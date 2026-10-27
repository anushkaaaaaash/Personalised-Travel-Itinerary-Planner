"""On-demand accepted-frontier accounting; no model, provider or storage writes.

Amounts are whole-group estimates, not receipts or a forecast for missing days.
The suggested buffer is separate from accepted spend and never changes budgets.
Memory retains one bounded repository page and five integer accumulators only.
"""
from datetime import date
from .adaptive_planning import cents
from .models import TripPreferences
from .planning_repository import JobRepositoryError, identity
from .section_repository import validate_checkpoint, _bounded_json, PLAN_STORAGE_BYTES, SECTION_ROW_RESERVATION_BYTES

CATEGORIES=('accommodation','meals','localTransport','activities','departureTravel')
MAX_PAGES=32768
MAX_SAFE_CENTS=2**53-1


def _invalid():
    raise JobRepositoryError('SECTION_EXPENSES_INVALID',503)


def _integer(value):
    if type(value) is not int or not 0<=value<=MAX_SAFE_CENTS:_invalid()
    return value


async def accepted_expenses(repository,owner,plan_id):
    """Read all retained accepted days at the initial immutable section frontier.

    Newer checkpoints are ignored; an incomplete/reordered/expired frontier fails
    rather than returning a misleading visible-page subtotal. Storage must keep
    accepted checkpoint rows immutable (revision candidates live separately).
    """
    owner,plan_id=identity(owner),identity(plan_id)
    try:
        plan=await repository.get_plan(owner,plan_id)
        if type(plan) is not dict or plan.get('user_id')!=owner or plan.get('id')!=plan_id:_invalid()
        if plan.get('status') not in {'active','paused','completed','cancelled'}:_invalid()
        version=_integer(plan['version'])
        if version<1:_invalid()
        prefs=TripPreferences.model_validate(plan['preferences'])
        start,end=date.fromisoformat(prefs.startDate),date.fromisoformat(prefs.endDate)
        total_days=(end-start).days+1
        count=_integer(plan['completed_days']);expected_spend=_integer(plan['spent_cents'])
        budget=_integer(plan['total_budget_cents'])
        if total_days<1 or count>total_days or budget!=cents(prefs.budget) or expected_spend>budget:_invalid()
        if plan['status']=='completed' and count!=total_days:_invalid()
        totals=dict.fromkeys(CATEGORIES,0)
        cursor=covered=pages=bytes_read=0
        while covered<count:
            pages+=1
            if pages>MAX_PAGES:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
            rows=await repository.list_sections(owner,plan_id,after_sequence=cursor,limit=3)
            if type(rows) is not list or not 1<=len(rows)<=3:_invalid()
            for row in rows:
                if covered==count:break
                if type(row) is not dict or row.get('user_id')!=owner or row.get('plan_id')!=plan_id:_invalid()
                identity(row['id'])
                sequence=_integer(row['sequence'])
                if sequence<=cursor:_invalid()
                cursor=sequence
                bytes_read+=SECTION_ROW_RESERVATION_BYTES+len(_bounded_json(row,524288))
                if bytes_read>PLAN_STORAGE_BYTES:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
                if row.get('status') not in {'queued','submitting','running','succeeded','failed','submission_unknown','cancelled'}:_invalid()
                if row['status']!='succeeded':continue
                section_start,section_end=date.fromisoformat(row['start_date']),date.fromisoformat(row['end_date'])
                if not 0<=(section_end-section_start).days<3:_invalid()
                cp=validate_checkpoint(row['checkpoint'],row)
                if cp['itinerary']['currency']!=prefs.currency:_invalid()
                days=cp['itinerary']['days']
                if not 1<=len(days)<=3 or len(days)>count-covered:_invalid()
                section_spend=0
                for day in days:
                    if day['date']!=date.fromordinal(start.toordinal()+covered).isoformat():_invalid()
                    costs=day['costs']
                    if type(costs) is not dict or set(costs)!=set(CATEGORIES):_invalid()
                    for category in CATEGORIES:
                        amount=_integer(cents(costs[category]))
                        totals[category]=_integer(totals[category]+amount)
                        section_spend=_integer(section_spend+amount)
                    covered+=1
                if section_spend!=_integer(cp['spentCents']):_invalid()
            if len(rows)<3 and covered<count:_invalid()
        spent=_integer(sum(totals.values()))
        if covered!=count or spent!=expected_spend:_invalid()
        buffer=(spent+9)//10
        return {'planId':plan_id,'planVersion':version,'categories':totals,'totalSpentCents':spent,'acceptedDays':count,'totalDays':total_days,
            'isComplete':count==total_days,'currency':prefs.currency,'travelers':prefs.travelers,'scope':'whole_group',
            'totalBudgetCents':budget,'remainingBudgetCents':budget-spent,
            'suggestedBufferPercent':10,'suggestedBufferCents':buffer,
            'budgetGapCents':max(0,spent+buffer-budget),'budgetGapScope':'accepted_estimates_plus_suggested_buffer'}
    except JobRepositoryError:raise
    except Exception:
        raise JobRepositoryError('SECTION_EXPENSES_INVALID',503) from None
