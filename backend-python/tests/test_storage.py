import asyncio
import json
import httpx
import pytest
from app.models import TripPreferences
from app.storage import SupabaseTripStore, StorageNotConfigured, SaveUnconfirmed, trip_row

TEST_KEY = 'test-only-placeholder-not-a-real-key'

def test_exact_existing_schema(payload):
    payload.update(travelStyle='comfort', mobilityConcerns='Avoid stairs')
    row = trip_row(TripPreferences(**payload))
    assert set(row) == {'destination','start_date','end_date','budget','travelers','preferences'}
    assert row['start_date'] == payload['startDate']
    assert row['budget'] == payload['budget']
    assert isinstance(row['preferences'], str)
    prefs = json.loads(row['preferences'])
    assert prefs == {key:payload[key] for key in ['departureCity','currency','interests','dietaryNeeds','travelPace','travelStyle','mobilityConcerns']}

def test_fake_supabase_round_trip(payload):
    requests = []
    def fake(request):
        requests.append(request)
        assert request.url.path == '/rest/v1/trips'
        assert request.url.params['select'] == 'id'
        assert request.headers['prefer'] == 'return=representation'
        assert request.headers['apikey'] == TEST_KEY
        assert 'authorization' not in request.headers
        assert json.loads(request.content)['destination'] == 'Goa'
        return httpx.Response(201, json=[{'id':7}])
    store = SupabaseTripStore(lambda:('https://example.supabase.co',TEST_KEY), httpx.MockTransport(fake))
    assert asyncio.run(store.save(TripPreferences(**payload))) == 7
    assert len(requests) == 1

@pytest.mark.parametrize('status,data', [(400,{'message':'private SQL'}),(500,{}),(200,[{'id':1}]),(201,[]),(201,[{}]),(201,[{'id':0}]),(201,[{'id':1},{'id':2}])])
def test_storage_bad_responses(payload, status, data):
    calls=[]
    def fake(request):
        calls.append(request)
        return httpx.Response(status,json=data)
    store=SupabaseTripStore(lambda:('https://example.supabase.co',TEST_KEY),httpx.MockTransport(fake))
    with pytest.raises(SaveUnconfirmed) as exc:
        asyncio.run(store.save(TripPreferences(**payload)))
    assert not str(exc.value)
    assert len(calls)==1  # No unsafe automatic retries.

@pytest.mark.parametrize('url,key', [('',TEST_KEY),('https://example.supabase.co',''),('http://example.supabase.co',TEST_KEY),('https://evil.test',TEST_KEY),('https://example.supabase.co/other',TEST_KEY)])
def test_config_fail_closed(payload, url, key):
    def fake(request):
        pytest.fail('must not contact server')
    store=SupabaseTripStore(lambda:(url,key),httpx.MockTransport(fake))
    with pytest.raises(StorageNotConfigured):
        asyncio.run(store.save(TripPreferences(**payload)))
