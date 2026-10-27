"""Disabled, injected checkpoint persistence for adaptive multi-section planning.

No credentials, provider calls, or implicit retries. Requires separately reviewed
migration 005, gateway mappings, narrow role/RLS grants and a retention cleanup
process before activation. A section result lives in its own bounded row; there
is no aggregate itinerary blob and no overall trip-day limit here.
"""
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from .models import TripPreferences
from .planning_repository import JobRepositoryError, identity

SECTION_DAYS = 3
RUN_ALLOWANCE = 12
MAX_CHECKPOINT_BYTES = 131072
PLAN_STORAGE_BYTES = 16 * 1024 * 1024
SECTION_ROW_RESERVATION_BYTES = 16384
PLAN_ROW_RESERVATION_BYTES = 49152
GLOBAL_STORAGE_BYTES = 64 * 1024 * 1024
MAX_LIVE_PLANS_PER_OWNER = 1
MAX_LIVE_PLANS_GLOBAL = 50


def _bounded_json(value, maximum=MAX_CHECKPOINT_BYTES):
    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
        if len(encoded) > maximum: raise ValueError()
        return encoded
    except (ValueError, TypeError, OverflowError):
        raise JobRepositoryError('SECTION_RESOURCE_LIMIT', 413) from None


def _cents(value):
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite() or amount < 0 or cents != cents.to_integral_value() or cents > 9007199254740991:
            raise ValueError()
        return int(cents)
    except Exception:
        raise JobRepositoryError('SECTION_MONEY_INVALID', 400) from None


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise JobRepositoryError('SECTION_RESOURCE_ALLOWANCE_INVALID', 400)
    return value


def validate_checkpoint(checkpoint, section):
    """Defense-in-depth after domain validation; never repair/truncate output."""
    from .itineraries import ItineraryResponse, is_adaptive_travel_day
    try:
        if type(checkpoint) is not dict or set(checkpoint) != {'itinerary','startLocation','endLocation','spentCents','provenance','journeyStrategy'}:
            raise ValueError()
        _bounded_json(checkpoint)
        strategy = checkpoint['journeyStrategy']
        if type(strategy) is not dict or set(strategy)!={'summary','stays'} or type(strategy['summary']) is not str or not 1<=len(strategy['summary'])<=1500:
            raise ValueError()
        _bounded_json(strategy,16384)
        if type(strategy['stays']) is not list or not 1<=len(strategy['stays'])<=12: raise ValueError()
        prior_end = None
        for stay in strategy['stays']:
            if type(stay) is not dict or set(stay)!={'startDate','endDate','location'}: raise ValueError()
            stay_start,stay_end=date.fromisoformat(stay['startDate']),date.fromisoformat(stay['endDate'])
            if stay_start>stay_end or (prior_end is not None and (stay_start-prior_end).days!=1): raise ValueError()
            if type(stay['location']) is not str or not 1<=len(stay['location'].strip())<=200 or stay['location']!=stay['location'].strip(): raise ValueError()
            prior_end=stay_end
        response = ItineraryResponse.model_validate(checkpoint['itinerary'])
        eligible={strategy['stays'][0]['startDate'],strategy['stays'][-1]['endDate']}
        lo,hi={'relaxed':(1,2),'balanced':(2,3),'fast':(3,4)}[response.travelPace]
        for day in response.days:
            minimum=0 if is_adaptive_travel_day(day.date,day.activities,eligible) else lo
            if not minimum<=day.mainActivityCount<=hi or sum(a.kind=='main' for a in day.activities)!=day.mainActivityCount: raise ValueError()
        if response.provider!='openai' or response.model!='gpt-6-luna' or response.vibe is not None or response.refinementSummary is not None: raise ValueError()
        start, end = date.fromisoformat(section['start_date']), date.fromisoformat(section['end_date'])
        dates = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
        if response.status != 'planned' or [day.date for day in response.days] != dates:
            raise ValueError()
        for location in (checkpoint['startLocation'], checkpoint['endLocation']):
            if type(location) is not str or not 1 <= len(location.strip()) <= 200 or location != location.strip(): raise ValueError()
        if checkpoint['startLocation'] != section['input_boundary']['location']:
            raise ValueError()
        if section.get('final_section') and checkpoint['endLocation'] != section['departure_city']:
            raise ValueError()
        spent = sum(_cents(cost) for day in response.days for cost in day.costs.model_dump().values())
        if type(checkpoint['spentCents']) is not int or checkpoint['spentCents'] != spent or spent > section['budget_limit_cents']:
            raise ValueError()
        if type(checkpoint['provenance']) is not dict or checkpoint['provenance'].get('provider') != 'openai' or checkpoint['provenance'].get('model') != 'gpt-6-luna' or set(checkpoint['provenance']) != {'provider','model','validationVersion'} or checkpoint['provenance'].get('validationVersion') != 'adaptive-section-v1':
            raise ValueError()
        _bounded_json(checkpoint['provenance'], 16384)
        return checkpoint
    except Exception:
        raise JobRepositoryError('SECTION_CHECKPOINT_INVALID', 400) from None


