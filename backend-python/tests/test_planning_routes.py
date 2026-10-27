import asyncio
from uuid import uuid4, UUID
from fastapi.testclient import TestClient
from app.auth import AuthUser, AuthError
from app.main import create_app
from app.planning_jobs import PlanningJobEngine

A='12345678-1234-1234-1234-123456789abc'
B='22345678-1234-1234-1234-123456789abc'
class Auth:
    def configured(self): return True
    async def verify(self,token):
        if token not in {'a','b'}:raise AuthError()
        return AuthUser(id=UUID(A if token=='a' else B))
async def generate(p):
    await asyncio.sleep(60)

def test_preview_disabled_by_default(monkeypatch,payload):
    monkeypatch.delenv('PLANNING_JOBS_PREVIEW',raising=False)
    client=TestClient(create_app(auth_service=Auth(),planning_engine=PlanningJobEngine(generate)))
    response=client.post('/api/planning-jobs',json={'requestId':str(uuid4()),'preferences':payload})
    assert response.status_code==404

def test_preview_verifies_owner_and_request_dedup(monkeypatch,payload):
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true')
    monkeypatch.setenv('APP_MODE','local')
    engine=PlanningJobEngine(generate)
    with TestClient(create_app(auth_service=Auth(),planning_engine=engine)) as client:
        body={'requestId':str(uuid4()),'preferences':payload}
        assert client.post('/api/planning-jobs',json=body).status_code==401
        response=client.post('/api/planning-jobs',json=body,headers={'Authorization':'Bearer a'})
        assert response.status_code==200,response.text
        job=response.json();url='/api/planning-jobs/'+job['id']
        assert response.headers['cache-control']=='no-store'
        assert client.post('/api/planning-jobs',json=body,headers={'Authorization':'Bearer a'}).json()['id']==job['id']
        assert client.get(url,headers={'Authorization':'Bearer b'}).status_code==404
        assert client.post(url+'/cancel',json={},headers={'Authorization':'Bearer b'}).status_code==404
        assert client.post(url+'/cancel',json={},headers={'Authorization':'Bearer a'}).json()['status']=='cancelled'
        assert client.post('/api/planning-jobs',json={**body,'owner':B},headers={'Authorization':'Bearer a'}).status_code==400

def test_engine_injection_cannot_enable_production(monkeypatch):
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true')
    monkeypatch.setenv('APP_MODE','production')
    client=TestClient(create_app(auth_service=Auth(),planning_engine=PlanningJobEngine(generate)))
    assert client.get('/api/planning-jobs/'+str(uuid4()),headers={'Authorization':'Bearer a'}).status_code!=200

def test_mixed_case_hosted_marker_never_enables_preview(monkeypatch):
    from app.planning_routes import preview_enabled
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true')
    monkeypatch.setenv('APP_MODE','local')
    for value in ('Production','STAGING','production'):
        monkeypatch.setenv('APP_ENV',value)
        assert not preview_enabled()
