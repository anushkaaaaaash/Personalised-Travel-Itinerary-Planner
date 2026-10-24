import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import SupabaseTripStore, ReadUnconfirmed, trip_row
from app.models import TripPreferences


def row(payload, identity=7):
    return dict(trip_row(TripPreferences(**payload)), id=identity, created_at='2026-10-24T12:00:00Z')

class Store:
    def __init__(self, rows):
        self.rows, self.calls = rows, []
    async def list(self, limit, offset):
        self.calls.append(('list', limit, offset))
        return self.rows[offset:offset+limit]
    async def get(self, identity):
        self.calls.append(('get', identity))
        return next((r for r in self.rows if str(r['id']) == str(identity)), None)
    async def save(self, preferences):
        pytest.fail('Reads never save')

def test_list_detail_history(payload):
    store = Store([row(payload, 9223372036854775807), row(payload, 3)])
    client = TestClient(create_app(store))
    response = client.get('/api/trips?limit=1')
    assert response.status_code == 200
    body = response.json()
    assert body['trips'][0]['id'] == '9223372036854775807'
    assert body['hasMore'] and body['scope'] == 'local-project-saved-trips'
    assert body['trips'][0]['preferences']['destination'] == payload['destination']
    assert client.get('/api/history?limit=1').json() == body
    assert client.get('/api/trips/3').json()['trip']['id'] == 3
    assert client.get('/api/trips/4').status_code == 404

@pytest.mark.parametrize('query', ['limit=0','limit=51','offset=-1','offset=10001','limit=x'])
def test_bad_page(query):
    store = Store([])
    assert TestClient(create_app(store)).get('/api/trips?' + query).status_code == 400
    assert not store.calls

@pytest.mark.parametrize('identity', ['0','-1','1.0','1e2','9223372036854775808','abc','01'])
def test_bad_identity(identity):
    store = Store([])
    assert TestClient(create_app(store)).get('/api/trips/' + identity).status_code == 400
    assert not store.calls

@pytest.mark.parametrize('raw', ['broken', '[]', 'null', '{}', '{"secret":"do-not-expose"}', 'x'*17000])
def test_bad_legacy_preferences_not_exposed(payload, raw):
    item = row(payload)
    item['preferences'] = raw
    response = TestClient(create_app(Store([item]))).get('/api/trips')
    assert response.status_code == 200
    record = response.json()['trips'][0]
    assert record['preferences'] is None
    assert record['preferencesStatus'] == 'unavailable'
    assert 'do-not-expose' not in response.text

def test_supabase_read_queries(payload):
    calls = []
    def fake(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.path == '/rest/v1/trips'
        assert request.url.params['select'] == 'id,destination,start_date,end_date,budget,travelers,preferences,created_at'
        assert 'authorization' not in request.headers
        return httpx.Response(200, json=[row(payload)])
    store = SupabaseTripStore(lambda: ('https://example.supabase.co','test-secret'), httpx.MockTransport(fake))
    assert asyncio.run(store.list(21, 0))[0]['id'] == 7
    assert calls[0].url.params['order'] == 'created_at.desc,id.desc'
    assert asyncio.run(store.get('7'))['id'] == 7
    assert calls[1].url.params['id'] == 'eq.7'

@pytest.mark.parametrize('status,data', [(500,{'secret':'private'}),(302,[]),(200,{}),(200,[{'id':9}])])
def test_bad_reads(status, data):
    calls=[]
    def fake(request):
        calls.append(request)
        return httpx.Response(status, json=data)
    store=SupabaseTripStore(lambda:('https://example.supabase.co','test-secret'),httpx.MockTransport(fake))
    with pytest.raises(ReadUnconfirmed):
        asyncio.run(store.get('7'))
    assert len(calls) == 1

def test_empty_reads():
    body = TestClient(create_app(Store([]))).get('/api/trips').json()
    assert body['trips'] == [] and not body['hasMore']

OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'

def test_owned_storage_read_and_save(payload, monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    calls=[]
    def fake(request):
        calls.append(request)
        assert request.headers['apikey']=='sb_publishable_test'
        assert request.headers['authorization']=='Bearer verified-user-token'
        assert 'user_id' in request.url.params['select']
        if request.method=='POST':
            assert json.loads(request.content)['user_id']==OWNER
            return httpx.Response(201,json=[{'id':7,'user_id':OWNER}])
        assert request.url.params['user_id']=='eq.'+OWNER
        return httpx.Response(200,json=[dict(row(payload),user_id=OWNER)])
    # The base privileged configuration must never execute for authenticated access.
    base=SupabaseTripStore(lambda:pytest.fail('privileged config accessed'),httpx.MockTransport(fake))
    store=base.for_user(OWNER,'verified-user-token')
    assert asyncio.run(store.get('7'))['user_id']==OWNER
    assert asyncio.run(store.save(TripPreferences(**payload)))==7
    assert len(calls)==2

@pytest.mark.parametrize('method', ['read','save'])
def test_owned_rows_reject_other_owner(payload,monkeypatch,method):
    from app.storage import SaveUnconfirmed
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    def fake(request):
        return httpx.Response(201 if method=='save' else 200,json=[dict(row(payload),user_id=OTHER)])
    store=SupabaseTripStore(transport=httpx.MockTransport(fake)).for_user(OWNER,'verified-token')
    with pytest.raises(SaveUnconfirmed if method=='save' else ReadUnconfirmed):
        asyncio.run(store.save(TripPreferences(**payload)) if method=='save' else store.get('7'))

def test_owner_never_falls_back_to_secret(monkeypatch):
    from app.storage import StorageNotConfigured
    monkeypatch.setenv('SUPABASE_SECRET_KEY','must-not-read')
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_secret_not-public')
    store=SupabaseTripStore(transport=httpx.MockTransport(lambda r:pytest.fail('must not send'))).for_user(OWNER,'verified-token')
    with pytest.raises(StorageNotConfigured):
        asyncio.run(store.list())
