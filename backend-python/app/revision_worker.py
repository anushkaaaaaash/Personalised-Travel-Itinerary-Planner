"""One lease-bound selected-day edit; no provider replay or auto-acceptance."""
from datetime import datetime,timezone
from uuid import uuid4
from .adaptive_revision import RevisionContract
from .adaptive_planning import AdaptiveError
from .planning_repository import JobRepositoryError
from .prompts import build_itinerary_prompt

class RevisionWorker:
    def __init__(self,repository,client,*,enabled=False,clock=lambda:datetime.now(timezone.utc),deadline_seconds=480):
        if enabled is not True or type(deadline_seconds) is not int or not 1<=deadline_seconds<=480:
            raise ValueError('Explicit revision activation and bounded deadline required')
        self.repository,self.client,self.clock,self.deadline_seconds=repository,client,clock,deadline_seconds
        self.worker_id=str(uuid4())

    async def _transition(self,j,status,**kwargs):
        return await self.repository.transition(j['user_id'],j['id'],j['lease_token'],j['version'],status,**kwargs)

    async def tick(self):
        j=await self.repository.claim_next(self.worker_id)
        if j is None:return None
        try:ctx=await self.repository.context(j['user_id'],j['id']);contract=RevisionContract(ctx)
        except (AdaptiveError,JobRepositoryError) as e:
            if isinstance(e,JobRepositoryError) and (e.status>=500 or e.code=='REVISION_NOT_FOUND_OR_CONFLICT'):raise
            return await self._transition(j,'failed',error_code=e.code)
        if j['status']=='queued':
            if (datetime.fromisoformat(j['expires_at'])-self.clock()).total_seconds()<480:
                return await self._transition(j,'failed',error_code='REVISION_INSUFFICIENT_RETENTION')
            prompt=build_itinerary_prompt(ctx.spec.preferences)
            try:j=await self._transition(j,'submitting')
            except JobRepositoryError as e:
                if e.code in {'REVISION_INSUFFICIENT_RETENTION','REVISION_ALLOWANCE_REACHED'}:
                    return await self._transition(j,'failed',error_code=e.code)
                raise
            try:response=await self.client.create(prompt.messages[0].content+'\n'+contract.instructions,
                prompt.messages[1].content+'\n'+contract.user_context,contract.schema)
            except Exception as e:
                uncertain=getattr(e,'ambiguous_create',True)
                return await self._transition(j,'submission_unknown' if uncertain else 'failed',
                    error_code='REVISION_SUBMISSION_UNCONFIRMED' if uncertain else 'REVISION_PROVIDER_REJECTED')
            return await self._transition(j,'running',provider_response_id=response.response_id)
        if j['status']!='running' or not j.get('provider_response_id'):raise JobRepositoryError('REVISION_INVALID_CLAIM')
        submitted=datetime.fromisoformat(j['submitted_at'])
        if (self.clock()-submitted).total_seconds()>=self.deadline_seconds:
            failed=await self._transition(j,'failed',error_code='REVISION_DEADLINE_REACHED')
            try:await self.client.cancel(j['provider_response_id'])
            except Exception:pass
            return failed
        try:response=await self.client.retrieve(j['provider_response_id'])
        except Exception:return await self._transition(j,'running',error_code='REVISION_POLL_UNCONFIRMED')
        if response.response_id!=j['provider_response_id']:return await self._transition(j,'failed',error_code='REVISION_RESPONSE_MISMATCH')
        if (self.clock()-submitted).total_seconds()>=self.deadline_seconds:return await self._transition(j,'failed',error_code='REVISION_DEADLINE_REACHED')
        if response.status in ('queued','in_progress'):return await self._transition(j,'running')
        if response.status!='completed' or response.refused:return await self._transition(j,'failed',error_code='REVISION_PROVIDER_FAILED')
        try:
            # Gateway re-runs this exact contract against its transaction's base.
            candidate=contract.decode(response.output_text)
            if isinstance(candidate,dict):return await self._transition(j,'failed',error_code='REVISION_CONSTRAINT_CONFLICT')
            return await self._transition(j,'candidate',output_text=response.output_text)
        except (AdaptiveError,JobRepositoryError) as e:
            if isinstance(e,JobRepositoryError) and (e.status>=500 or e.code in {'REVISION_NOT_FOUND_OR_CONFLICT','SECTION_NOT_FOUND_OR_CONFLICT'}):raise
            return await self._transition(j,'failed',error_code=e.code)
