"""One leased adaptive section per tick. No auto-replay of uncertain creates."""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL
import json
import logging
import math
from time import monotonic
from .adaptive_planning import SectionSpec, SectionContract, AdaptiveError
from .section_repository import validate_checkpoint
from .planning_repository import JobRepositoryError
from .planning_worker import _provider_diagnostic
from .adaptive_prompts import build_adaptive_prompt
from .openai_output_stream import OutputStreamError


_logger = logging.getLogger('uvicorn.error')


def _timing(phase, seconds, *, status=None):
    """Aggregate timings only: no request IDs, preferences, outputs or error text."""
    try:
        if type(phase) is not str or phase not in {'create_ack', 'provider_wait', 'validation', 'research_create_ack', 'research_provider_wait', 'research_validation'}:
            return
        if type(seconds) not in (int, float) or not math.isfinite(seconds):
            return
        metadata = {'phase': phase, 'elapsed_ms': round(min(86400, max(0, seconds)) * 1000)}
        if type(status) is str and status in {'queued', 'in_progress', 'completed', 'failed', 'incomplete', 'cancelled'}:
            metadata['status'] = status
        _logger.info('Adaptive timing: %s', json.dumps(metadata, sort_keys=True))
    except Exception:
        # Observability must never prevent persisting an already-paid response ID.
        pass


def next_identity(plan):
    return str(uuid5(NAMESPACE_URL, 'adaptive-section:'+plan['id']+':'+str(plan['next_date'])))


