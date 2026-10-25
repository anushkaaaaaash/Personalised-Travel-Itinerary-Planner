import pytest
from app.cors import configured_frontend_origins

@pytest.mark.parametrize('value,expected',[
 ('',[]),('*',[]),('http://example.com',[]),('https://example.com',['https://example.com']),
 ('https://example.com/',['https://example.com']),('https://user:pass@example.com',[]),
 ('https://example.com/path',[]),('https://example.com?x=1',[]),('https://example.com:bad',[]),
 ('https://example.com\n.evil.com',[]),('https://example.com,https://evil.com',[]),
])
def test_explicit_origin(monkeypatch,value,expected):
    monkeypatch.delenv('FRONTEND_PREVIEW_ORIGIN',raising=False)
    monkeypatch.setenv('FRONTEND_ORIGIN',value)
    assert configured_frontend_origins()==expected

PRIMARY='https://personalised-travel-itinerary-plann.vercel.app'
PREVIEW='https://personalised-travel-itinerary-planner-git-f-0f4c9b-anushka-76c5.vercel.app'

def test_exact_pair_optional_and_deduplicated(monkeypatch):
    monkeypatch.setenv('FRONTEND_ORIGIN',PRIMARY)
    monkeypatch.setenv('FRONTEND_PREVIEW_ORIGIN',PREVIEW)
    assert configured_frontend_origins()==[PRIMARY,PREVIEW]
    monkeypatch.setenv('FRONTEND_PREVIEW_ORIGIN',PRIMARY)
    assert configured_frontend_origins()==[PRIMARY]
    monkeypatch.delenv('FRONTEND_ORIGIN')
    assert configured_frontend_origins()==[]

@pytest.mark.parametrize('value',['*','https://*.vercel.app','http://preview.example.test','https://user:pass@preview.example.test','https://preview.example.test/path','https://preview.example.test?x=1','https://preview.example.test#x','https://preview.example.test:8443','https://preview.example.test,https://other.example.test','https://preview.example.test\\evil','https://preview.example.test\n.evil.test'])
def test_bad_optional_origin_fails_closed(monkeypatch,value):
    monkeypatch.setenv('FRONTEND_ORIGIN',PRIMARY)
    monkeypatch.setenv('FRONTEND_PREVIEW_ORIGIN',value)
    assert configured_frontend_origins()==[]

def production_client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.auth import AuthError
    class Auth:
        def configured(self):return True
        async def verify(self,token):raise AuthError()
    for key,value in {'APP_MODE':'production','APP_ENV':'production','API_HOST':'api.example.test','SAVED_ITINERARIES_SCHEMA_VERIFIED':'true','TRIP_OWNERSHIP_ENABLED':'false','TRIP_OWNERSHIP_SCHEMA_VERIFIED':'false','FRONTEND_ORIGIN':PRIMARY,'FRONTEND_PREVIEW_ORIGIN':PREVIEW}.items():monkeypatch.setenv(key,value)
    return TestClient(create_app(auth_service=Auth()),base_url='https://api.example.test')

@pytest.mark.parametrize('origin',[PRIMARY,PREVIEW])
def test_approved_pair_preflight_and_actual_requests_still_require_auth(monkeypatch,origin):
    client=production_client(monkeypatch)
    response=client.options('/api/auth/login',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
    assert response.status_code==200 and response.headers['access-control-allow-origin']==origin
    assert client.get('/api/auth/config',headers={'Origin':origin}).status_code==200
    assert client.get('/api/saved-itineraries',headers={'Origin':origin}).status_code==401
    assert client.get('/api/saved-itineraries',headers={'Origin':origin,'Authorization':'Bearer synthetic-expired'}).status_code==401
    assert client.get('/api/trips',headers={'Origin':origin}).status_code==404

@pytest.mark.parametrize('origin',[PREVIEW+'.evil.test',PREVIEW.replace('0f4c9b','0f4c9c'),'https://unapproved.vercel.app','null',PRIMARY+'/',PRIMARY+','+PREVIEW])
def test_foreign_and_lookalike_origins_rejected_by_cors_and_access_boundary(monkeypatch,origin):
    client=production_client(monkeypatch)
    preflight=client.options('/api/auth/login',headers={'Origin':origin,'Access-Control-Request-Method':'POST'})
    assert preflight.status_code==400 and 'access-control-allow-origin' not in preflight.headers
    actual=client.get('/api/auth/config',headers={'Origin':origin})
    assert actual.status_code==403 and actual.json()['error']['code']=='ORIGIN_FORBIDDEN'

def test_malformed_preview_blocks_startup_and_requests(monkeypatch):
    client=production_client(monkeypatch)
    monkeypatch.setenv('FRONTEND_PREVIEW_ORIGIN','*')
    from app.production import create_production_app
    with pytest.raises(ValueError):create_production_app()
    assert client.get('/api/health').status_code==503
