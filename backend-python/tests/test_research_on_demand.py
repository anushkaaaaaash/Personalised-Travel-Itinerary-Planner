from test_itineraries import generated
from test_research_sqlite import store,uid,run,pack_for,change
from app.planning_repository import JobRepositoryError
import pytest


def start(store,payload):
    _,_,_,r,rr=store
    p=run(r.create_plan(uid(),uid(),payload));s=run(r.next_section(p['user_id'],p['id'],uid()))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'submitting'))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_test'))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    return p,s


def trigger(store,payload):
    p,s=start(store,payload);rr=store[4]
    old=run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],'hours'))
    assert old['status']=='failed' and old['error_code']=='SECTION_RESEARCH_REQUESTED'
    return p,s


def test_new_plan_no_initial_research(store,payload):
    _,_,_,r,rr=store;p=run(r.create_plan(uid(),uid(),payload))
    assert p['research_on_demand'] is True and not p.get('research_required')
    assert run(rr.claim_next(uid())) is None
    assert run(r.next_section(p['user_id'],p['id'],uid()))['status']=='queued'


def test_trigger_cas_owner_enum_and_repair(store,payload):
    p,s=start(store,payload);rr=store[4]
    for owner,version,kind in [(uid(),s['version'],'hours'),(p['user_id'],s['version']+1,'hours'),(p['user_id'],s['version'],'private notes')]:
        with pytest.raises(JobRepositoryError):run(rr.request_research(owner,s['id'],s['lease_token'],version,kind))
    run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],'hours'))
    with pytest.raises(JobRepositoryError):run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],'hours'))
    j=run(rr.claim_next(uid()));assert j['query']['researchTopic']=='hours'
    assert j['query']['venueLabels']==[] and j['max_tool_calls']==4
    assert run(rr.claim_next(uid())) is None


def test_research_success_replaces_only_trigger(store,payload):
    p,s=trigger(store,payload);_,clock,_,r,rr=store
    j=run(rr.claim_next(uid()));j=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'submitting'))
    plan=run(r.get_plan(p['user_id'],p['id']));assert plan['remaining_creates']==10 and plan['tool_calls_reserved']==4
    j=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'running',provider_response_id='resp_research'))
    j=run(rr.claim_next(uid()));j=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'succeeded',sourcepack=pack_for(j,clock)))
    replacement=run(rr.continue_researched(p['user_id'],p['id']))
    assert replacement['retry_of']==s['id'] and replacement['research_source_id']==j['id']
    assert replacement['start_date']==s['start_date'] and replacement['end_date']==s['end_date']
    assert run(rr.continue_researched(p['user_id'],p['id'])) is None
    plan=run(r.get_plan(p['user_id'],p['id']));assert plan['spent_cents']==0 and plan['completed_days']==0 and plan['remaining_creates']==10
    assert len(run(r.list_sections(p['user_id'],p['id'])))==2


def test_unknown_research_never_retried(store,payload):
    p,s=trigger(store,payload);_,clock,_,r,rr=store
    j=run(rr.claim_next(uid()));j=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'submitting'))
    clock[0]+=61
    assert run(rr.claim_next(uid())) is None
    assert run(rr.continue_researched(p['user_id'],p['id'])) is None
    assert run(r.get_plan(p['user_id'],p['id']))['pause_reason']=='RESEARCH_SUBMISSION_UNKNOWN'
    assert len(run(r.list_sections(p['user_id'],p['id'])))==1


def finish_research(store):
    _,clock,_,r,rr=store
    j=run(rr.claim_next(uid()));j=run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'submitting'))
    j=run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'running',provider_response_id='resp_'+j['id']))
    j=run(rr.claim_next(uid()));return run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'succeeded',sourcepack=pack_for(j,clock)))


def trigger_replacement(store,p,kind):
    r,rr=store[3:];s=run(rr.continue_researched(p['user_id'],p['id']))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'submitting'))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_'+s['id']))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    return run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],kind))


def test_four_then_two_no_automatic_budget_reset_and_explicit_continue(store,payload):
    p,s=trigger(store,payload);r,rr=store[3:]
    first=finish_research(store);assert first['max_tool_calls']==4
    trigger_replacement(store,p,'transport')
    second=finish_research(store);assert second['max_tool_calls']==2
    trigger_replacement(store,p,'closures')
    paused=run(r.get_plan(p['user_id'],p['id']))
    assert paused['pause_reason']=='RESEARCH_ALLOWANCE_REACHED' and paused['tool_calls_reserved']==6
    assert run(rr.claim_next(uid())) is None
    request=uid();resumed=run(r.continue_run(p['user_id'],p['id'],request))
    assert resumed['run_index']==2 and resumed['remaining_creates']==12 and resumed['tool_calls_reserved']==0
    assert run(r.continue_run(p['user_id'],p['id'],request))==resumed
    j=run(rr.claim_next(uid()));assert j['query']['researchTopic']=='closures' and j['phase']=='initial'


