"""Owner-scoped adaptive API facade with bounded, paginated public snapshots."""
import asyncio
from datetime import date, datetime, timezone
import logging
import time
from .models import TripPreferences
from .planning_repository import JobRepositoryError, identity
from .section_repository import validate_checkpoint
from .adaptive_planning import RECOMMENDATION_FIELDS

ERROR_CODES = frozenset({'SECTION_SUBMISSION_UNCONFIRMED','SECTION_PROVIDER_REJECTED','SECTION_DEADLINE_REACHED',
    'SECTION_POLL_UNCONFIRMED','SECTION_RESPONSE_MISMATCH','SECTION_OUTPUT_LIMIT','SECTION_PROVIDER_INCOMPLETE',
    'SECTION_PROVIDER_FAILED','SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED','SECTION_INVALID_RESULT',
    'SECTION_CONTINUITY_CONFLICT','SECTION_RETURN_MISSING','SECTION_REST_CONFLICT','SECTION_TRAVEL_DOUBLE_COUNT',
    'SECTION_BUDGET_EXCEEDED','SECTION_INVALID_COST','SECTION_CHECKPOINT_INVALID','SECTION_STRATEGY_INVALID','SECTION_STRATEGY_MISSING','SECTION_STRATEGY_CONFLICT','SECTION_TRANSFER_MISSING','SECTION_REPEAT_CONFLICT'})
PAUSE_REASONS = frozenset({'RESOURCE_ALLOWANCE_REACHED','SECTION_FAILED','SUBMISSION_UNKNOWN','CONSTRAINT_CONFLICT','BUDGET_EXHAUSTED','STORAGE_LIMIT'})


def public_failure_details(value):
    if value is None: return None
    if type(value) is not dict or set(value) != {'applicability','explanation','recommendations'} or value['applicability'] != 'proposed':
        raise JobRepositoryError('SECTION_INVALID_RESULT')
    if type(value['explanation']) is not str or not 1 <= len(value['explanation']) <= 500:
        raise JobRepositoryError('SECTION_INVALID_RESULT')
    items = value['recommendations']
    if type(items) is not list or not 1 <= len(items) <= 3: raise JobRepositoryError('SECTION_INVALID_RESULT')
    for item in items:
        if type(item) is not dict or set(item) != {'field','reason','suggestion'} or item['field'] not in RECOMMENDATION_FIELDS:
            raise JobRepositoryError('SECTION_INVALID_RESULT')
        if any(type(item[k]) is not str or not 1 <= len(item[k]) <= 500 for k in ('reason','suggestion')):
            raise JobRepositoryError('SECTION_INVALID_RESULT')
    return value


