from datetime import date, datetime, timedelta, timezone
import pytest
from app.travel_evidence import EvidenceScope, TrustedEvidence
from app.travel_feasibility import TravelConstraint, assess_feasibility, build_feasibility_gate, FeasibilityConflict
NOW=datetime(2026,10,27,5,tzinfo=timezone.utc)
def plan(start='10:00',duration=60):
    return {'days':[{'date':'2026-10-27','activities':[{'id':'venue','startTime':start,'durationMinutes':duration}]}]}
def constraint(rule='closure',kind='closure',outcome='blocked',**kwargs):
    stale=kwargs.pop('stale',False)
    e=TrustedEvidence(providerId='official',scope=EvidenceScope(destinationId='paris-fr',localDate=date(2026,10,27),
        timeZone='Europe/Paris',kind=kind,subjectId='venue'),sourceURL='https://www.louvre.fr/en/visit/hours-admission',
        checkedAt=NOW-timedelta(hours=2),expiresAt=NOW if stale else NOW+timedelta(hours=1),
        validFrom=date(2026,10,27),validUntil=date(2026,10,27),outcome=outcome,
        summary='Official constraint.',fallback='Choose another time or venue.')
    return TravelConstraint(evidence=e,rule=rule,**kwargs)
def check(p=None,cs=(),**kwargs):
    return assess_feasibility(p or plan(),constraints=cs,accepted_providers=frozenset({'official'}),now=NOW,
        destination_id='paris-fr',time_zone='Europe/Paris',**kwargs)
def test_closed_rejected():
    assert check(cs=(constraint(),)).blockers[0].code=='VENUE_CLOSED'
def test_date_bound_does_not_leak():
    p=plan();p['days'][0]['date']='2026-10-28'
    assert check(p,(constraint(),)).feasible
def test_stale_does_not_block_and_is_marked():
    r=check(cs=(constraint(stale=True),));assert r.feasible and any(c.status=='stale' for c in r.checks)
def test_unknown_not_clear():
    r=check(); assert r.feasible and all(c.status=='unverified' for c in r.checks)
@pytest.mark.parametrize('start,duration,code',[('08:00',60,'VISIT_OUTSIDE_HOURS'),('17:30',60,'VISIT_OUTSIDE_HOURS'),('17:15',15,'LAST_ENTRY_MISSED')])
def test_hours_and_last_entry(start,duration,code):
    c=constraint('visit_window','opening_hours','clear',opensAt='09:00',closesAt='18:00',lastEntry='17:00')
    assert check(plan(start,duration),(c,)).blockers[0].code==code
def test_full_visit_fits():
    c=constraint('visit_window','opening_hours','clear',opensAt='09:00',closesAt='18:00',lastEntry='17:00')
    assert check(plan('17:00',60),(c,)).feasible
def test_gap_too_short():
    p=plan('10:15');p['days'][0]['activities'].insert(0,{'id':'previous','startTime':'09:00','durationMinutes':60})
    c=constraint('minimum_gap','route','clear',minimumGapMinutes=30)
    assert check(p,(c,)).blockers[0].code=='TRANSFER_BUFFER_TOO_SHORT'
def test_fixed_booking_conflict():
    c=constraint('fixed_booking','booking','clear',fixedStart='11:00')
    assert check(cs=(c,)).blockers[0].code=='FIXED_BOOKING_CONFLICT'
def test_booking_required_does_not_mean_booked_or_sold_out():
    c=constraint('booking_required','booking','caution')
    r=check(cs=(c,));assert r.feasible and any(x.severity=='caution' for x in r.checks)
def test_worker_adapter_raises_only_for_conflict():
    gate=build_feasibility_gate(constraints=(constraint(),),accepted_providers=frozenset({'official'}),now=lambda:NOW,
        destination_id='paris-fr',time_zone='Europe/Paris')
    with pytest.raises(FeasibilityConflict):gate(plan(),{})
def test_other_destination_not_applied():
    r=assess_feasibility(plan(),constraints=(constraint(),),accepted_providers=frozenset({'official'}),now=NOW,
        destination_id='paris-us',time_zone='Europe/Paris')
    assert r.feasible and all(c.status=='unverified' for c in r.checks)
