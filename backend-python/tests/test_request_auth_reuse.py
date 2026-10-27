"""Request-local verified identity reuse; no auth cache or live service calls."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import AccessBoundary, AuthError, verified_request_user
from app.adaptive_routes import build_adaptive_router
from test_production_readiness import configure

class Auth:
    def __init__(self): self.calls=[]; self.owner=str(uuid4()); self.denied=False
    def configured(self): return True
    async def verify(self, token):
        self.calls.append(token)
        if token!='valid' or self.denied: raise AuthError()
        return SimpleNamespace(id=self.owner)

class Engine:
    require_health=True
    def capability_ready(self): return True
    async def current_context(self,owner): return {'owner':owner}

def client(monkeypatch,auth,*,middleware=True):
    configure(monkeypatch)
    monkeypatch.setattr('app.adaptive_activation.route_enabled',lambda e:True)
    app=FastAPI();app.include_router(build_adaptive_router(auth,Engine()))
    if middleware: app.add_middleware(AccessBoundary,auth_service=auth)
    return TestClient(app,base_url='https://api.example.test')

def test_production_poll_checks_auth_once_each_request_and_revocation(monkeypatch):
    auth=Auth();c=client(monkeypatch,auth)
    for _ in range(2):
        r=c.get('/api/adaptive-plans/current',headers={'Authorization':'Bearer valid'})
        assert r.status_code==200 and r.json()['owner']==auth.owner
    assert auth.calls==['valid','valid']
    auth.denied=True
    assert c.get('/api/adaptive-plans/current',headers={'Authorization':'Bearer valid'}).status_code==401
    assert len(auth.calls)==3

@pytest.mark.parametrize('middleware',[True,False])
def test_direct_routes_and_spoofed_headers_never_bypass_verify(monkeypatch,middleware):
    auth=Auth();c=client(monkeypatch,auth,middleware=middleware)
    spoof={'X-Auth-User-Id':auth.owner,'X-Verified-Auth':'true'}
    assert c.get('/api/adaptive-plans/current',headers=spoof).status_code==401
    assert c.get('/api/adaptive-plans/current',headers={**spoof,'Authorization':'Bearer expired'}).status_code==401
    assert c.get('/api/adaptive-plans/current',headers={**spoof,'Authorization':'Bearer valid'}).status_code==200
    assert auth.calls==['expired','valid']

def test_scope_copy_service_change_token_change_and_user_state_not_trusted():
    async def scenario():
        a=Auth();b=Auth()
        scope={'headers':[(b'authorization',b'Bearer valid')], 'state':{'auth_user_id':'spoofed'}}
        assert (await verified_request_user(a,scope)).id==a.owner
        await verified_request_user(a,scope);assert len(a.calls)==1
        await verified_request_user(a,dict(scope));assert len(a.calls)==2
        assert (await verified_request_user(b,scope)).id==b.owner
        scope['headers']=[(b'authorization',b'Bearer expired')]
        with pytest.raises(AuthError):await verified_request_user(b,scope)
        assert b.calls==['valid','expired']
    asyncio.run(scenario())