def test_public_trigger_transport_no_private_notes_or_model_labels(store,payload):
    p,s=start(store,payload);rr=store[4]
    run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],'transport'))
    j=run(rr.claim_next(uid()))
    assert j['query']['routeLabels']==[payload['departureCity']]
    assert set(j['query'])=={'destination','startDate','endDate','venueLabels','routeLabels','researchTopic'}


def test_legacy_only_explicit_retry_enables_on_demand_preserves_prefix(store,payload,generated):
    from datetime import date,timedelta
    from app.adaptive_planning import SectionSpec,SectionContract
    from test_adaptive_planning import section_wire
    path,clock,g,r,rr=store;g.research_enabled=False
    prefs={**payload,'budget':100000,'endDate':(date.fromisoformat(payload['startDate'])+timedelta(days=8)).isoformat()}
    p=run(r.create_plan(uid(),uid(),prefs));accepted=[]
    for index in range(3):
        section=run(r.claim_next(uid()))
        section=run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'submitting'))
        section=run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'running',provider_response_id='resp_'+str(index)))
        section=run(r.claim(p['user_id'],section['id'],uid()))
        if index==2:
            failed=run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'failed',error_code='SECTION_PROVIDER_FAILED'));break
        current=run(r.get_plan(p['user_id'],p['id']))
        spec=SectionSpec.from_manifest(prefs,next_date=section['start_date'],spent_cents=current['spent_cents'],previous_boundary=current['previous_boundary'] if index else None,journey_strategy=current['journey_strategy'])
        cp=SectionContract(spec).decode(section_wire(prefs,generated,spec))
        accepted.append(run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'succeeded',checkpoint=cp)))
    g.research_enabled=True
    before=run(r.get_plan(p['user_id'],p['id']));assert before['completed_days']==6 and not before.get('research_on_demand')
    assert run(rr.claim_next(uid())) is None
    new=run(r.retry_failed(p['user_id'],failed['id'],uid()))
    after=run(r.get_plan(p['user_id'],p['id']))
    assert new['status']=='queued' and after['research_on_demand'] is True
    assert after['remaining_creates']==before['remaining_creates']
    assert after['completed_days']==6 and after['spent_cents']==before['spent_cents'] and after['previous_boundary']==before['previous_boundary'] and after['journey_strategy']==before['journey_strategy']
    for row in accepted:assert run(r.get_section(p['user_id'],row['id']))==row
    assert run(rr.claim_next(uid())) is None


def test_invalid_original_public_query_pauses_no_repeated_completed_poll(store,payload):
    bad={**payload,'destination':'name@example.com'}
    p,s=start(store,bad);r,rr=store[3:]
    old=run(rr.request_research(p['user_id'],s['id'],s['lease_token'],s['version'],'places'))
    assert old['status']=='failed'
    plan=run(r.get_plan(p['user_id'],p['id']))
    assert plan['research_error']=='RESEARCH_QUERY_INVALID' and plan['status']=='paused'
    assert run(rr.claim_next(uid())) is None and run(r.claim_next(uid())) is None
    assert plan['remaining_creates']==11 and plan['tool_calls_reserved']==0


def test_research_last_create_explicit_continue_reuses_source_without_new_research(store,payload):
    p,s=trigger(store,payload);path,clock,g,r,rr=store
    change(path,'plans',p['id'],remaining_creates=1)
    accepted=finish_research(store)
    plan=run(r.get_plan(p['user_id'],p['id']))
    assert plan['remaining_creates']==0 and plan['pause_reason']=='RESOURCE_ALLOWANCE_REACHED'
    assert run(rr.continue_researched(p['user_id'],p['id'])) is None
    run(r.continue_run(p['user_id'],p['id'],uid()))
    assert run(rr.claim_next(uid())) is None
    plan=run(r.get_plan(p['user_id'],p['id']));section=run(r.get_section(p['user_id'],plan['active_section']))
    assert section['research_source_id']==accepted['id'] and section['status']=='queued'
    assert plan['remaining_creates']==12 and plan['tool_calls_reserved']==0
