import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import StorageNotConfigured

class FakeStore:
    def __init__(self, identity=42, error=None):
        self.calls = []
        self.identity = identity
        self.error = error
    async def save(self, preferences):
        self.calls.append(preferences)
        if self.error:
            raise self.error
        return self.identity

def test_save_and_health(payload):
    store = FakeStore()
    with TestClient(create_app(store)) as client:
        assert client.get('/api/health').json() == {'status': 'ok', 'backend': 'fastapi'}
        response = client.post('/api/trips', json=payload)
        assert response.status_code == 201
        assert response.json() == {'trip': {'id': 42}}
        assert len(store.calls) == 1

@pytest.mark.parametrize('field,value', [
    ('destination',''), ('destination','x'*201), ('destination','Goa\n'),
    ('departureCity',''), ('startDate','2026-02-30'), ('startDate','2026-1-01'),
    ('startDate','0000-01-01'), ('endDate','2026-10-01'),
    ('travelers',True), ('travelers','2'), ('travelers',0), ('travelers',21), ('travelers',1.5),
    ('budget',True), ('budget','2500'), ('budget',0), ('budget',-1),
    ('currency','GBP'), ('interests',['food','food']), ('interests',['unknown']), ('interests','food'),
    ('dietaryNeeds','keto'), ('travelPace','moderate'), ('travelStyle','unknown'),
    ('mobilityConcerns',None), ('mobilityConcerns','x'*501), ('mobilityConcerns','steps\n'),
    ('unknown','secret'),
])
def test_invalid_before_storage(payload, field, value):
    store = FakeStore()
    payload[field] = value
    response = TestClient(create_app(store)).post('/api/trips', json=payload)
    assert response.status_code == 400
    assert not store.calls
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'

@pytest.mark.parametrize('field', ['destination','departureCity','startDate','endDate','budget','travelers','currency','interests','dietaryNeeds','travelPace'])
def test_required(payload, field):
    del payload[field]
    assert TestClient(create_app(FakeStore())).post('/api/trips', json=payload).status_code == 400

@pytest.mark.parametrize('body', ['{"private":"do-not-echo",', '123', 'null', '[]', 'true', '{"budget":NaN}'])
def test_bad_json_safe(body):
    store = FakeStore()
    response = TestClient(create_app(store)).post('/api/trips', content=body, headers={'Content-Type':'application/json'})
    assert response.status_code == 400
    assert 'do-not-echo' not in response.text
    assert not store.calls

def test_content_boundaries():
    client = TestClient(create_app(FakeStore()))
    assert client.post('/api/trips', content='{}').status_code == 415
    assert client.post('/api/trips', content='x'*16385, headers={'Content-Type':'application/json'}).status_code == 413

@pytest.mark.parametrize('identity', [None, '', ' ', ' leading', '12\n', 0, -1, 1.5, True, {}, [], '9223372036854775808'])
def test_unconfirmed_id(payload, identity):
    response = TestClient(create_app(FakeStore(identity))).post('/api/trips', json=payload)
    assert response.status_code == 500
    assert 'Check stored trips before retrying' in response.text

def test_bigint_preserved(payload):
    response = TestClient(create_app(FakeStore(9223372036854775807))).post('/api/trips', json=payload)
    assert response.json()['trip']['id'] == '9223372036854775807'

@pytest.mark.parametrize('error,status', [(StorageNotConfigured(),503), (RuntimeError('private-key-and-SQL'),500)])
def test_errors_safe(payload, error, status):
    response = TestClient(create_app(FakeStore(error=error))).post('/api/trips', json=payload)
    assert response.status_code == status
    assert 'private-key-and-SQL' not in response.text

def test_prompt_no_database(payload):
    store = FakeStore(error=AssertionError('must not save'))
    client = TestClient(create_app(store))
    response = client.post('/api/prompts/itinerary', json=payload)
    assert response.status_code == 200
    assert response.json()['generated'] is False
    assert response.json()['tripDays'] == 6
    assert not store.calls
    schema = client.get('/openapi.json').json()
    assert 'TripPreferences' in schema['components']['schemas']


def test_huge_numeric_budget_is_validation_error(payload):
    payload['budget'] = 10 ** 400
    store = FakeStore()
    client = TestClient(create_app(store))
    for endpoint in ['/api/trips', '/api/prompts/itinerary']:
        response = client.post(endpoint, content=json.dumps(payload), headers={'Content-Type': 'application/json'})
        assert response.status_code == 400
    assert not store.calls


def test_prompt_escapes_lone_surrogate_without_crash(payload):
    payload['destination'] = '\ud800'
    response = TestClient(create_app(FakeStore())).post('/api/prompts/itinerary', content=json.dumps(payload), headers={'Content-Type': 'application/json'})
    assert response.status_code == 200
    context = json.loads(response.json()['messages'][1]['content'].split('\n', 1)[1])
    assert context['destination'] == payload['destination']
