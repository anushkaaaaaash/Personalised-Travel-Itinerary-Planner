import json
import httpx
from fastapi.testclient import TestClient
from app.auth import SupabaseAuthService
from app.main import create_app
from app.storage import SupabaseTripStore, trip_row
from app.models import TripPreferences
A='12345678-1234-1234-1234-123456789abc'
B='22345678-1234-1234-1234-123456789abc'

def test_owned_app_all_trip_routes_bound_to_verified_user(monkeypatch,payload):
    monkeypatch.setenv('APP_MODE','production')
    monkeypatch.setenv('TRIP_OWNERSHIP_ENABLED','true')
    monkeypatch.setenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED','true')
    calls=[]
    def auth_request(request):
        user=A if request.headers['authorization']=='Bearer test-access-token-a' else B
        return httpx.Response(200,json={'id':user,'email':'test@example.com','email_confirmed_at':'2026-01-01T00:00:00Z'})
    auth=SupabaseAuthService(configuration=lambda:('https://test.supabase.co','sb_publishable_test'),transport=httpx.MockTransport(auth_request))
    def store_request(request):
        calls.append(request)
        assert request.headers['apikey']=='sb_publishable_test'
        user=A if request.headers['authorization']=='Bearer test-access-token-a' else B
        if request.method=='POST':
            assert json.loads(request.content)['user_id']==user
            return httpx.Response(201,json=[{'id':7,'user_id':user}])
        assert request.url.params['user_id']=='eq.'+user
        return httpx.Response(200,json=[dict(trip_row(TripPreferences(**payload)),id=7,user_id=user,created_at=None)])
    monkeypatch.setenv('SUPABASE_URL','https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    store=SupabaseTripStore(configuration=lambda:('https://legacy.supabase.co','PRIVATE-LEGACY-KEY'),transport=httpx.MockTransport(store_request))
    client=TestClient(create_app(store=store,auth_service=auth))
    assert client.get('/api/trips').status_code==401
    assert not calls
    for token in ['test-access-token-a','test-access-token-b']:
        headers={'Authorization':'Bearer '+token}
        for path in ['/api/trips','/api/history','/api/trips/7']:
            response=client.get(path,headers=headers)
            assert response.status_code==200,response.text
            assert response.headers['cache-control']=='no-store'
            assert 'user_id' not in response.text
        response=client.post('/api/trips',headers=headers,json=payload)
        assert response.status_code==201,response.text
    assert len(calls)==8

def test_production_missing_owner_verification_closed(monkeypatch):
    monkeypatch.setenv('APP_MODE','production')
    monkeypatch.delenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED',raising=False)
    client=TestClient(create_app())
    for path in ['/api/health','/api/trips','/api/auth/config']:
        assert client.get(path).status_code==503
