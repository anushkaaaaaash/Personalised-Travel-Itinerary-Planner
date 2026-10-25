"""Offline transport tests: no real accounts, mail, credentials or requests."""
import httpx
import pytest
from fastapi.testclient import TestClient
from app.auth import SupabaseAuthService, safe_retry_after
from app.main import create_app


@pytest.mark.parametrize('value,expected', [('60',60),('3600',3600),('86400',86400),('86401',None),('0',None),('-1',None),('PRIVATE_HEADER',None),(None,None)])
def test_safe_delay(value, expected):
    assert safe_retry_after(value) == expected


def test_http_date_delay(monkeypatch):
    monkeypatch.setattr('app.auth.time.time', lambda: 0)
    assert safe_retry_after('Thu, 01 Jan 1970 00:01:00 GMT') == 60
    assert safe_retry_after('Thu, 01 Jan 1970 00:01:00') is None
    assert safe_retry_after('Wed, 31 Dec 1969 23:59:59 GMT') is None


@pytest.mark.parametrize('path', ['/api/auth/register','/api/auth/login'])
@pytest.mark.parametrize('delay,expected', [('3600','3600'),('PRIVATE_HEADER',None),(None,None)])
def test_provider_rate_limit_preserved_once_with_cors_and_masking(monkeypatch, path, delay, expected):
    monkeypatch.delenv('FRONTEND_PREVIEW_ORIGIN', raising=False)
    for name, value in {'APP_ENV':'production','APP_MODE':'production','SAVED_ITINERARIES_SCHEMA_VERIFIED':'true','TRIP_OWNERSHIP_ENABLED':'false','TRIP_OWNERSHIP_SCHEMA_VERIFIED':'false','API_HOST':'api.example.test','FRONTEND_ORIGIN':'https://app.example.test'}.items():
        monkeypatch.setenv(name, value)
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, headers={'Retry-After':delay} if delay else {}, json={'message':'PRIVATE_PROVIDER_BODY'})
    service=SupabaseAuthService(lambda:('https://example.supabase.co','sb_publishable_test_only'),httpx.MockTransport(handler))
    response=TestClient(create_app(auth_service=service),base_url='https://api.example.test').post(path,headers={'Origin':'https://app.example.test'},json={'email':'person@example.com','password':'synthetic-test-only'})
    assert response.status_code == 429 and len(calls) == 1
    assert response.headers.get('retry-after') == expected
    assert 'retry-after' in response.headers['access-control-expose-headers'].lower()
    assert response.headers['access-control-allow-origin'] == 'https://app.example.test'
    assert response.headers['cache-control'] == 'no-store'
    assert 'PRIVATE_' not in response.text
    assert response.json()['error']['code'] == 'AUTH_RATE_LIMITED'
