"""3.3 orchestration tests use injected providers only; no live AI or database."""
import asyncio
import copy
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.recommendations import RecommendationService, ProviderRefusal


class NoDatabase:
    def __init__(self):
        self.calls = 0
    async def save(self, preferences):
        self.calls += 1
        return 101


class TestOnlyProvider:
    __test__ = False
    name = 'test-only-provider'
    model = 'test-only-model'
    def __init__(self, result=None, error=None, delay=0):
        self.result, self.error, self.delay = result, error, delay
        self.calls = []
    async def generate(self, messages, response_schema):
        self.calls.append((messages, response_schema))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def recommendations(payload):
    return {
        'destination': payload['destination'], 'currency': payload['currency'],
        'recommendations': [
            {'id': str(index), 'category': category, 'name': 'Test option',
             'description': 'Synthetic test fixture, not an actual recommendation.',
             'whyRecommended': 'Matches the selected culture interest in this test.',
             'estimatedGroupCost': 100, 'interestTags': ['culture'], 'travelStyle': '',
             'dietaryNotes': 'No preference supplied; verify dietary suitability.',
             'mobilityNotes': 'No needs supplied; accessibility is unverified.'}
            for index, category in enumerate(['attraction', 'activity', 'dining'])
        ], 'warnings': ['Synthetic fixture; all details are unverified.'],
    }


def make_client(provider=None, timeout=30):
    database = NoDatabase()
    service = RecommendationService(provider, timeout_seconds=timeout)
    return TestClient(create_app(database, service)), database


def test_unconfigured_and_existing_save_unchanged(payload):
    client, database = make_client()
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'AI_NOT_CONFIGURED'
    assert database.calls == 0
    assert client.post('/api/trips', json=payload).json() == {'trip': {'id': 101}}
    assert database.calls == 1


@pytest.mark.parametrize('as_json_string', [False, True])
def test_success_schema_prompts_no_save(payload, recommendations, as_json_string):
    provider = TestOnlyProvider(json.dumps(recommendations) if as_json_string else recommendations)
    client, database = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['source'] == 'ai'
    assert result['provider'] == provider.name and result['model'] == provider.model
    assert {item['category'] for item in result['recommendations']} == {'attraction', 'activity', 'dining'}
    assert len(provider.calls) == 1 and database.calls == 0
    messages, schema = provider.calls[0]
    assert [message['role'] for message in messages] == ['system', 'user']
    assert 'RECOMMENDATION SELECTION STAGE' in messages[0]['content']
    assert 'ENTIRE GROUP' in messages[0]['content']
    assert schema['properties']['recommendations']['minItems'] == 3
    assert schema['properties']['recommendations']['maxItems'] == 12


@pytest.mark.parametrize('body,status', [('{broken', 400), ('null', 400), ('[]', 400), ('123', 400), ('x'*16385, 413)], ids=['broken-json', 'null-body', 'array-body', 'number-body', 'oversized-body'])
def test_malformed_never_calls_provider(body, status):
    provider = TestOnlyProvider()
    client, database = make_client(provider)
    response = client.post('/api/recommendations', content=body, headers={'Content-Type':'application/json'})
    assert response.status_code == status
    assert provider.calls == [] and database.calls == 0


def test_validation_and_content_type(payload):
    provider = TestOnlyProvider()
    client, database = make_client(provider)
    assert client.post('/api/recommendations', content='{}').status_code == 415
    payload['budget'] = -1
    assert client.post('/api/recommendations', json=payload).status_code == 400
    assert not provider.calls and database.calls == 0


@pytest.mark.parametrize('error,code', [(ProviderRefusal('SECRET-refusal'), 'AI_REFUSED'), (RuntimeError('SECRET-provider'), 'AI_PROVIDER_FAILED')])
def test_provider_errors_safe(payload, error, code):
    provider = TestOnlyProvider(error=error)
    client, database = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 502
    assert response.json()['error']['code'] == code
    assert 'SECRET' not in response.text
    assert len(provider.calls) == 1 and database.calls == 0


def test_timeout_no_retry(payload):
    provider = TestOnlyProvider(delay=0.1)
    client, database = make_client(provider, timeout=0.001)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 504
    assert response.json()['error']['code'] == 'AI_TIMEOUT'
    assert len(provider.calls) == 1 and database.calls == 0


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(currency='USD'),
    lambda r: r.update(destination='Paris'),
    lambda r: r.update(extra='SECRET-extra'),
    lambda r: r.update(source='pretend-provider'),
    lambda r: r.update(recommendations=r['recommendations'][:2]),
    lambda r: r.update(recommendations=r['recommendations']*5),
    lambda r: r.update(warnings=['x'*501]),
    lambda r: r.update(warnings=['bad\nwarning']),
    lambda r: r.update(warnings=['\ud800']),
    lambda r: r['recommendations'][0].update(id=r['recommendations'][1]['id']),
    lambda r: r['recommendations'][0].update(category='dining'),
    lambda r: r['recommendations'][0].update(estimatedGroupCost=2501),
    lambda r: r['recommendations'][0].update(estimatedGroupCost=-1),
    lambda r: r['recommendations'][0].update(estimatedGroupCost=True),
    lambda r: r['recommendations'][0].update(estimatedGroupCost='100'),
    lambda r: r['recommendations'][0].update(estimatedGroupCost=float('inf')),
    lambda r: r['recommendations'][0].update(interestTags=['history']),
    lambda r: r['recommendations'][0].update(interestTags=['culture','culture']),
    lambda r: r['recommendations'][0].update(interestTags=['invalid']),
    lambda r: r['recommendations'][0].update(description=' '),
    lambda r: r['recommendations'][0].update(name='\ud800'),
    lambda r: r['recommendations'][0].update(dietaryNotes='x\n'),
])
def test_invalid_schema_or_preference_rejected(payload, recommendations, mutation):
    mutation(recommendations)
    provider = TestOnlyProvider(recommendations)
    client, database = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'AI_INVALID_RESPONSE'
    assert 'SECRET' not in response.text
    assert database.calls == 0


