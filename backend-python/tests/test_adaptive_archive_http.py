from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import AuthError
from app.adaptive_archive_routes import build_archive_router,archive_enabled
from test_adaptive_expenses import completed
from test_adaptive_archive_service import Archive
from test_adaptive_integration import OWNER


def client(completed,enabled=lambda:True):
    _,repo,_,_,_=completed;stores={};verifications=[]
    class Auth:
        async def verify(self,token):
            verifications.append(token)
            if token not in {'owner','other'}:raise AuthError('AUTH_REQUIRED',401)
            return SimpleNamespace(id=OWNER if token=='owner' else '22222222-2222-4222-8222-222222222222')
    def factory(owner,token):
        if owner not in stores:stores[owner]=Archive();stores[owner].owner_id=owner
        return stores[owner]
    app=FastAPI();app.include_router(build_archive_router(Auth(),SimpleNamespace(repository=repo),factory,enabled))
    return TestClient(app),stores,verifications


def test_actual_sqlite_save_steps_protected_reopen_without_provider(completed):
    c,stores,auth=client(completed);_,repo,provider,p,_=completed;h={'Authorization':'Bearer owner'}
    rid=str(uuid4());body={'requestId':rid,'title':'A complete trip','expectedVersion':p['version']};url='/api/adaptive-plans/'+p['id']+'/save'
    assert c.post(url,json=body).status_code==401 and not stores
    first=c.post(url,headers=h,json=body);assert first.status_code==200,first.text
    assert first.json()['savedSections']==3 and not first.json()['persisted']
    checked=c.get('/api/saved-adaptive-trips/requests/'+rid,headers=h);assert checked.json()==first.json()
    second=c.post(url,headers=h,json=body);assert second.status_code==200,second.text
    saved=second.json()['savedId'];assert saved and provider.calls==4
    detail=c.get('/api/saved-adaptive-trips/'+saved,headers=h);assert detail.status_code==200,detail.text
    assert len(detail.json()['sections'])==3 and detail.json()['nextCursor']==3
    last=c.get('/api/saved-adaptive-trips/'+saved+'?afterSequence=3',headers=h);assert len(last.json()['sections'])==1
    other=c.get('/api/saved-adaptive-trips/requests/'+rid,headers={'Authorization':'Bearer other'})
    assert other.status_code==404 and other.json()['error']['code']=='SAVED_ADAPTIVE_REQUEST_NOT_FOUND'
    assert 'user_id' not in detail.text and 'provider_response_id' not in detail.text and provider.calls==4


def test_disabled_and_invalid_save_have_no_writes(completed,monkeypatch):
    monkeypatch.delenv('ADAPTIVE_SAVED_TRIPS_ENABLED',raising=False);monkeypatch.delenv('ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED',raising=False)
    assert archive_enabled() is False
    monkeypatch.setenv('ADAPTIVE_SAVED_TRIPS_ENABLED','true');assert archive_enabled() is False
    monkeypatch.setenv('ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED','true');assert archive_enabled() is True
    c,stores,_=client(completed,lambda:False);p=completed[3]
    body={'requestId':str(uuid4()),'title':'Trip','expectedVersion':p['version']};url='/api/adaptive-plans/'+p['id']+'/save'
    assert c.post(url,headers={'Authorization':'Bearer owner'},json=body).status_code==404 and not stores
    c,stores,_=client(completed)
    for t in ['   ','bad\x00title']:
        r=c.post(url,headers={'Authorization':'Bearer owner'},json={**body,'title':t})
        assert r.status_code==400 and r.json()['error']['code']=='SAVED_ADAPTIVE_INVALID_REQUEST'
    assert not stores[OWNER].writes


def test_delete_requires_owner_and_exact_version_without_touching_source(completed):
    c,stores,_=client(completed);_,repo,provider,p,_=completed;h={'Authorization':'Bearer owner'}
    body={'requestId':str(uuid4()),'title':'Trip','expectedVersion':p['version']};url='/api/adaptive-plans/'+p['id']+'/save'
    c.post(url,headers=h,json=body);saved=c.post(url,headers=h,json=body).json()['savedId'];path='/api/saved-adaptive-trips/'+saved
    assert c.request('DELETE',path,json={'version':1}).status_code==401
    assert c.request('DELETE',path,headers={'Authorization':'Bearer other'},json={'version':1}).status_code==404
    assert c.request('DELETE',path,headers=h,json={'version':2}).status_code==409
    result=c.request('DELETE',path,headers=h,json={'version':1});assert result.status_code==200,result.text
    assert result.json()=={'id':saved,'version':1,'deleted':True}
    assert c.get(path,headers=h).status_code==404 and provider.calls==4
    from test_adaptive_archive_service import run
    assert run(repo.get_plan(OWNER,p['id']))==p
