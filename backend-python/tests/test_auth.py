"""No real credentials, files, accounts or external requests in these tests."""
import asyncio
import json
import time
import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.auth import (Credentials, SupabaseAuthService, AuthError, AccessBoundary,
                      build_auth_router, auth_error)

UID = '11111111-1111-4111-8111-111111111111'
USER = {'id': UID, 'email': 'person@example.com', 'email_confirmed_at': '2026-01-01T00:00:00Z'}
CREDENTIALS = {'email': 'person@example.com', 'password': 'private-test-password'}


def service(handler):
    return SupabaseAuthService(lambda: ('https://example.supabase.co', 'sb_publishable_test_only'), httpx.MockTransport(handler))


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize('email,password', [('bad', '12345678'), ('a@b.com','short'), ('a@b.com','x'*129), ('a\n@b.com','12345678')])
def test_validation(email, password):
    with pytest.raises(ValidationError):
        Credentials(email=email, password=password)


def test_password_repr_redacted():
    assert CREDENTIALS['password'] not in repr(Credentials(**CREDENTIALS))


def test_signup_pending_does_not_claim_confirmation_or_identity():
    def handler(request):
        assert request.url.path == '/auth/v1/signup'
        assert json.loads(request.content) == CREDENTIALS
        return httpx.Response(200, json=USER)
    result = run(service(handler).authenticate(Credentials(**CREDENTIALS), register=True))
    assert result.pending_confirmation and result.user is None and result.session is None


def test_real_provider_session_passthrough_no_refresh_token():
    def handler(request):
        assert request.url.path == '/auth/v1/token' and request.url.params['grant_type'] == 'password'
        return httpx.Response(200, json={'user':USER,'access_token':'provider-issued-test-token','refresh_token':'never-exposed', 'expires_in':3600, 'token_type':'bearer'})
    result = run(service(handler).authenticate(Credentials(**CREDENTIALS))).model_dump(mode='json')
    assert result['session']['access_token'] == 'provider-issued-test-token'
    assert result['session']['expires_at'] >= int(time.time()) + 3599
    assert 'never-exposed' not in str(result)


@pytest.mark.parametrize('status', [400,401,403,422,429,500,302])
def test_provider_errors_never_echo(status):
    with pytest.raises(AuthError) as exc:
        run(service(lambda r: httpx.Response(status,json={'message':CREDENTIALS['password']})).authenticate(Credentials(**CREDENTIALS)))
    assert CREDENTIALS['password'] not in str(exc.value)
    assert CREDENTIALS['password'] not in exc.value.message


@pytest.mark.parametrize('expires', [0,-1,'3600',99999999])
def test_invalid_or_expired_session_refused(expires):
    with pytest.raises(AuthError):
        run(service(lambda r: httpx.Response(200,json={'user':USER,'access_token':'token','expires_in':expires,'token_type':'bearer'})).authenticate(Credentials(**CREDENTIALS)))


def test_verified_identity_comes_from_auth_user_endpoint():
    def handler(request):
        assert request.url.path == '/auth/v1/user'
        assert request.headers['authorization'] == 'Bearer supplied-token'
        return httpx.Response(200,json=USER)
    assert str(run(service(handler).verify('supplied-token')).id) == UID


@pytest.mark.parametrize('status', [401,403])
def test_wrong_or_expired_bearer_refused(status):
    with pytest.raises(AuthError):
        run(service(lambda r:httpx.Response(status,json={'error':'bad-token'})).verify('wrong-token'))


def test_unconfirmed_user_refused():
    with pytest.raises(AuthError):
        run(service(lambda r:httpx.Response(200,json={'id':UID})).verify('token'))


@pytest.mark.parametrize('url,key', [('https://evil.example','sb_publishable_test'), ('http://x.supabase.co','sb_publishable_test'), ('https://x.supabase.co@evil.example','sb_publishable_test'), ('https://x.supabase.co','sb_secret_no'), ('https://x.supabase.co','arbitrary-key')])
def test_bad_config_fails_without_network(url,key):
    def forbidden(request):
        pytest.fail('Must not request unsafe/unconfigured provider')
    adapter = SupabaseAuthService(lambda:(url,key),httpx.MockTransport(forbidden))
    assert not adapter.configured()
    with pytest.raises(AuthError):
        run(adapter.verify('token'))


