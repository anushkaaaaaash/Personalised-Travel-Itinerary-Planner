"""Fake-provider phase evidence; these are not production latency benchmarks."""
import json
import logging
import pytest
from app.adaptive_planning import SectionContract
from app.planning_repository import JobRepositoryError
from test_section_preview_store import setup, run
from test_adaptive_stream_worker import Client, worker
from test_adaptive_fast_follow import drive


@pytest.mark.parametrize('outcome', ['confirmed', 'unknown', 'paused', 'wrong_id'])
def test_research_handoff_hint_requires_confirmed_transition(setup, monkeypatch, outcome):
    _,clock,g,r,_,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    client=Client([],status='completed',output='synthetic')
    w=worker(r,g,client,clock)
    monkeypatch.setattr(SectionContract,'decode',lambda *args:{'status':'needs_research','kind':'hours'})
    calls=[]
    async def request(section, kind):
        calls.append((section['id'],kind))
        if outcome=='unknown':raise JobRepositoryError('RESEARCH_STORAGE_UNCONFIRMED',503)
        return {'id':section['id'] if outcome!='wrong_id' else 'other',
                'status':'failed','error_code':'SECTION_RESEARCH_REQUESTED' if outcome!='paused' else 'RESEARCH_ALLOWANCE_REACHED'}
    w.research_request=request
    if outcome=='unknown':
        assert run(w.tick())['error_code']=='RESEARCH_STORAGE_UNCONFIRMED'
    else:run(w.tick())
    assert w.immediate_followup is (outcome=='confirmed')
    assert calls==[(s['id'],'hours')]
    assert client.creates==0 and client.gets==1 and client.cancelled==0
    assert run(r.get_plan(p['user_id'],p['id']))['completed_days']==0


def test_confirmed_research_handoff_removes_only_scheduler_delay(monkeypatch):
    actions=[('research_request',True),('create',False),('running',False)]
    old=drive(monkeypatch,actions,hints=False);new=drive(monkeypatch,actions)
    assert old['seconds']-new['seconds']==5
    assert old['creates']==new['creates']==1
    assert old['ticks']==new['ticks']==3


def test_research_phase_fields_are_closed(caplog):
    from app.adaptive_worker import _timing
    with caplog.at_level(logging.INFO,logger='uvicorn.error'):
        for phase in ('research_create_ack','research_provider_wait','research_validation'):
            _timing(phase,1,status='completed')
    rows=[json.loads(r.message.split(': ',1)[1]) for r in caplog.records]
    assert len(rows)==3
    assert all(set(row)=={'phase','elapsed_ms','status'} and row['elapsed_ms']==1000 for row in rows)


def test_nine_day_single_batch_is_not_supported_by_existing_contract(payload):
    from app.adaptive_planning import SectionSpec,AdaptiveError
    nine={**payload,'startDate':'2026-10-24','endDate':'2026-11-01'}
    with pytest.raises(AdaptiveError) as failure:
        SectionSpec.from_manifest(nine,section_days=9)
    assert failure.value.code=='SECTION_WORK_LIMIT'
    bounded=SectionSpec.from_manifest(nine)
    assert bounded.start.isoformat()=='2026-10-24' and bounded.end.isoformat()=='2026-10-26'
    assert bounded.original.endDate=='2026-11-01'  # bounded work, never truncated trip


def test_repository_rejects_larger_batch_before_gateway_io():
    from app.section_repository import SectionCheckpointRepository
    from uuid import uuid4
    class NoCalls:
        elevated=True
        async def section_request(self,*args,**kwargs):raise AssertionError('must reject before I/O')
    repo=SectionCheckpointRepository(NoCalls(),enabled=True)
    with pytest.raises(JobRepositoryError):
        run(repo.next_section(str(uuid4()),str(uuid4()),str(uuid4()),section_days=9))