@pytest.mark.parametrize('raw', ['not-json', '```json\n{}\n```', 'null', '[]', 'x'*65537, {'huge':'x'*65537}], ids=['not-json', 'markdown-json', 'null-response', 'array-response', 'oversized-string', 'oversized-object'])
def test_bad_raw_response(payload, raw):
    client, _ = make_client(TestOnlyProvider(raw))
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'AI_INVALID_RESPONSE'


def test_style_match_and_all_preferences_in_prompt(payload, recommendations):
    payload.update(travelStyle='comfort', mobilityConcerns='Step-free paths', dietaryNeeds='jain')
    provider = TestOnlyProvider(recommendations)
    client, _ = make_client(provider)
    assert client.post('/api/recommendations', json=payload).status_code == 502
    for item in recommendations['recommendations']:
        item['travelStyle'] = 'comfort'
    assert client.post('/api/recommendations', json=payload).status_code == 200
    context = json.loads(provider.calls[0][0][1]['content'].split('\n',1)[1])
    assert context['travel_style'] == 'comfort'
    assert context['mobility_needs'] == 'Step-free paths'
    assert context['dietary_needs'] == 'jain'


@pytest.mark.parametrize('field,value', [('name','\ud800'), ('model','\ud800'), ('name','bad\n'), ('model','')])
def test_provider_metadata_safe(payload, recommendations, field, value):
    provider = TestOnlyProvider(recommendations)
    setattr(provider, field, value)
    client, _ = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'AI_INVALID_RESPONSE'


def test_surrogate_destination_safe_failure(payload, recommendations):
    payload['destination'] = recommendations['destination'] = '\ud800'
    client, _ = make_client(TestOnlyProvider(recommendations))
    response = client.post('/api/recommendations', content=json.dumps(payload), headers={'Content-Type':'application/json'})
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'AI_INVALID_RESPONSE'


def test_unicode_destination_and_no_selected_interests(payload, recommendations):
    payload['destination'] = recommendations['destination'] = '京都'
    payload['interests'] = []
    for item in recommendations['recommendations']:
        item['interestTags'] = []
    client, _ = make_client(TestOnlyProvider(recommendations))
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 200
    assert response.json()['destination'] == '京都'


def test_verification_instructions_are_server_bound_and_user_data_unchanged(payload, recommendations):
    from app.models import TripPreferences
    from app.prompts import build_itinerary_prompt
    original = copy.deepcopy(payload)
    provider = TestOnlyProvider(recommendations)
    client, database = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 200
    messages, _ = provider.calls[0]
    baseline_user = build_itinerary_prompt(TripPreferences(**payload)).messages[1].content
    assert messages[1]['content'] == baseline_user
    assert payload == original
    assert database.calls == 0
    for instruction in ['Do not invent available meals', 'allergen handling', 'step counts',
                        'ground-floor locations', 'access guarantees',
                        'confirmation questions are not assurances',
                        'Unspecified dietary and mobility needs must remain unspecified',
                        'Use confirmation questions for the venue']:
        assert instruction in messages[0]['content']
    data = json.loads(messages[1]['content'].split('\n', 1)[1])
    assert data['dietary_needs'].startswith('unspecified')
    assert data['mobility_needs'].startswith('unspecified')


def test_unverified_assurances_are_not_keyword_filtered_or_claimed_fact_checked(payload, recommendations):
    # Provider content stays intact. The UI must supply controlled verification guidance.
    recommendations['warnings'] = []
    recommendations['recommendations'][0]['dietaryNotes'] = 'suitable for all dietary needs; no allergens listed'
    recommendations['recommendations'][0]['mobilityNotes'] = 'all restaurants ground level accessible'
    provider = TestOnlyProvider(recommendations)
    client, database = make_client(provider)
    response = client.post('/api/recommendations', json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['warnings'] == []
    assert result['recommendations'][0]['dietaryNotes'] == recommendations['recommendations'][0]['dietaryNotes']
    assert result['recommendations'][0]['mobilityNotes'] == recommendations['recommendations'][0]['mobilityNotes']
    assert database.calls == 0