def client(monkeypatch, *, supported=False, configured=True):
    for name in ['APP_MODE','APP_ENV','RENDER','VERCEL','TRIP_OWNERSHIP_ENABLED','TRIP_OWNERSHIP_SCHEMA_VERIFIED']:
        monkeypatch.delenv(name,raising=False)
    adapter = service(lambda r:httpx.Response(200,json=USER)) if configured else SupabaseAuthService(lambda:('',''))
    app = FastAPI()
    app.add_middleware(AccessBoundary,auth_service=adapter,ownership_supported=supported)
    @app.get('/api/trips')
    def trips(): return {'protected':True}
    app.include_router(build_auth_router(adapter))
    return TestClient(app)


def test_production_fails_closed_without_owner_adapter(monkeypatch):
    c = client(monkeypatch)
    monkeypatch.setenv('APP_MODE','production')
    monkeypatch.setenv('TRIP_OWNERSHIP_ENABLED','true')
    monkeypatch.setenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED','true')
    assert c.get('/api/trips',headers={'Authorization':'Bearer token'}).status_code == 503


def test_production_missing_schema_fails_closed(monkeypatch):
    c = client(monkeypatch,supported=True)
    monkeypatch.setenv('APP_MODE','production')
    monkeypatch.setenv('TRIP_OWNERSHIP_ENABLED','true')
    assert c.get('/api/trips').status_code == 503


def test_owned_mode_requires_verified_bearer(monkeypatch):
    c = client(monkeypatch,supported=True)
    monkeypatch.setenv('APP_MODE','local')
    monkeypatch.setenv('TRIP_OWNERSHIP_ENABLED','true')
    monkeypatch.setenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED','true')
    assert c.get('/api/trips').status_code == 401
    assert c.get('/api/trips',headers={'Authorization':'Bearer token'}).status_code == 200


def test_local_proxy_header_refused(monkeypatch):
    c = client(monkeypatch)
    assert c.get('/api/trips',headers={'X-Forwarded-For':'127.0.0.1'}).status_code == 503


def test_integrated_validation_does_not_echo_password():
    from app.main import create_app
    c = TestClient(create_app(auth_service=service(lambda r: pytest.fail('Invalid inputs must not call auth'))))
    response = c.post('/api/auth/login', json={'email':'bad','password':'private-bad-pass'})
    assert response.status_code == 400
    assert 'private-bad-pass' not in response.text and 'bad' not in response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'


def test_logout_only_current_session_and_no_refresh_exposure():
    paths = []
    def handler(request):
        paths.append(str(request.url))
        return httpx.Response(200,json=USER) if request.url.path.endswith('/user') else httpx.Response(204)
    run(service(handler).logout('token'))
    assert paths[-1].endswith('/auth/v1/logout?scope=local')


def test_malformed_signup_success_not_reported_pending():
    with pytest.raises(AuthError):
        run(service(lambda r:httpx.Response(200,json={})).authenticate(Credentials(**CREDENTIALS),register=True))


def test_user_scope_comes_only_from_verified_endpoint(monkeypatch):
    from fastapi import Request
    for name in ['RENDER','VERCEL','APP_ENV']:
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('APP_MODE','local')
    monkeypatch.setenv('TRIP_OWNERSHIP_ENABLED','true')
    monkeypatch.setenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED','true')
    app=FastAPI()
    app.add_middleware(AccessBoundary,auth_service=service(lambda r:httpx.Response(200,json=USER)),ownership_supported=True)
    @app.get('/api/private')
    def private(request:Request): return {'owner':request.state.auth_user_id}
    response=TestClient(app).get('/api/private',headers={'Authorization':'Bearer provider-token', 'X-User-Id':'attacker'})
    assert response.json()=={'owner':UID}

@pytest.mark.parametrize('confirmed,status',[(True,200),(False,401)])
def test_confirmation_route_requires_authoritative_confirmed_user(confirmed,status):
    def handler(request):
        assert request.url.path == '/auth/v1/user'
        assert request.headers['authorization']=='Bearer supplied-token'
        return httpx.Response(200,json={**USER,'email_confirmed_at':USER['email_confirmed_at'] if confirmed else None})
    app=FastAPI();app.include_router(build_auth_router(service(handler)))
    with TestClient(app) as client:
        response=client.get('/api/auth/confirmation',headers={'Authorization':'Bearer supplied-token'})
        assert response.status_code==status
        assert response.headers['cache-control']=='no-store'
        if confirmed:assert response.json()=={'confirmed':True}
        assert 'supplied-token' not in response.text and USER['email'] not in response.text
        assert client.get('/api/auth/confirmation?confirmed=true').status_code==401