def proposed_constraint_retryable(section):
    """A recorded model proposal, not a verified impossibility or unknown create."""
    try:
        from .adaptive_planning import RECOMMENDATION_FIELDS
        from .models import CONTROL
        d=section.get('failure_details')
        if section.get('status')!='failed' or section.get('error_code')!='SECTION_CONSTRAINT_CONFLICT': return False
        if type(d) is not dict or set(d)!={'applicability','explanation','recommendations'} or d['applicability']!='proposed': return False
        if type(d['explanation']) is not str or not d['explanation'].strip() or not 1<=len(d['explanation'])<=500 or CONTROL.search(d['explanation']): return False
        if type(d['recommendations']) is not list or not 1<=len(d['recommendations'])<=3: return False
        for item in d['recommendations']:
            if type(item) is not dict or set(item)!={'field','reason','suggestion'} or any(type(v) is not str or not v.strip() or not 1<=len(v)<=500 or CONTROL.search(v) for v in item.values()): return False
            if item['field'] not in RECOMMENDATION_FIELDS: return False
        _bounded_json(d,8192)
        return True
    except Exception: return False


class SectionCheckpointRepository:
    def __init__(self, gateway, *, enabled=False):
        if enabled is not True: raise JobRepositoryError('SECTIONS_DISABLED')
        if getattr(gateway, 'elevated', False) is not True: raise JobRepositoryError('JOB_WORKER_CONTEXT_REQUIRED', 403)
        self.gateway = gateway

    async def _call(self, operation, owner, payload, *, many=False):
        owner = identity(owner)
        try:
            rows = await self.gateway.request('POST', 'rpc/adaptive_'+operation, payload={'owner':owner, **payload})
            if type(rows) is not list or len(rows) > (3 if many else 1) or any(type(r) is not dict or r.get('user_id') != owner for r in rows):
                raise ValueError()
            _bounded_json(rows,524288)
            if many: return rows
            if not rows: raise JobRepositoryError('SECTION_NOT_FOUND_OR_CONFLICT', 409)
            return rows[0]
        except JobRepositoryError: raise
        except Exception: raise JobRepositoryError('SECTION_STORAGE_UNCONFIRMED') from None

    async def create_plan(self, owner, request_id, preferences, run_allowance=RUN_ALLOWANCE):
        prefs = TripPreferences.model_validate(preferences.model_dump() if isinstance(preferences, TripPreferences) else preferences)
        payload = prefs.model_dump(mode='json')
        encoded = _bounded_json(payload, 16384)
        digest = hashlib.sha256(encoded).hexdigest()
        request_id = identity(request_id)
        arguments = {'request_id':request_id, 'preferences':payload, 'input_hash':digest,
            'budget_cents':_cents(prefs.budget), 'run_allowance':_limit(run_allowance,RUN_ALLOWANCE)}
        try:
            row = await self._call('create_plan',owner,arguments)
        except JobRepositoryError as error:
            if error.code in {'SECTION_ADMISSION_REJECTED','SECTION_REQUEST_CONFLICT','SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT'}: raise
            # Read-only reconciliation, never a second insert after uncertainty.
            row = await self.find_request(owner,request_id)
            if row is None: raise JobRepositoryError('SECTION_CREATE_UNCONFIRMED') from None
        if row.get('input_hash') != digest or row.get('request_id') != request_id:
            raise JobRepositoryError('SECTION_REQUEST_CONFLICT',409)
        return row

    async def find_current(self, owner):
        if getattr(self.gateway,'supports_owner_recovery',False) is not True:
            raise JobRepositoryError('SECTION_OWNER_RECOVERY_UNAVAILABLE',503)
        try:
            return await self._call('find_current',owner,{})
        except JobRepositoryError as error:
            if error.code=='SECTION_NOT_FOUND_OR_CONFLICT': return None
            raise

    async def find_request(self, owner, request_id):
        try:
            return await self._call('find_request',owner,{'request_id':identity(request_id)})
        except JobRepositoryError as error:
            if error.code=='SECTION_NOT_FOUND_OR_CONFLICT': return None
            raise

    async def get_plan(self, owner, plan_id):
        return await self._call('get_plan', owner, {'plan':identity(plan_id)})

    async def get_section(self, owner, section_id):
        return await self._call('get_section',owner,{'section':identity(section_id)})

    async def next_section(self, owner, plan_id, request_id, section_days=SECTION_DAYS):
        try:
            return await self._call('next_section', owner, {'plan':identity(plan_id),'request_id':identity(request_id),
                'section_days':_limit(section_days,SECTION_DAYS)})
        except JobRepositoryError as error:
            if error.code=='SECTION_NOT_FOUND_OR_CONFLICT':
                plan = await self.get_plan(owner,plan_id)
                if plan.get('status')=='paused' and plan.get('pause_reason')=='STORAGE_LIMIT':
                    raise JobRepositoryError('SECTION_RESOURCE_LIMIT',409) from None
            raise

    async def list_sections(self, owner, plan_id, after_sequence=0, limit=3):
        if type(after_sequence) is not int or after_sequence < 0: raise JobRepositoryError('SECTION_CURSOR_INVALID',400)
        return await self._call('list_sections', owner, {'plan':identity(plan_id),'after_sequence':after_sequence,
            'page_size':_limit(limit,3)}, many=True)

    async def recent_checkpoints(self, owner, plan_id):
        return await self._call('recent_checkpoints',owner,{'plan':identity(plan_id)},many=True)

    async def claim(self, owner, section_id, worker_id):
        return await self._call('claim_section', owner, {'section':identity(section_id),'worker':identity(worker_id)})

    async def claim_next(self, worker_id):
        try:
            rows = await self.gateway.request('POST','rpc/adaptive_claim_next',payload={'worker':identity(worker_id)})
            if type(rows) is not list or len(rows)>1: raise ValueError()
            if not rows: return None
            _bounded_json(rows,524288)
            if type(rows[0]) is not dict: raise ValueError()
            identity(rows[0]['user_id'])
            return rows[0]
        except JobRepositoryError: raise
        except Exception: raise JobRepositoryError('SECTION_STORAGE_UNCONFIRMED') from None

    async def verify_ready(self):
        try:
            rows = await self.gateway.request('POST','rpc/adaptive_checkpoint_health',payload={})
            if rows != [{'schema_version':1,'rpc_version':1,'cleanup_fresh':True}]: raise ValueError()
        except Exception: raise JobRepositoryError('SECTIONS_SCHEMA_NOT_READY') from None

    async def transition(self, owner, section_id, lease, version, status, *, provider_response_id=None, error_code=None, checkpoint=None, failure_details=None):
        if type(version) is not int or version < 1 or status not in {'submitting','running','succeeded','failed','submission_unknown'}:
            raise JobRepositoryError('SECTION_TRANSITION_INVALID',400)
        if checkpoint is not None:
            if status != 'succeeded': raise JobRepositoryError('SECTION_CHECKPOINT_INVALID',400)
            _bounded_json(checkpoint)
        if status=='succeeded' and checkpoint is None: raise JobRepositoryError('SECTION_CHECKPOINT_INVALID',400)
        if failure_details is not None:
            try:
                if status!='failed' or error_code!='SECTION_CONSTRAINT_CONFLICT' or set(failure_details)!={'applicability','explanation','recommendations'} or failure_details['applicability']!='proposed': raise ValueError()
                if type(failure_details['explanation']) is not str or not 1<=len(failure_details['explanation'])<=500: raise ValueError()
                recommendations=failure_details['recommendations']
                if type(recommendations) is not list or not 1<=len(recommendations)<=3: raise ValueError()
                for item in recommendations:
                    if type(item) is not dict or set(item)!={'field','reason','suggestion'} or any(type(v) is not str or not 1<=len(v)<=500 for v in item.values()): raise ValueError()
                _bounded_json(failure_details,8192)
            except Exception: raise JobRepositoryError('SECTION_FAILURE_DETAILS_INVALID',400) from None
        # Domain calls validate_checkpoint before this write; SQL independently
        # enforces dates, boundary, exact cents, budget and immutable success.
        return await self._call('transition_section', owner, {'section':identity(section_id),'lease':identity(lease),
            'expected_version':version,'next_status':status,'response_id':provider_response_id,
            'failure_code':error_code,'checkpoint':checkpoint,'failure_details':failure_details})

    async def retry_failed(self, owner, section_id, retry_id, section_days=SECTION_DAYS):
        return await self._call('retry_section', owner, {'section':identity(section_id),'request_id':identity(retry_id),
            'section_days':_limit(section_days,SECTION_DAYS)})

    async def continue_run(self, owner, plan_id, request_id, run_allowance=RUN_ALLOWANCE):
        return await self._call('continue_run', owner, {'plan':identity(plan_id),'request_id':identity(request_id),
            'run_allowance':_limit(run_allowance,RUN_ALLOWANCE)})

    async def cancel_plan(self, owner, plan_id):
        return await self._call('cancel_plan', owner, {'plan':identity(plan_id)})
