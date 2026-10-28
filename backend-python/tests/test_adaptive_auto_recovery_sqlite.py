"""Real SQLite automatic recovery: bounded lineage, no provider/network calls."""
import sqlite3
import pytest
from copy import deepcopy
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.planning_repository import JobRepositoryError
from app.adaptive_planning import SectionSpec,SectionContract
from test_adaptive_sqlite import store,uid,run,make,mutate
from test_adaptive_planning import section_wire
from test_itineraries import generated

FAIL='SECTION_AUTO_RETRYABLE_FAILURE';INCOMPLETE='SECTION_AUTO_RETRYABLE_INCOMPLETE'

def running(r,owner,plan,section=None):
    section=section or run(r.next_section(owner,plan['id'],uid()))
    s=run(r.claim(owner,section['id'],uid()))
    s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'submitting'))
    s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_verified'))
    return run(r.claim(owner,s['id'],uid()))

def fail(r,owner,s,code=FAIL):
    return run(r.transition(owner,s['id'],s['lease_token'],s['version'],'failed',error_code=code))

@pytest.mark.parametrize('code,days',[(FAIL,3),(INCOMPLETE,1)])
def test_atomic_successor_bounded_delay_restart_no_duplicate(store,payload,code,days):
    path,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    before=run(r.get_plan(owner,p['id']));old=fail(r,owner,s,code)
    after=run(r.get_plan(owner,p['id']));successor=run(r.get_section(owner,after['active_section']))
    assert old['status']=='failed' and old['auto_retry_count']==1
    assert successor['requested_days']==days and successor['start_date']==s['start_date']
    assert successor['retry_of']==s['id'] and successor['auto_retry_root']==s['id'] and successor['auto_retry_count']==1
    assert after['remaining_creates']==before['remaining_creates'] and after['spent_cents']==before['spent_cents']
    assert after['status']=='active' and successor['status']=='queued'
    with pytest.raises(JobRepositoryError):fail(r,owner,s,code)
    assert run(r.claim_next(uid())) is None
    with pytest.raises(JobRepositoryError):run(r.claim(owner,successor['id'],uid()))
    g2,r2=make(path,clock=lambda:clock[0]);assert g2.supports_auto_recovery is True
    assert run(r2.get_plan(owner,p['id']))['active_section']==successor['id']
    clock[0]+=15
    claimed=run(r2.claim_next(uid()));assert claimed['id']==successor['id']
    with sqlite3.connect(path) as c:assert c.execute('select count(*) from sections').fetchone()[0]==2


def test_auto_limit_survives_manual_retry_descendant(store,payload):
    _,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p);fail(r,owner,s)
    p=run(r.get_plan(owner,p['id']));replacement=run(r.get_section(owner,p['active_section']));clock[0]+=15
    second=running(r,owner,p,replacement);fail(r,owner,second)
    p=run(r.get_plan(owner,p['id']));assert p['status']=='paused' and p['active_section']==second['id']
    manual=run(r.retry_failed(owner,second['id'],uid(),section_days=1))
    assert manual['auto_retry_count']==1 and manual['auto_retry_root']==s['id']
    third=running(r,owner,p,manual);fail(r,owner,third,INCOMPLETE)
    p=run(r.get_plan(owner,p['id']));assert p['status']=='paused' and p['active_section']==third['id']

@pytest.mark.parametrize('code',['SECTION_PROVIDER_FAILED','SECTION_DEADLINE_EXCEEDED','SUBMISSION_UNKNOWN','SECTION_CONSTRAINT_CONFLICT','SECTION_INVALID_RESULT','SECTION_RESEARCH_REQUESTED','SECTION_REFUSED'])
def test_generic_failures_never_auto_schedule(store,payload,code):
    _,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p);fail(r,owner,s,code)
    p=run(r.get_plan(owner,p['id']));assert p['status']=='paused' and p['active_section']==s['id']


def test_no_allowance_no_auto_reset(store,payload):
    _,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload,run_allowance=1));s=running(r,owner,p);fail(r,owner,s)
    p=run(r.get_plan(owner,p['id']));assert p['remaining_creates']==0 and p['status']=='paused' and p['active_section']==s['id']

@pytest.mark.parametrize('reason',['cancel','expired','lease','owner'])
def test_stale_cancel_expiry_owner_cannot_schedule(store,payload,reason):
    _,clock,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    if reason=='cancel':run(r.cancel_plan(owner,p['id']))
    elif reason=='expired':clock[0]+=86401
    elif reason=='lease':clock[0]+=61
    else:owner=uid()
    with pytest.raises(JobRepositoryError):fail(r,owner,s)


def test_new_codes_require_existing_running_response(store,payload):
    _,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=run(r.next_section(owner,p['id'],uid()));s=run(r.claim(owner,s['id'],uid()))
    with pytest.raises(JobRepositoryError):fail(r,owner,s)


def test_storage_pause_retains_failure_and_checkpoint(store,payload):
    path,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    mutate(path,'plans',p['id'],storage_limit_bytes=1)
    old=fail(r,owner,s);p=run(r.get_plan(owner,p['id']))
    assert old['status']=='failed' and p['status']=='paused' and p['pause_reason']=='STORAGE_LIMIT' and p['active_section']==s['id']