class AdaptiveCoordinator:
    def __init__(self, repository, worker, *, enabled=False, require_health=True, run_allowance=12, maintenance=None):
        if enabled is not True: raise ValueError('Explicit adaptive activation required.')
        if type(run_allowance) is not int or not 1 <= run_allowance <= 12: raise ValueError('Invalid processing allowance.')
        self.run_allowance=run_allowance
        self.repository, self.worker, self.require_health = repository, worker, require_health
        self._ready = False; self._checked = 0.0
        self._maintenance=maintenance; self._maintained=None
        self._maintenance_lock=asyncio.Lock()

    async def verify_ready(self):
        try:
            if self._maintenance is not None:
                async with self._maintenance_lock:
                    now=time.monotonic()
                    if self._maintained is None or now-self._maintained >= 30:
                        await self._maintenance()
                        self._maintained=time.monotonic()
            await self.repository.verify_ready()
            self._ready = True; self._checked = time.monotonic()
        except Exception:
            self._ready = False
            raise

    def capability_ready(self):
        return self.require_health and self._ready and 0 <= time.monotonic()-self._checked <= 15

    async def context(self, owner, plan_id, after_sequence=0):
        owner = identity(owner)
        try:
            plan = await self.repository.get_plan(owner, plan_id)
        except JobRepositoryError as error:
            if error.code=='SECTION_NOT_FOUND_OR_CONFLICT': raise JobRepositoryError('SECTION_NOT_FOUND',404) from None
            raise
        if plan['user_id'] != owner: raise JobRepositoryError('SECTION_NOT_FOUND',404)
        preferences = TripPreferences.model_validate(plan['preferences']).model_dump(mode='json')
        expired = datetime.now(timezone.utc) >= datetime.fromisoformat(plan['expires_at'].replace('Z','+00:00'))
        status = 'expired' if expired else plan['status']
        if status not in {'active','paused','completed','cancelled','expired'}: raise JobRepositoryError()
        active = None
        if not expired and plan.get('active_section'):
            section = await self.repository.get_section(owner, plan['active_section'])
            if section['plan_id'] != plan['id']: raise JobRepositoryError()
            active = {'id':identity(section['id']), 'status':section['status'],
                'errorCode':section.get('error_code') if section.get('error_code') in ERROR_CODES else None,
                'failureDetails':public_failure_details(section.get('failure_details'))}
        pause_reason = plan.get('pause_reason') if plan.get('pause_reason') in PAUSE_REASONS else None
        if status=='paused' and pause_reason=='SECTION_FAILED' and active:
            pause_reason = {'SECTION_CONSTRAINT_CONFLICT':'CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED':'BUDGET_EXHAUSTED'}.get(active['errorCode'],pause_reason)
        public = {'id':identity(plan['id']), 'requestId':identity(plan['request_id']), 'status':status,
            'completedDays':plan['completed_days'], 'totalDays':(date.fromisoformat(preferences['endDate'])-date.fromisoformat(preferences['startDate'])).days+1,
            'estimatedSections':((date.fromisoformat(preferences['endDate'])-date.fromisoformat(preferences['startDate'])).days+3)//3,
            'runAllowance':self.run_allowance, 'storageLimitBytes':plan.get('storage_limit_bytes',16777216),
            'storageUsedBytes':plan.get('storage_used_bytes',0), 'globalStorageLimitBytes':plan.get('global_storage_limit_bytes',67108864),
            'storagePauseScope':plan.get('storage_pause_scope'), 'remainingCreates':plan['remaining_creates'], 'spentCents':plan['spent_cents'],
            'totalBudgetCents':plan['total_budget_cents'], 'pauseReason':pause_reason,
            'expiresAt':plan['expires_at'], 'activeSection':active}
        rows = [] if expired else await self.repository.list_sections(owner, plan_id, after_sequence=after_sequence, limit=3)
        sections = []
        for row in rows:
            if row['plan_id'] != plan['id']: raise JobRepositoryError()
            if row['status'] != 'succeeded': continue
            checkpoint = validate_checkpoint(row['checkpoint'],row)
            sections.append({'id':identity(row['id']), 'sequence':row['sequence'], 'startDate':row['start_date'],
                'endDate':row['end_date'], 'checkpoint':checkpoint})
        return {'plan':public, 'preferences':None if expired else preferences, 'sections':sections,
            'nextCursor':rows[-1]['sequence'] if len(rows)==3 else None}

    async def request_context(self, owner, request_id):
        plan = await self.repository.find_request(owner,request_id)
        if plan is None: raise JobRepositoryError('SECTION_NOT_FOUND',404)
        return await self.context(owner, plan['id'])

    async def start(self, owner, request_id, preferences):
        await self.verify_ready()
        plan = await self.repository.create_plan(owner,request_id,preferences,run_allowance=self.run_allowance)
        await self.worker.schedule_next(owner,plan['id'])
        return await self.context(owner,plan['id'])

    async def continue_run(self, owner, plan_id, request_id):
        await self.verify_ready()
        plan = await self.repository.get_plan(owner,plan_id)
        if plan.get('active_section'):
            section = await self.repository.get_section(owner,plan['active_section'])
            if section.get('error_code') in {'SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED'}:
                raise JobRepositoryError('SECTION_RETRY_NOT_ALLOWED',409)
        await self.repository.continue_run(owner,plan_id,request_id,run_allowance=self.run_allowance)
        await self.worker.schedule_next(owner,plan_id)
        return await self.context(owner,plan_id)

    async def retry(self, owner, plan_id, section_id, request_id):
        await self.verify_ready()
        section = await self.repository.get_section(owner,section_id)
        from .section_repository import proposed_constraint_retryable
        proposed_retry = (getattr(getattr(self.repository,'gateway',None),'supports_proposed_constraint_retry',False) is True and proposed_constraint_retryable(section))
        if section['plan_id'] != plan_id or section['status'] != 'failed' or section.get('error_code')=='SECTION_BUDGET_EXHAUSTED' or (section.get('error_code')=='SECTION_CONSTRAINT_CONFLICT' and not proposed_retry):
            raise JobRepositoryError('SECTION_RETRY_NOT_ALLOWED',409)
        days = (date.fromisoformat(section['end_date'])-date.fromisoformat(section['start_date'])).days+1
        # An explicit retry of an oversized/invalid result gets less work, never
        # an automatic paid retry and never a shortened original trip.
        if section.get('error_code') in {'SECTION_OUTPUT_LIMIT','SECTION_PROVIDER_INCOMPLETE','SECTION_INVALID_RESULT'}:
            days = max(1,days//2)
        await self.repository.retry_failed(owner,section_id,request_id,section_days=days)
        return await self.context(owner,plan_id)

    async def cancel(self, owner, plan_id):
        plan = await self.repository.get_plan(owner,plan_id)
        section = await self.repository.get_section(owner,plan['active_section']) if plan.get('active_section') else None
        await self.repository.cancel_plan(owner,plan_id)
        if section and section.get('provider_response_id'):
            try: await self.worker.client.cancel(section['provider_response_id'])
            except Exception: pass  # confirmed local stop is not a billing guarantee
        return await self.context(owner,plan_id)

    async def run(self, stop, interval_seconds=5):
        while not stop.is_set():
            try:
                await self.verify_ready()
                await self.worker.tick()
            except asyncio.CancelledError: raise
            except Exception:
                logging.getLogger(__name__).warning('Adaptive planning worker unavailable; code=SECTION_WORKER_UNCONFIRMED')
            try: await asyncio.wait_for(stop.wait(),timeout=interval_seconds)
            except TimeoutError: pass

    async def close(self):
        close = getattr(self.worker.client,'close',None)
        if close: await close()
        storage_close=getattr(getattr(self.repository,'gateway',None),'close',None)
        if storage_close: await storage_close()
