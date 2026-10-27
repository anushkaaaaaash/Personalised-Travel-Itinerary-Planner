"""One leased adaptive section per tick. No auto-replay of uncertain creates."""
from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL
from .adaptive_planning import SectionSpec, SectionContract, AdaptiveError
from .section_repository import validate_checkpoint
from .planning_repository import JobRepositoryError
from .planning_worker import _provider_diagnostic
from .prompts import build_itinerary_prompt


def next_identity(plan):
    return str(uuid5(NAMESPACE_URL, 'adaptive-section:'+plan['id']+':'+str(plan['next_date'])))


class AdaptivePlanningWorker:
    def __init__(self, repository, client, *, enabled=False, worker_id=None,
                 clock=lambda: datetime.now(timezone.utc), deadline_seconds=480):
        if enabled is not True or not 1 <= deadline_seconds <= 480:
            raise ValueError('Explicit adaptive activation and bounded deadline required.')
        self.repository, self.client = repository, client
        self.worker_id, self.clock = worker_id or str(uuid4()), clock
        self.deadline_seconds = deadline_seconds

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
            contract = SectionContract(spec)
        except Exception as error:
            return await self._transition(section, 'failed', error_code=error.code if isinstance(error,AdaptiveError) else 'SECTION_INVALID_RESULT')
        if section['status'] == 'queued':
            section = await self._transition(section, 'submitting')
            prompt = build_itinerary_prompt(spec.preferences)
            try:
                response = await self.client.create(prompt.messages[0].content + '\n' + contract.instructions,
                    prompt.messages[1].content, contract.schema)
            except Exception as error:
                _provider_diagnostic('create', error=error)
                return await self._transition(section, 'submission_unknown' if getattr(error, 'ambiguous_create', True) else 'failed',
                    error_code='SECTION_SUBMISSION_UNCONFIRMED' if getattr(error, 'ambiguous_create', True) else 'SECTION_PROVIDER_REJECTED')
            # Persist response ID before retrieving; lost-CAS must never cancel
            # another worker's active response or create again.
            return await self._transition(section, 'running', provider_response_id=response.response_id)
        if section['status'] != 'running' or not section.get('provider_response_id'):
            raise JobRepositoryError('SECTION_INVALID_CLAIM')
        submitted = datetime.fromisoformat(section['submitted_at'].replace('Z', '+00:00'))
        if (self.clock()-submitted).total_seconds() >= self.deadline_seconds:
            failed = await self._transition(section, 'failed', error_code='SECTION_DEADLINE_REACHED')
            try: await self.client.cancel(section['provider_response_id'])
            except Exception as error: _provider_diagnostic('cancel', error=error)
            return failed
        try:
            response = await self.client.retrieve(section['provider_response_id'])
        except Exception as error:
            _provider_diagnostic('retrieve', error=error)
            return await self._transition(section, 'running', error_code='SECTION_POLL_UNCONFIRMED')
        if (self.clock()-submitted).total_seconds() >= self.deadline_seconds:
            return await self._transition(section, 'failed', error_code='SECTION_DEADLINE_REACHED')
        if response.response_id != section['provider_response_id']:
            return await self._transition(section, 'failed', error_code='SECTION_RESPONSE_MISMATCH')
        if response.status in {'queued', 'in_progress'}:
            return await self._transition(section, 'running')
        if response.status != 'completed' or response.refused:
            _provider_diagnostic('retrieve', status=response.status, refused=response.refused)
            return await self._transition(section, 'failed', error_code='SECTION_PROVIDER_INCOMPLETE' if response.status == 'incomplete' else 'SECTION_PROVIDER_FAILED')
        try:
            checkpoint = contract.decode(response.output_text)
            if checkpoint.get('status') == 'needs_changes':
                return await self._transition(section, 'failed', error_code='SECTION_CONSTRAINT_CONFLICT',
                    failure_details={k: checkpoint[k] for k in ('applicability','explanation','recommendations')})
            validate_checkpoint(checkpoint, section)
        except (AdaptiveError, JobRepositoryError) as error:
            return await self._transition(section, 'failed', error_code=getattr(error, 'code', 'SECTION_INVALID_RESULT'))
        result = await self._transition(section, 'succeeded', checkpoint=checkpoint)
        # A crash here must be recoverable by coordinator reconciliation using
        # deterministic next identity, not by regenerating this checkpoint.
        await self.schedule_next(section['user_id'], section['plan_id'])
        return result
