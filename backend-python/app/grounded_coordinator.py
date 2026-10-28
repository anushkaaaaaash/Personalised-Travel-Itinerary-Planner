"""Owner-scoped research/draft facade; no raw stream or private query forwarding."""
from dataclasses import asdict
import time
from datetime import datetime, timezone
from .adaptive_coordinator import AdaptiveCoordinator
from .adaptive_research import validate_research_pack, build_public_query
from .itineraries import ItineraryDay
from .planning_repository import JobRepositoryError

RESEARCH_ERRORS=frozenset({'RESEARCH_PROVIDER_REJECTED','RESEARCH_DEADLINE_REACHED','RESEARCH_SOURCES_UNCONFIRMED',
    'RESEARCH_SUBMISSION_UNCONFIRMED','RESEARCH_POLL_UNCONFIRMED','RESEARCH_PROVIDER_FAILED','RESEARCH_RESPONSE_MISMATCH','RESEARCH_QUERY_INVALID'})

class GroundedCoordinator(AdaptiveCoordinator):
    def __init__(self,*args,research_repository,revision_repository=None,streaming_enabled=False,clock=lambda:datetime.now(timezone.utc),**kwargs):
        super().__init__(*args,**kwargs)
        self.research_repository=research_repository
        self.revision_repository=revision_repository
        self.clock=clock
        self.streaming_enabled=streaming_enabled is True

    def public_policy(self):
        return {'sectionDays':3,'maxSubmissionsPerRun':self.run_allowance,
            'researchEnabled':True,'maxWebSearchCalls':6,'researchMode':'on_demand',
            'provisionalDayPreviews':self.streaming_enabled,'responseDeadlineMinutes':30,
            'selectedDayRevisions':self.revision_repository is not None}

    async def verify_ready(self):
        await super().verify_ready()
        self._ready=False
        try:
            await self.research_repository.verify_ready()
            if self.revision_repository is not None:await self.revision_repository.verify_ready()
            self._ready=True
            self._checked=time.monotonic()
        except Exception:
            self._ready=False
            raise

    async def context(self,owner,plan_id,after_sequence=0):
        result=await super().context(owner,plan_id,after_sequence)
        result['research']=None;result['draft']=None
        if result['plan']['status']=='expired':return result
        plan=await self.repository.get_plan(owner,plan_id)
        if plan.get('active_section') and result['plan'].get('activeSection'):
            active=await self.repository.get_section(owner,plan['active_section'])
            if active.get('error_code') in {'SECTION_RESEARCH_UNAVAILABLE','SECTION_RESEARCH_REQUESTED'}:
                result['plan']['activeSection']['errorCode']=active['error_code']
        if plan.get('research_required') or plan.get('research_on_demand'):
            if plan.get('active_research'):
                job=await self.research_repository.get(owner,plan['active_research'])
            else:job=await self.research_repository.latest(owner,plan_id)
            if job and job['plan_id']!=plan_id:raise JobRepositoryError('RESEARCH_CONTEXT_INVALID')
            research={'status':job['status'] if job else 'queued','toolCallsReserved':plan.get('tool_calls_reserved',0),
                'toolCallLimit':6,'errorCode':job.get('error_code') if job and job.get('error_code') in RESEARCH_ERRORS else None,
                'receivedAt':None,'expiresAt':None,'sources':[],'citations':[],'text':'','applicability':'unknown'}
            if job and job['status']=='succeeded':
                try:pack=validate_research_pack(job['sourcepack'],query=job['query'],phase=job['phase'],now=self.clock())
                except Exception:
                    research.update(status='failed',errorCode='RESEARCH_SOURCES_UNCONFIRMED')
                else:research.update(receivedAt=pack['checked_at'],expiresAt=pack['expires_at'],
                    sources=[{'url':s['url'],'title':s['title']} for s in pack['sources'] if s['consulted'] and s['cited']],
                    citations=pack['citations'],text=pack['text'])
            if research['status'] not in {'queued','submitting','running','succeeded','failed','submission_unknown','cancelled'}:
                raise JobRepositoryError('RESEARCH_CONTEXT_INVALID')
            if type(research['toolCallsReserved']) is not int or not 0<=research['toolCallsReserved']<=6:
                raise JobRepositoryError('RESEARCH_CONTEXT_INVALID')
            if not job and plan.get('research_error')=='RESEARCH_QUERY_INVALID':
                research.update(status='failed',errorCode='RESEARCH_QUERY_INVALID')
                result['research']=research
            else:result['research']=research if job else None
            if plan.get('pause_reason') in {'RESEARCH_FAILED','RESEARCH_SUBMISSION_UNKNOWN','RESEARCH_ALLOWANCE_REACHED'}:
                result['plan']['pauseReason']=plan['pause_reason']
        if plan.get('active_section') and plan['status']=='active':
            section=await self.repository.get_section(owner,plan['active_section'])
            if section['plan_id']!=plan_id:raise JobRepositoryError('SECTION_INVALID_RESULT')
            preview=section.get('stream_preview')
            if section['status']=='running' and section.get('error_code')!='SECTION_STREAM_FINAL_ONLY' and preview:
                if type(preview) is not dict or preview.get('status')!='draft' or preview.get('accepted') is not False:
                    raise JobRepositoryError('SECTION_PREVIEW_INVALID')
                rows=preview.get('days')
                if type(rows) is not list or len(rows)>3:raise JobRepositoryError('SECTION_PREVIEW_INVALID')
                days=[ItineraryDay.model_validate(day).model_dump(mode='json') for day in rows]
                from datetime import date,timedelta
                expected=[(date.fromisoformat(section['start_date'])+timedelta(days=i)).isoformat() for i in range(len(days))]
                if [d['date'] for d in days]!=expected or (expected and expected[-1]>section['end_date']):
                    raise JobRepositoryError('SECTION_PREVIEW_INVALID')
                result['draft']={'status':'draft','accepted':False,'days':days,
                    'sectionStart':section['start_date'],'sectionEnd':section['end_date'],'currency':result['preferences']['currency']}
        return result

    async def _revision(self,owner,plan_id,revision_id):
        if self.revision_repository is None:raise JobRepositoryError('REVISION_DISABLED',404)
        try:row=await self.revision_repository.get(owner,revision_id)
        except JobRepositoryError as error:
            if error.code=='REVISION_NOT_FOUND_OR_CONFLICT':raise JobRepositoryError('REVISION_NOT_FOUND',404) from None
            raise
        if row is None or row['plan_id']!=plan_id:raise JobRepositoryError('REVISION_NOT_FOUND',404)
        return row

    async def revision_context(self,owner,plan_id,revision_id):
        from .revision_repository import public_revision
        return {'revision':public_revision(await self._revision(owner,plan_id,revision_id))}

    async def revision_request_context(self,owner,plan_id,request_id):
        from .revision_repository import public_revision
        if self.revision_repository is None:raise JobRepositoryError('REVISION_DISABLED',404)
        row=await self.revision_repository.lookup(owner,request_id)
        if row is None or row['plan_id']!=plan_id:raise JobRepositoryError('REVISION_NOT_FOUND',404)
        return {'revision':public_revision(row)}

    async def continue_revisions(self,owner,plan_id,request_id):
        await self.verify_ready()
        if self.revision_repository is None:raise JobRepositoryError('REVISION_DISABLED',404)
        row=await self.revision_repository.continue_run(owner,plan_id,request_id)
        if row.get('plan_id')!=plan_id or row.get('user_id')!=owner:raise JobRepositoryError('REVISION_NOT_FOUND_OR_CONFLICT',409)
        remaining=row.get('remaining_creates')
        if type(remaining) is not int or not 0<=remaining<=12:raise JobRepositoryError('REVISION_STORAGE_UNCONFIRMED',503)
        return {'basePlanId':plan_id,'remainingCreates':remaining}

    async def current_revision_context(self,owner,plan_id):
        from .revision_repository import public_revision
        if self.revision_repository is None:raise JobRepositoryError('REVISION_DISABLED',404)
        row=await self.revision_repository.current(owner,plan_id)
        if row is None:raise JobRepositoryError('REVISION_NOT_FOUND',404)
        if row['plan_id']!=plan_id:raise JobRepositoryError('REVISION_NOT_FOUND',404)
        return {'revision':public_revision(row)}

    async def start_revision(self,owner,plan_id,request):
        from .adaptive_revision import RevisionRequest
        from .revision_repository import public_revision
        await self.verify_ready()
        if self.revision_repository is None:raise JobRepositoryError('REVISION_DISABLED',404)
        from .adaptive_planning import AdaptiveError
        try:RevisionRequest.parse(request)
        except AdaptiveError:raise JobRepositoryError("REVISION_INVALID_REQUEST",400) from None
        row=await self.revision_repository.reserve(owner,plan_id,request)
        return {'revision':public_revision(row)}

    async def revision_action(self,owner,plan_id,revision_id,action,request_id=None):
        from .revision_repository import public_revision
        await self.verify_ready()
        await self._revision(owner,plan_id,revision_id)
        if action=='accept':row=await self.revision_repository.accept(owner,revision_id)
        elif action=='reject':row=await self.revision_repository.reject(owner,revision_id)
        elif action=='retry':row=await self.revision_repository.retry(owner,revision_id,request_id)
        else:raise JobRepositoryError('REVISION_NOT_FOUND_OR_CONFLICT',409)
        return {'revision':public_revision(row)}

    async def retry_research(self,owner,plan_id,request_id):
        await self.verify_ready()
        plan=await self.repository.get_plan(owner,plan_id)
        if plan['status']!='paused' or plan.get('pause_reason')!='RESEARCH_FAILED' or not plan.get('active_research'):
            raise JobRepositoryError('RESEARCH_RETRY_NOT_ALLOWED',409)
        prior=await self.research_repository.get(owner,plan['active_research'])
        if prior['plan_id']!=plan_id or prior['status']!='failed':raise JobRepositoryError('RESEARCH_RETRY_NOT_ALLOWED',409)
        from .adaptive_research import build_trigger_query
        query=asdict(build_trigger_query(plan['preferences'],prior['query']['researchTopic']))
        query['venueLabels']=list(query['venueLabels']);query['routeLabels']=list(query['routeLabels'])
        await self.research_repository.reserve(owner,plan_id,request_id,query,phase='refresh')
        return await self.context(owner,plan_id)

    async def cancel(self,owner,plan_id):
        plan=await self.repository.get_plan(owner,plan_id)
        job=await self.research_repository.get(owner,plan['active_research']) if plan.get('active_research') else None
        result=await super().cancel(owner,plan_id)
        if job and job.get('provider_response_id'):
            try:await self.worker.research.client.cancel(job['provider_response_id'])
            except Exception:pass  # Durable stop is not an upstream billing guarantee.
        return result

    async def close(self):
        try:await super().close()
        finally:
            close=getattr(self.worker.research.client,'close',None)
            if close:await close()
