import asyncio
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from app.auth import AccessBoundary,AuthError,build_auth_router
from app.production_security import ProductionAccess,settings
from app.configuration import ProviderSettings,private_backend_values
from app.providers import create_provider

class Auth:
    def configured(self):return True
    async def verify(self,token):
        if token!='valid':raise AuthError()
        return SimpleNamespace(id='11111111-1111-4111-8111-111111111111')

def configure(monkeypatch):
    for key,value in {'APP_MODE':'production','APP_ENV':'production','SAVED_ITINERARIES_SCHEMA_VERIFIED':'true','TRIP_OWNERSHIP_ENABLED':'false','TRIP_OWNERSHIP_SCHEMA_VERIFIED':'false','API_HOST':'api.example.test','FRONTEND_ORIGIN':'https://app.example.test'}.items():monkeypatch.setenv(key,value)

def client(monkeypatch):
    configure(monkeypatch);app=FastAPI();app.add_middleware(AccessBoundary,auth_service=Auth())
    @app.get('/api/trips')
    @app.get('/api/history')
    @app.get('/api/trips/{trip_id}')
    def legacy(trip_id=None):pytest.fail('Production must never enter legacy storage')
    @app.post('/api/itineraries/generate')
    def ai():return {'mock':True}
    @app.get('/api/saved-itineraries')
    def saved(request:Request):return {'owner':request.state.auth_user_id}
    app.include_router(build_auth_router(Auth()))
    return TestClient(app,base_url='https://api.example.test')

def test_production_disables_legacy_even_with_verified_user(monkeypatch):
    c=client(monkeypatch)
    for path in ['/api/trips','/api/trips/1','/api/history']:
        assert c.get(path,headers={'Authorization':'Bearer valid'}).status_code==404

@pytest.mark.parametrize('key,value',[('APP_MODE','local'),('SAVED_ITINERARIES_SCHEMA_VERIFIED','false'),('TRIP_OWNERSHIP_ENABLED','true'),('API_HOST','*'),('FRONTEND_ORIGIN','*')])
def test_production_configuration_fails_closed(monkeypatch,key,value):
    c=client(monkeypatch);monkeypatch.setenv(key,value)
    assert c.get('/api/saved-itineraries',headers={'Authorization':'Bearer valid'}).status_code==503

def test_production_auth_host_origin_and_config(monkeypatch):
    c=client(monkeypatch)
    assert c.get('/api/saved-itineraries').status_code==401
    assert c.get('/api/saved-itineraries',headers={'Authorization':'Bearer expired'}).status_code==401
    assert c.get('/api/saved-itineraries',headers={'Authorization':'Bearer valid','Host':'evil.example'}).status_code==400
    assert c.get('/api/saved-itineraries',headers={'Authorization':'Bearer valid','Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/saved-itineraries',headers={'Authorization':'Bearer valid','Origin':'https://app.example.test'}).status_code==200
    assert c.get('/api/auth/config').json()['saved_only'] is True

def test_ai_budget_is_bounded_and_no_retry(monkeypatch):
    c=client(monkeypatch)
    for _ in range(6):assert c.post('/api/itineraries/generate',headers={'Authorization':'Bearer valid'}).status_code==200
    assert c.post('/api/itineraries/generate',headers={'Authorization':'Bearer valid'}).status_code==429

def test_rate_window_expires_without_retaining_tokens(monkeypatch):
    configure(monkeypatch);now=[0];boundary=ProductionAccess(None,Auth(),clock=lambda:now[0])
    from collections import deque
    bucket=deque();assert boundary.consume(bucket,1,60);assert not boundary.consume(bucket,1,60)
    now[0]=61;assert boundary.consume(bucket,1,60);assert list(bucket)==[61]

def test_production_entry_point_fails_before_app_creation(monkeypatch):
    from app.production import create_production_app
    monkeypatch.setenv('APP_MODE','production')
    with pytest.raises((ValueError,RuntimeError)):create_production_app()

def test_hosted_configuration_never_reads_local_files(monkeypatch):
    import app.configuration as cfg
    monkeypatch.setenv('APP_ENV','staging')
    monkeypatch.setattr(cfg,'dotenv_values',lambda *a,**k:pytest.fail('No workstation file in staging'))
    assert private_backend_values()['APP_ENV']=='staging'

def test_local_environment_overrides_file_without_interpolation(monkeypatch):
    import app.configuration as cfg
    for key in ['RENDER','VERCEL','APP_ENV','APP_MODE']:monkeypatch.delenv(key,raising=False)
    def file(*a,**k):assert k['interpolate'] is False;return {'OPENAI_MODEL':'file-model'}
    monkeypatch.setattr(cfg,'dotenv_values',file);monkeypatch.setenv('OPENAI_MODEL','process-model')
    assert private_backend_values()['OPENAI_MODEL']=='process-model'

def test_typed_provider_settings_hide_secrets_and_preserve_model_defaults():
    s=ProviderSettings(OPENAI_API_KEY='fixture-private-value')
    assert 'fixture-private-value' not in repr(s)
    assert s.OPENAI_MODEL=='gpt-6-luna' and s.OPENAI_REASONING_EFFORT=='max'
    p=create_provider(lambda:{'OPENAI_API_KEY':'synthetic-fixture-only','OPENAI_MODEL':'gpt-6-luna'},for_refinement=True)
    assert p.model=='gpt-6-luna'
    with pytest.raises(Exception):ProviderSettings(OPENAI_MODEL='unsupported')

def test_legacy_configuration_cannot_be_read_in_production(monkeypatch):
    from app.storage import read_configuration,StorageNotConfigured
    monkeypatch.setenv('APP_MODE','production')
    with pytest.raises(StorageNotConfigured):read_configuration()

def test_startup_validates_provider_before_serving_without_any_paid_call(monkeypatch):
    from app.production import create_production_app
    configure(monkeypatch)
    monkeypatch.setenv('SUPABASE_URL','https://synthetic.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_synthetic')
    monkeypatch.setenv('AI_PROVIDER','openai');monkeypatch.setenv('OPENAI_API_KEY','x')
    with pytest.raises(RuntimeError,match='invalid'):create_production_app()
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-provider-only')
    app=create_production_app()
    assert TestClient(app,base_url='https://api.example.test').get('/api/health').status_code==200

def test_two_inflight_ai_requests_block_third_and_release_after_completion(monkeypatch):
    import httpx
    configure(monkeypatch)
    async def scenario():
        entered=0;ready=asyncio.Event();release=asyncio.Event()
        app=FastAPI();app.add_middleware(AccessBoundary,auth_service=Auth())
        @app.post('/api/itineraries/generate')
        async def generate():
            nonlocal entered
            entered+=1
            if entered==2:ready.set()
            await release.wait();return {'synthetic':True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://api.example.test',headers={'Authorization':'Bearer valid'}) as c:
            first=asyncio.create_task(c.post('/api/itineraries/generate'));second=asyncio.create_task(c.post('/api/itineraries/generate'))
            await asyncio.wait_for(ready.wait(),2)
            assert (await c.post('/api/itineraries/generate')).status_code==429
            release.set();assert all(r.status_code==200 for r in await asyncio.gather(first,second))
            assert (await c.post('/api/itineraries/generate')).status_code==200
    asyncio.run(scenario())