def test_accepted_days_immutable_and_failed_terminal_slot_released(store,payload,generated):
    _,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    spec=SectionSpec.from_manifest(payload);cp=SectionContract(spec).decode(section_wire(payload,generated,spec))
    accepted=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=cp))
    p=run(r.get_plan(owner,p['id']));s2=running(r,owner,p);fail(r,owner,s2)
    now=run(r.get_plan(owner,p['id']));assert now['completed_days']==3 and now['spent_cents']==cp['spentCents']
    assert run(r.get_section(owner,accepted['id']))==accepted
    with g._connect() as c:assert g._paid_work_count(c,clock[0])==0
    clock[0]+=15
    assert run(r.claim_next(uid()))['id']==now['active_section']


def test_allocation_exception_rolls_back_failure_and_successor(store,payload,monkeypatch):
    path,_,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    before=run(r.get_plan(owner,p['id']));original=g._next
    def interrupted(*args):
        original(*args)
        raise RuntimeError('synthetic interrupted transaction')
    monkeypatch.setattr(g,'_next',interrupted)
    with pytest.raises(JobRepositoryError):fail(r,owner,s)
    assert run(r.get_section(owner,s['id']))==s and run(r.get_plan(owner,p['id']))==before
    with sqlite3.connect(path) as c:assert c.execute('select count(*) from sections').fetchone()[0]==1


def test_competing_transition_and_cancelled_successor_never_duplicate(store,payload):
    from concurrent.futures import ThreadPoolExecutor
    path,clock,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    def attempt(_):
        _,other=make(path,clock=lambda:clock[0])
        try:fail(other,owner,s);return True
        except JobRepositoryError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,range(2)))==[False,True]
    run(r.cancel_plan(owner,p['id']));clock[0]+=15
    assert run(r.claim_next(uid())) is None
    with sqlite3.connect(path) as c:assert c.execute('select count(*) from sections').fetchone()[0]==2


def test_recovery_waits_for_existing_global_paid_admission(store,payload):
    _,clock,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    second_owner=uid();second_plan=run(r.create_plan(second_owner,uid(),payload));second=running(r,second_owner,second_plan)
    fail(r,owner,s);p=run(r.get_plan(owner,p['id']))
    third_owner=uid();third_plan=run(r.create_plan(third_owner,uid(),payload));running(r,third_owner,third_plan)
    clock[0]+=15
    with pytest.raises(JobRepositoryError):run(r.claim(owner,p['active_section'],uid()))
    fail(r,second_owner,second,'SECTION_PROVIDER_FAILED')
    # An unclassified failed response still holds its existing quarantine slot.
    with pytest.raises(JobRepositoryError):run(r.claim(owner,p['active_section'],uid()))
    clock[0]+=601
    assert run(r.claim(owner,p['active_section'],uid()))['id']==p['active_section']


def test_manual_request_uuid_collision_cannot_clear_failed_lineage(store,payload):
    from uuid import UUID,uuid5
    path,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));first=running(r,owner,p)
    fail(r,owner,first,'SECTION_PROVIDER_FAILED')
    collision=str(uuid5(UUID(first['id']),'adaptive-auto-retry-v1'))
    manual=run(r.retry_failed(owner,first['id'],collision))
    current=running(r,owner,p,manual);fail(r,owner,current)
    p=run(r.get_plan(owner,p['id']))
    assert p['status']=='paused' and p['active_section']==current['id']
    assert run(r.get_section(owner,current['id']))['retry_of']==first['id']
    with sqlite3.connect(path) as c:assert c.execute('select count(*) from sections').fetchone()[0]==2

@pytest.mark.parametrize('stop',['failed','cancel'])
def test_late_unconfirmed_stop_keeps_paid_slot_for_ten_more_minutes(store,payload,stop):
    _,clock,g,r=store;owners=[uid(),uid(),uid()]
    plans=[run(r.create_plan(owner,uid(),payload)) for owner in owners]
    pending=[running(r,owners[i],plans[i]) for i in range(2)]
    original=pending[0]['submitted_at'];clock[0]+=1800
    if stop=='failed':
        pending[0]=run(r.claim(owners[0],pending[0]['id'],uid()))
        fail(r,owners[0],pending[0],'SECTION_DEADLINE_EXCEEDED')
    else:run(r.cancel_plan(owners[0],plans[0]['id']))
    stopped=run(r.get_section(owners[0],pending[0]['id']))
    assert stopped['submitted_at']==original and stopped['paid_hold_until']
    with g._connect() as c:assert g._paid_work_count(c,clock[0])==2
    next_section=run(r.next_section(owners[2],plans[2]['id'],uid()))
    with pytest.raises(JobRepositoryError):run(r.claim(owners[2],next_section['id'],uid()))
    clock[0]+=300;run(r.cancel_plan(owners[0],plans[0]['id']))
    assert run(r.get_section(owners[0],pending[0]['id']))['paid_hold_until']==stopped['paid_hold_until']
    clock[0]+=301
    assert run(r.claim(owners[2],next_section['id'],uid()))['id']==next_section['id']


def test_late_proven_terminal_does_not_get_uncertain_hold(store,payload):
    _,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    clock[0]+=1800;s=run(r.claim(owner,s['id'],uid()));old=fail(r,owner,s)
    assert not old.get('paid_hold_until')
    with g._connect() as c:assert g._paid_work_count(c,clock[0])==0


def test_early_stop_does_not_extend_original_reservation(store,payload):
    _,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=running(r,owner,p)
    clock[0]+=30;run(r.cancel_plan(owner,p['id']))
    assert not run(r.get_section(owner,s['id'])).get('paid_hold_until')
    clock[0]+=571
    with g._connect() as c:assert g._paid_work_count(c,clock[0])==0