class AdaptivePlanningWorker:
    def __init__(self, repository, client, *, enabled=False, worker_id=None,
                 clock=lambda: datetime.now(timezone.utc), deadline_seconds=480, research_context=None, preview_store=None, research_request=None):
        if enabled is not True or not 1 <= deadline_seconds <= 1800:
            raise ValueError('Explicit adaptive activation and bounded deadline required.')
        self.repository, self.client = repository, client
        self.worker_id, self.clock = worker_id or str(uuid4()), clock
        self.deadline_seconds = deadline_seconds
        self.research_context = research_context
        self.research_request = research_request
        self.preview_store = preview_store
        self.immediate_followup = False

    async def _transition(self, section, status, **kwargs):
        return await self.repository.transition(section['user_id'], section['id'], section['lease_token'],
            section['version'], status, **kwargs)

    async def schedule_next(self, owner, plan_id):
        plan = await self.repository.get_plan(owner, plan_id)
        if plan['status'] == 'active' and not plan.get('active_section') and plan.get('next_date'):
            try:
                return await self.repository.next_section(owner, plan_id, next_identity(plan))
            except JobRepositoryError as error:
                if error.code != 'SECTION_RESOURCE_LIMIT': raise
                current = await self.repository.get_plan(owner,plan_id)
                if current.get('pause_reason') != 'STORAGE_LIMIT': raise
                return None
        return None

    async def tick(self):
        self.immediate_followup = False
        section = await self.repository.claim_next(self.worker_id)
        if section is None: return None
        plan = await self.repository.get_plan(section['user_id'], section['plan_id'])
        try:
            recent_rows = sorted(await self.repository.recent_checkpoints(section['user_id'],section['plan_id']), key=lambda row:row['sequence'])
            recent_titles = [a['title'] for row in recent_rows if row['status']=='succeeded' and row['sequence']<section['sequence'] for day in row['checkpoint']['itinerary']['days'] for a in day['activities'] if a['kind']=='main'][-48:]
            spec = SectionSpec.from_manifest(plan['preferences'], next_date=section['start_date'],
                spent_cents=plan['total_budget_cents']-section['budget_limit_cents'],
                previous_boundary=section['input_boundary'] if section['start_date'] != plan['start_date'] else None,
                section_days=(datetime.fromisoformat(section['end_date'])-datetime.fromisoformat(section['start_date'])).days+1,
                journey_strategy=plan.get('journey_strategy'), recent_activities=recent_titles)
            contract = SectionContract(spec,allow_research=plan.get("research_on_demand") is True)
        except Exception as error:
            return await self._transition(section, 'failed', error_code=error.code if isinstance(error,AdaptiveError) else 'SECTION_INVALID_RESULT')
        if section['status'] == 'queued':
            prompt = build_adaptive_prompt(spec)
            research_text = ''
            if plan.get('research_required') or plan.get('research_latest') or section.get('research_source_id'):
                try:
                    if not section.get('research_source_id'): raise ValueError()
                    if self.research_context is None: raise ValueError()
                    research_text = await self.research_context(section)
                except Exception:
                    return await self._transition(section, 'failed', error_code='SECTION_RESEARCH_UNAVAILABLE')
            section = await self._transition(section, 'submitting')
            started = monotonic()
            if self.preview_store is not None:
                return await self._create_stream(section, prompt.messages[0].content + '\n' + contract.instructions,
                    prompt.messages[1].content + research_text, contract.schema)
            try:
                response = await self.client.create(prompt.messages[0].content + '\n' + contract.instructions,
                    prompt.messages[1].content + research_text, contract.schema)
            except Exception as error:
                _provider_diagnostic('create', error=error)
                return await self._transition(section, 'submission_unknown' if getattr(error, 'ambiguous_create', True) else 'failed',
                    error_code='SECTION_SUBMISSION_UNCONFIRMED' if getattr(error, 'ambiguous_create', True) else 'SECTION_PROVIDER_REJECTED')
            acknowledged = monotonic()
            # Persist response ID before retrieving; lost-CAS must never cancel
            # another worker's active response or create again.
            result = await self._transition(section, 'running', provider_response_id=response.response_id)
            _timing('create_ack', acknowledged-started, status=response.status)
            return result
        if section['status'] != 'running' or not section.get('provider_response_id'):
            raise JobRepositoryError('SECTION_INVALID_CLAIM')
        submitted = datetime.fromisoformat(section['submitted_at'].replace('Z', '+00:00'))
        try:
            response = await self.client.retrieve(section['provider_response_id'])
        except Exception as error:
            _provider_diagnostic('retrieve', error=error)
            if getattr(error, 'http_status', None) in {401, 403}:
                return await self._transition(section, 'failed', error_code='SECTION_PROVIDER_REJECTED')
            if getattr(error, 'http_status', None) == 404:
                return await self._transition(section, 'failed', error_code='SECTION_RESPONSE_UNAVAILABLE')
            if (self.clock()-submitted).total_seconds() >= self.deadline_seconds:
                return await self._deadline(section)
            return await self._transition(section, 'running', error_code='SECTION_STREAM_FINAL_ONLY' if section.get('error_code')=='SECTION_STREAM_FINAL_ONLY' else 'SECTION_POLL_UNCONFIRMED')
        if response.response_id != section['provider_response_id']:
            return await self._transition(section, 'failed', error_code='SECTION_RESPONSE_MISMATCH')
        if response.status in {'queued', 'in_progress'}:
            if (self.clock()-submitted).total_seconds() >= self.deadline_seconds:
                return await self._deadline(section)
            if self.preview_store is not None and section.get('error_code')!='SECTION_STREAM_FINAL_ONLY':
                state = await self.preview_store.load(section['user_id'],section['plan_id'],section['id'],section['lease_token'],section['version'])
                stream = self.client.resume_stream(section['provider_response_id'],starting_after=state.cursor,prior_text_bytes=len(state.output_text.encode()))
                lease_left = (datetime.fromisoformat(section['lease_until'].replace('Z','+00:00'))-self.clock()).total_seconds()
                return await self._consume_stream(section, stream, state,stop=monotonic()+max(0,min(30,lease_left-5,self.deadline_seconds-(self.clock()-submitted).total_seconds())))
            return await self._transition(section, 'running',error_code='SECTION_STREAM_FINAL_ONLY' if section.get('error_code')=='SECTION_STREAM_FINAL_ONLY' else None)
        _timing('provider_wait', (self.clock()-submitted).total_seconds(), status=response.status)
        if response.status != 'completed' or response.refused:
            _provider_diagnostic('retrieve', status=response.status, refused=response.refused)
            code = 'SECTION_PROVIDER_INCOMPLETE' if response.status == 'incomplete' else 'SECTION_PROVIDER_FAILED'
            capable = getattr(getattr(self.repository, 'gateway', None), 'supports_auto_recovery', False) is True
            reason = getattr(response, 'recovery_reason', None)
            if capable and not response.refused:
                if response.status == 'failed' and reason in {'server_error', 'rate_limit_exceeded'}:
                    code = 'SECTION_AUTO_RETRYABLE_FAILURE'
                elif response.status == 'incomplete' and reason == 'max_output_tokens':
                    code = 'SECTION_AUTO_RETRYABLE_INCOMPLETE'
            return await self._transition(section, 'failed', error_code=code)
        started = monotonic()
        try:
            checkpoint = contract.decode(response.output_text)
            if checkpoint.get('status') == 'needs_research':
                if self.research_request is None:
                    return await self._transition(section,'failed',error_code='SECTION_RESEARCH_UNAVAILABLE')
                result = await self.research_request(section,checkpoint['kind'])
                # Only a confirmed durable handoff can bypass the normal poll delay.
                # This does not replay a create or bypass research admission limits.
                self.immediate_followup = (type(result) is dict and result.get('id') == section['id']
                    and result.get('status') == 'failed' and result.get('error_code') == 'SECTION_RESEARCH_REQUESTED')
                return result
            if checkpoint.get('status') == 'needs_changes':
                return await self._transition(section, 'failed', error_code='SECTION_CONSTRAINT_CONFLICT',
                    failure_details={k: checkpoint[k] for k in ('applicability','explanation','recommendations')})
            validate_checkpoint(checkpoint, section)
        except (AdaptiveError, JobRepositoryError) as error:
            return await self._transition(section, 'failed', error_code=getattr(error, 'code', 'SECTION_INVALID_RESULT'))
        _timing('validation', monotonic()-started)
        result = await self._transition(section, 'succeeded', checkpoint=checkpoint)
        # A crash here must be recoverable by coordinator reconciliation using
        # deterministic next identity, not by regenerating this checkpoint.
        successor = await self.schedule_next(section['user_id'], section['plan_id'])
        self.immediate_followup = successor is not None
        return result


    async def _deadline(self, section):
        # No new create: even an unconfirmed cancellation cannot authorize replay.
        failed = await self._transition(section, 'failed', error_code='SECTION_DEADLINE_REACHED')
        try: await self.client.cancel(section['provider_response_id'])
        except Exception as error: _provider_diagnostic('cancel', error=error)
        return failed

    async def _create_stream(self, section, system, user, schema):
        started = monotonic()
        stop = started+30
        stream = self.client.create_stream(system,user,schema)
        try:
            try:
                first = await asyncio.wait_for(anext(stream),30)
            except Exception as error:
                # A parsed ID is still authoritative even if the first event
                # could not be yielded. Never turn that into another create.
                known = getattr(error,'response_id',None)
                if known:
                    return await self._transition(section,'running',provider_response_id=known,error_code='SECTION_STREAM_FINAL_ONLY' if getattr(error,'code',None)=='STREAM_FINAL_ONLY' else None)
                ambiguous = getattr(error,'ambiguous_create',True)
                return await self._transition(section,'submission_unknown' if ambiguous else 'failed',
                    error_code='SECTION_SUBMISSION_UNCONFIRMED' if ambiguous else 'SECTION_PROVIDER_REJECTED')
            acknowledged = monotonic()
            section = await self._transition(section,'running',provider_response_id=first.response_id)
            _timing('create_ack', acknowledged-started)
            section = await self.repository.claim(section['user_id'],section['id'],self.worker_id)
            state = await self.preview_store.load(section['user_id'],section['plan_id'],section['id'],section['lease_token'],section['version'])
            return await self._consume_stream(section,stream,state,first=first,stop=stop)
        finally:
            with suppress(Exception): await stream.aclose()

    async def _consume_stream(self, section, stream, state, *, first=None, stop=None):
        """Bounded connection, batched durable output only; SSE never accepts."""
        stop = stop if stop is not None else monotonic()+30
        last_flush = monotonic()
        cursor = state.cursor
        delta = ''
        pending = None
        terminal_committed = False

        async def flush():
            nonlocal state,delta,last_flush
            if cursor<=state.cursor: return
            state = await self.preview_store.append(section['user_id'],section['plan_id'],section['id'],
                section['lease_token'],section['version'],response_id=section['provider_response_id'],
                expected_cursor=state.cursor,cursor=cursor,text_delta=delta)
            section.update(version=state.version,lease_until=state.lease_until)
            delta='';last_flush=monotonic()

        try:
            while monotonic()<stop:
                if first is not None:
                    event,first=first,None
                else:
                    if pending is None: pending=asyncio.create_task(anext(stream))
                    wait=max(0,min(stop-monotonic(),0.5-(monotonic()-last_flush))) if cursor>state.cursor else max(0,stop-monotonic())
                    done,_=await asyncio.wait({pending},timeout=wait)
                    if not done:
                        await flush()
                        continue
                    task,pending=pending,None
                    try: event=task.result()
                    except StopAsyncIteration: break
                if event.response_id!=section['provider_response_id']:
                    raise OutputStreamError('STREAM_INVALID_RESPONSE',response_id=section['provider_response_id'])
                if event.sequence_number<=cursor:
                    raise OutputStreamError('STREAM_INVALID_RESPONSE',response_id=section['provider_response_id'])
                cursor=event.sequence_number
                if event.kind=='text_delta': delta+=event.text_delta
                if len(delta.encode())>=4096 or monotonic()-last_flush>=0.5 or event.kind=='terminal': await flush()
                if event.kind=='terminal':
                    terminal_committed = True
                    break
            await flush()
        except (OutputStreamError,TimeoutError,ConnectionError) as error:
            if getattr(error,'code',None)=='STREAM_FINAL_ONLY':
                return await self._transition(section,'running',error_code='SECTION_STREAM_FINAL_ONLY')
            if getattr(error,'code',None)=='STREAM_INVALID_RESPONSE':
                return await self._transition(section,'failed',error_code='SECTION_INVALID_RESULT')
            # Interruptions preserve the last committed prefix and provider ID.
            try: await flush()
            except JobRepositoryError as failure:
                if failure.code=='SECTION_RESOURCE_LIMIT':
                    return await self._transition(section,'running',error_code='SECTION_RESOURCE_LIMIT')
                if failure.code=='SECTION_PREVIEW_INVALID':
                    return await self._transition(section,'failed',error_code='SECTION_INVALID_RESULT')
                raise
        except JobRepositoryError as error:
            if error.code in {'SECTION_PREVIEW_INVALID','SECTION_RESOURCE_LIMIT'}:
                return await self._transition(section,'failed' if error.code=='SECTION_PREVIEW_INVALID' else 'running',error_code='SECTION_INVALID_RESULT' if error.code=='SECTION_PREVIEW_INVALID' else 'SECTION_RESOURCE_LIMIT')
            raise  # A stale/unconfirmed CAS must not mutate or cancel this job.
        finally:
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError,Exception): await pending
            with suppress(Exception): await stream.aclose()
        result = await self._transition(section,'running')
        self.immediate_followup = terminal_committed
        return result
