import asyncio
from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.adaptive_routes import build_adaptive_router
from app.grounded_coordinator import GroundedCoordinator
from app.research_repository import ResearchCheckpointRepository
from app.revision_repository import public_revision
from test_revision_sqlite import store,candidate,uid,run
from test_itineraries import generated


def client(store,monkeypatch):
    from app.auth import AuthError
    _,clock,g,r,rr,p=store
    monkeypatch.setenv('APP_MODE','local');monkeypatch.setenv('ADAPTIVE_PLANNING_PREVIEW','true')
    class Auth:
        async def verify(self,token):
            if token=='owner':return SimpleNamespace(id=p['user_id'])
            if token=='other':return SimpleNamespace(id=str(uuid4()))
            raise AuthError('AUTH_REQUIRED',401)
    e=GroundedCoordinator(r,SimpleNamespace(),research_repository=ResearchCheckpointRepository(g,enabled=True),revision_repository=rr,enabled=True,require_health=False)
    async def ready():pass
    e.verify_ready=ready
    app=FastAPI();app.include_router(build_adaptive_router(Auth(),e))
    return TestClient(app),e,p


def test_revision_http_owner_request_identity_and_no_auto_provider(store,monkeypatch):
    c,e,p=client(store,monkeypatch);base='/api/adaptive-plans/'+p['id'];h={'Authorization':'Bearer owner'}
    request={'requestId':uid(),'targetDate':p['start_date'],'instruction':'Prefer a quiet museum.'}
    response=c.post(base+'/revisions',headers=h,json=request)
    assert response.status_code==200,response.text
    row=response.json()['revision'];assert row['status']=='queued' and row['candidate'] is None
    assert 'instruction' not in response.text and 'provider_response_id' not in response.text
    assert c.post(base+'/revisions',headers=h,json=request).json()['revision']['id']==row['id']
    assert c.get(base+'/revision-requests/'+request['requestId'],headers=h).json()['revision']['id']==row['id']
    assert c.get(base+'/revisions/'+row['id'],headers={'Authorization':'Bearer other'}).status_code in (404,409)
    assert c.get('/api/adaptive-plans/'+uid()+'/revisions/'+row['id'],headers=h).status_code==404
    assert run(e.repository.get_plan(p['user_id'],p['id']))==p


def test_revision_http_explicit_accept_preserves_original(store,generated,monkeypatch):
    j=candidate(store,generated);c,e,p=client(store,monkeypatch);h={'Authorization':'Bearer owner'}
    base='/api/adaptive-plans/'+p['id']+'/revisions/'+j['id']
    draft=c.get(base,headers=h);assert draft.status_code==200
    assert draft.json()['revision']['candidate']['accepted'] is False
    accepted=c.post(base+'/accept',headers=h);assert accepted.status_code==200,accepted.text
    new_id=accepted.json()['revision']['acceptedPlanId'];assert new_id!=p['id']
    assert run(e.repository.get_plan(p['user_id'],p['id']))==p
    assert c.post(base+'/accept',headers=h).json()['revision']['acceptedPlanId']==new_id
    assert run(e.repository.get_plan(p['user_id'],new_id))['status']=='completed'


def test_invalid_revision_inputs_are_definitive_before_reservation(store,monkeypatch):
    c,e,p=client(store,monkeypatch);base='/api/adaptive-plans/'+p['id'];h={'Authorization':'Bearer owner'}
    for target,instruction in [('2026-02-31','Visit a museum'),(p['start_date'],'   '),(p['start_date'],'bad\x00input')]:
        response=c.post(base+'/revisions',headers=h,json={'requestId':uid(),'targetDate':target,'instruction':instruction})
        assert response.status_code==400,response.text
        assert response.json()['error']['code']=='REVISION_INVALID_REQUEST'
    with e.repository.gateway._connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM revision_jobs').fetchone()[0]==0


def test_known_revision_absence_is_exact_but_lookup_stays_distinct(store,monkeypatch):
    c,e,p=client(store,monkeypatch);base='/api/adaptive-plans/'+p['id'];h={'Authorization':'Bearer owner'}
    response=c.get(base+'/revisions/'+uid(),headers=h)
    assert response.status_code==404 and response.json()['error']['code']=='REVISION_NOT_FOUND'
    response=c.get(base+'/revision-requests/'+uid(),headers=h)
    assert response.status_code==404 and response.json()['error']['code']=='REVISION_NOT_FOUND'


def test_pending_revision_owner_recovery_opens_original_completed_trip(store,monkeypatch):
    c,e,p=client(store,monkeypatch);base='/api/adaptive-plans/'+p['id'];h={'Authorization':'Bearer owner'}
    request={'requestId':uid(),'targetDate':p['start_date'],'instruction':'Prefer a quiet garden.'}
    started=c.post(base+'/revisions',headers=h,json=request);assert started.status_code==200
    blocked=c.post('/api/adaptive-plans',headers=h,json={'requestId':uid(),'preferences':p['preferences']})
    assert blocked.status_code==429 and blocked.json()['error']['code']=='SECTION_OWNER_PLAN_EXISTS'
    current=c.get('/api/adaptive-plans/current',headers=h)
    assert current.status_code==200,current.text
    assert current.json()['plan']['id']==p['id'] and current.json()['plan']['status']=='completed'
    other=c.get('/api/adaptive-plans/current',headers={'Authorization':'Bearer other'})
    assert other.status_code==404
    with e.repository.gateway._connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM revision_jobs').fetchone()[0]==1


def test_recent_discarded_submission_is_capacity_not_missing_owner_plan(store,monkeypatch):
    from test_revision_sqlite import reserve,running
    _,_,_,_,rr,p=store
    j=running(rr,reserve(store));run(rr.reject(p['user_id'],j['id']))
    c,e,p=client(store,monkeypatch);h={'Authorization':'Bearer owner'}
    blocked=c.post('/api/adaptive-plans',headers=h,json={'requestId':uid(),'preferences':p['preferences']})
    assert blocked.status_code==429 and blocked.json()['error']['code']=='SECTION_CAPACITY_LIMIT'
    assert c.get('/api/adaptive-plans/current',headers=h).status_code==404
