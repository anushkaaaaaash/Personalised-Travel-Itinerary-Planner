"""Serial handoff timings use a fake clock; no provider/network benchmarks."""
import asyncio
from datetime import datetime,timezone
import json
from types import SimpleNamespace
import pytest
from app.adaptive_coordinator import AdaptiveCoordinator
from app.adaptive_research_worker import GroundedPlanningWorker,AdaptiveResearchWorker
from app.planning_repository import JobRepositoryError
from test_section_preview_store import setup,run
from test_adaptive_stream_worker import Client,event,worker
from test_adaptive_planning import section_wire
from app.adaptive_planning import SectionSpec
from test_itineraries import generated


def drive(monkeypatch,actions,*,hints=True):
    state={'seconds':0,'waits':0,'ticks':0,'creates':0,'accepted':0,'yields':0}
    class Stop:
        done=False
        def is_set(self):return self.done
        async def wait(self):
            if not self.done:state['seconds']+=5;state['waits']+=1
            assert state['waits']<20
    stop=Stop()
    class Worker:
        immediate_followup=False
        async def tick(self):
            kind,followup=actions[state['ticks']];state['ticks']+=1
            self.immediate_followup=followup and hints
            state['creates']+=kind=='create';state['accepted']+=kind=='accept'
            if state['ticks']==len(actions):stop.done=True
            if kind=='error':raise RuntimeError('safe synthetic failure')
            return {'status':kind}
    async def wait_for(coro,timeout):
        await coro
        if not stop.done:raise TimeoutError()
    original_sleep=asyncio.sleep
    async def sleep(delay):
        assert delay==0;state['yields']+=1;await original_sleep(0)
    with monkeypatch.context() as m:
        m.setattr(asyncio,'wait_for',wait_for);m.setattr(asyncio,'sleep',sleep)
        class Repository:
            async def verify_ready(self):pass
        engine=AdaptiveCoordinator(Repository(),Worker(),enabled=True,require_health=False)
        run(engine.run(stop))
    return state


def test_three_synthetic_handoffs_save_15s_without_output_or_create_changes(monkeypatch):
    actions=[('terminal',True),('accept',True),('create',False),('running',False),('research_success',True),('create',False)]
    before=drive(monkeypatch,actions,hints=False);after=drive(monkeypatch,actions)
    assert before['seconds']==25 and after['seconds']==10
    assert before['creates']==after['creates']==2 and before['accepted']==after['accepted']==1
    assert after['ticks']==before['ticks']==6 and after['yields']==3


def test_immediate_burst_bounded_and_exceptions_never_use_stale_hint(monkeypatch):
    burst=drive(monkeypatch,[('accept',True)]*6)
    assert burst['waits']==1 and burst['seconds']==5
    failed=drive(monkeypatch,[('error',True),('running',False)])
    assert failed['waits']==1 and failed['yields']==0


def test_composite_keeps_round_robin_and_clears_hint_on_empty_or_exception():
    calls=[]
    class Child:
        def __init__(self,name):self.name=name;self.immediate_followup=True;self.empty=False;self.error=False
        async def tick(self):
            calls.append(self.name)
            if self.error:raise RuntimeError()
            return None if self.empty else {'status':'succeeded'}
    sections,research,revisions=(Child(n) for n in ('sections','research','revision'))
    sections.client=object();research.context_for_section=None;research.request_for_section=None
    combined=GroundedPlanningWorker(sections,research,revisions)
    for _ in range(3):run(combined.tick());assert combined.immediate_followup
    assert calls==['research','sections','revision']
    for child in (sections,research,revisions):child.empty=True
    assert run(combined.tick()) is None and combined.immediate_followup is False
    sections.error=True
    with pytest.raises(RuntimeError):run(combined.tick())
    assert combined.immediate_followup is False


def test_stream_terminal_only_hints_after_durable_cas_then_requires_get_validation(setup,payload,generated):
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    client=Client([event(0),event(1,kind='terminal')]);w=worker(r,g,client,clock)
    first=run(w.tick())
    assert first['status']=='running' and first['checkpoint'] is None and w.immediate_followup
    assert client.creates==0 and client.gets==1
    client.status='completed';client.output=json.dumps(section_wire(payload,generated,SectionSpec.from_manifest(payload)))
    accepted=run(w.tick())
    assert accepted['status']=='succeeded' and accepted['checkpoint'] and w.immediate_followup
    assert client.gets==2 and client.creates==0
    assert run(r.get_plan(p['user_id'],p['id']))['completed_days']==3


