import asyncio
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.research_sqlite import ResearchSQLiteGateway,upgrade_research_schema
from app.section_repository import SectionCheckpointRepository
from app.research_repository import ResearchCheckpointRepository
from app.adaptive_research_worker import AdaptiveResearchWorker,GroundedPlanningWorker
from app.adaptive_worker import AdaptivePlanningWorker
from app.grounded_coordinator import GroundedCoordinator
from app.openai_background import BackgroundError
from test_research_worker_sqlite import FakeResearch
from test_adaptive_integration import Auth,FakeProvider,OWNER


def run(c):return asyncio.run(c)

def setup(tmp_path,payload,monkeypatch,*,failure=None):
    monkeypatch.setenv('ADAPTIVE_PLANNING_PREVIEW','true');monkeypatch.setenv('APP_MODE','local')
    path=tmp_path/'db';AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,research_enabled=True);run(g.purge_expired())
    plans=SectionCheckpointRepository(g,enabled=True);research=ResearchCheckpointRepository(g,enabled=True)
    provider=FakeResearch(lambda:datetime.now(timezone.utc),failure=failure)
    rw=AdaptiveResearchWorker(research,plans,provider,enabled=True)
    section_provider=FakeProvider(plans,payload)
    sw=AdaptivePlanningWorker(plans,section_provider,enabled=True)
    worker=GroundedPlanningWorker(sw,rw)
    engine=GroundedCoordinator(plans,worker,research_repository=research,enabled=True,require_health=False)
    client=TestClient(create_app(auth_service=Auth(),adaptive_engine=engine))
    return g,engine,client,provider,section_provider


def trigger(e, plan_id, kind='hours'):
    p=run(e.repository.get_plan(OWNER,plan_id))
    sec=run(e.repository.claim(OWNER,p['active_section'],str(uuid4())))
    sec=run(e.repository.transition(OWNER,sec['id'],sec['lease_token'],sec['version'],'submitting'))
    sec=run(e.repository.transition(OWNER,sec['id'],sec['lease_token'],sec['version'],'running',provider_response_id='resp_planner_trigger'))
    sec=run(e.repository.claim(OWNER,sec['id'],str(uuid4())))
    return run(e.worker.research.request_for_section(sec,kind))


def test_owner_http_research_receipts_and_stop_are_safe(tmp_path,payload,monkeypatch):
    g,e,c,p,sp=setup(tmp_path,payload,monkeypatch);h={'Authorization':'Bearer owner'}
    body=c.post('/api/adaptive-plans',headers=h,json={'requestId':str(uuid4()),'preferences':payload}).json()
    assert body['research'] is None and body['draft'] is None
    pid=body['plan']['id'];assert sp.calls==0 and p.creates==[]
    trigger(e,pid)
    assert c.get('/api/adaptive-plans/'+pid,headers=h).json()['plan']['activeSection']['errorCode']=='SECTION_RESEARCH_REQUESTED'
    run(e.worker.research.tick());run(e.worker.research.tick())
    result=c.get('/api/adaptive-plans/'+pid,headers=h)
    assert result.status_code==200
    d=result.json();assert d['research']['status']=='succeeded'
    assert d['research']['toolCallsReserved']==4 and d['plan']['remainingCreates']==10
    assert d['research']['applicability']=='unknown' and d['research']['receivedAt']
    assert d['research']['sources'][0]['url']=='https://example.org/official'
    assert 'query' not in d['research'] and 'stream_output_text' not in result.text
    assert c.get('/api/adaptive-plans/'+pid,headers={'Authorization':'Bearer other'}).status_code==404
    assert c.post('/api/adaptive-plans/'+pid+'/cancel',headers=h,json={}).status_code==200
    run(e.close())  # per-request HTTP clients have no close method


def test_only_explicit_research_retry_consumes_second_reservation(tmp_path,payload,monkeypatch):
    g,e,c,p,sp=setup(tmp_path,payload,monkeypatch,failure=BackgroundError('BACKGROUND_HTTP_FAILED',ambiguous_create=False))
    h={'Authorization':'Bearer owner'}
    d=c.post('/api/adaptive-plans',headers=h,json={'requestId':str(uuid4()),'preferences':payload}).json();pid=d['plan']['id']
    trigger(e,pid)
    run(e.worker.research.tick())
    paused=c.get('/api/adaptive-plans/'+pid,headers=h).json()
    assert paused['plan']['pauseReason']=='RESEARCH_FAILED'
    assert len(p.creates)==1
    request={'requestId':str(uuid4())}
    r=c.post('/api/adaptive-plans/'+pid+'/research/retry',headers=h,json=request)
    assert r.status_code==200 and len(p.creates)==1
    run(e.worker.research.tick());assert len(p.creates)==2
    paused=c.get('/api/adaptive-plans/'+pid,headers=h).json()
    assert paused['research']['toolCallsReserved']==6 and paused['plan']['remainingCreates']==9
    assert paused['plan']['pauseReason']=='RESEARCH_ALLOWANCE_REACHED'
    run(e.close())


def test_unknown_research_never_retries(tmp_path,payload,monkeypatch):
    g,e,c,p,sp=setup(tmp_path,payload,monkeypatch,failure=BackgroundError('BACKGROUND_TRANSPORT_FAILED',ambiguous_create=True))
    h={'Authorization':'Bearer owner'}
    d=c.post('/api/adaptive-plans',headers=h,json={'requestId':str(uuid4()),'preferences':payload}).json();pid=d['plan']['id']
    trigger(e,pid)
    run(e.worker.research.tick())
    r=c.post('/api/adaptive-plans/'+pid+'/research/retry',headers=h,json={'requestId':str(uuid4())})
    assert r.status_code==409 and len(p.creates)==1
    run(e.close())


def test_invalid_public_query_is_visible_without_fake_job_or_paid_search(tmp_path,payload,monkeypatch):
    payload={**payload,'destination':'private@example.com'}
    g,e,c,p,sp=setup(tmp_path,payload,monkeypatch);h={'Authorization':'Bearer owner'}
    d=c.post('/api/adaptive-plans',headers=h,json={'requestId':str(uuid4()),'preferences':payload}).json()
    trigger(e,d['plan']['id'])
    result=c.get('/api/adaptive-plans/'+d['plan']['id'],headers=h).json()
    assert result['research']['status']=='failed' and result['research']['errorCode']=='RESEARCH_QUERY_INVALID'
    assert result['research']['sources']==[] and result['research']['toolCallsReserved']==0
    assert p.creates==[]
    assert c.post('/api/adaptive-plans/'+d['plan']['id']+'/research/retry',headers=h,json={'requestId':str(uuid4())}).status_code==409
    run(e.close())