@pytest.mark.parametrize('kind',['in_progress','interrupted','invalid','lost_cas'])
def test_nonterminal_errors_and_stale_cas_never_hint(setup,kind):
    from app.openai_output_stream import OutputStreamError
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    events=[]
    if kind=='interrupted':events=[event(0),OutputStreamError('STREAM_INTERRUPTED',response_id='resp_private')]
    if kind=='invalid':events=[event(0),OutputStreamError('STREAM_INVALID_RESPONSE',response_id='resp_private')]
    if kind=='lost_cas':events=[event(0),event(1,kind='terminal')]
    client=Client(events);w=worker(r,g,client,clock);w.immediate_followup=True
    if kind=='lost_cas':
        async def lost(*args,**kwargs):raise JobRepositoryError('SECTION_PREVIEW_CONFLICT',409)
        w.preview_store.append=lost
        with pytest.raises(JobRepositoryError):run(w.tick())
    else:run(w.tick())
    assert w.immediate_followup is False and client.creates==0 and client.cancelled==0


from test_research_worker_sqlite import setup as research_setup,FakeResearch,triggered


def test_research_success_hints_only_when_successor_is_durably_queued(research_setup,payload):
    path,clock,g,plans,research=research_setup
    p=triggered(plans,research,payload);client=FakeResearch(lambda:clock[0])
    w=AdaptiveResearchWorker(research,plans,client,enabled=True,clock=lambda:clock[0])
    assert run(w.tick())['status']=='running' and not w.immediate_followup
    assert run(w.tick())['status']=='succeeded' and w.immediate_followup
    current=run(plans.get_plan(p['user_id'],p['id']))
    successor=run(plans.get_section(p['user_id'],current['active_section']))
    assert successor['status']=='queued' and current['remaining_creates']==10 and current['tool_calls_reserved']==4
    assert len(client.creates)==1 and len(client.retrieves)==1
    assert run(w.tick()) is None and not w.immediate_followup


def test_research_success_with_capacity_pause_does_not_fast_follow(research_setup,payload):
    path,clock,g,plans,research=research_setup
    triggered(plans,research,payload);client=FakeResearch(lambda:clock[0])
    w=AdaptiveResearchWorker(research,plans,client,enabled=True,clock=lambda:clock[0])
    run(w.tick())
    async def no_capacity(*args):return None
    research.continue_researched=no_capacity
    assert run(w.tick())['status']=='succeeded' and not w.immediate_followup



def test_worker_diagnostics_are_closed_safe_and_best_effort(caplog,monkeypatch):
    import logging
    from app.adaptive_coordinator import _worker_diagnostic
    class Hostile(JobRepositoryError):
        def __str__(self):raise AssertionError('SECRET_REQUEST_TEXT')
    with caplog.at_level(logging.WARNING):
        _worker_diagnostic(Hostile('SECRET_REQUEST_TEXT'))
        _worker_diagnostic(JobRepositoryError('SECTION_PREVIEW_CONFLICT',409))
        _worker_diagnostic(TimeoutError('SECRET_REQUEST_TEXT'))
        _worker_diagnostic(ValueError('SECRET_REQUEST_TEXT'))
    messages=[record.getMessage() for record in caplog.records]
    assert messages==[
        'Adaptive planning worker unavailable; family=repository code=SECTION_WORKER_UNCONFIRMED',
        'Adaptive planning worker unavailable; family=repository code=SECTION_PREVIEW_CONFLICT',
        'Adaptive planning worker unavailable; family=timeout code=SECTION_WORKER_UNCONFIRMED',
        'Adaptive planning worker unavailable; family=unexpected code=SECTION_WORKER_UNCONFIRMED']
    assert 'SECRET' not in caplog.text and 'Hostile' not in caplog.text
    def broken(*args,**kwargs):raise RuntimeError('logging unavailable')
    monkeypatch.setattr(logging.getLogger('app.adaptive_coordinator'),'warning',broken)
    _worker_diagnostic(Hostile('SECRET_REQUEST_TEXT'))
