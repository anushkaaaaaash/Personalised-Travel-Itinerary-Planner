"""Synthetic provider errors only; no account, prompt or provider requests."""
import json
import httpx
import pytest
from app.groq import provider_error_detail, strict_schema
from app.itineraries import ItineraryPayload
from app.warning_contract import WarningContract
from app.schema_diagnostics import schema_names, missing_properties
from app.recommendations import RecommendationError
from test_groq import run


@pytest.fixture
def schema():
    value = ItineraryPayload.model_json_schema()
    value['properties']['vibe'] = {'type': 'null'}
    return strict_schema(WarningContract(value).schema)


def detail(message, schema, **extra):
    return provider_error_detail(json.dumps({'error': {'code': 'json_validate_failed',
        'type': 'invalid_request_error', 'message': message, **extra},
        'failed_generation': 'PRIVATE_FAILED_OUTPUT'}).encode(), schema)


@pytest.mark.parametrize('name', ['verificationWarning', 'additionalWarnings', 'destination',
    'travelPace', 'dietaryNotes', 'activities', 'departureTravel', 'mainActivityCount'])
@pytest.mark.parametrize('template', ["required: missing properties: '{name}'", 'missing required properties: "{name}"', "'{name}' is a required property"])
def test_exact_active_missing_names_retained(schema, name, template):
    result = detail(template.format(name=name), schema)
    assert result['missingProperties'] == [name]
    assert 'PRIVATE' not in json.dumps(result)


def test_nested_active_paths_and_unknowns(schema):
    result = detail('at /properties/days/items/properties/dietaryNotes; schema.properties.warnings.properties.verificationWarning; schema.PRIVATE_FIELD', schema,
        param='schema.properties.PRIVATE_FIELD')
    assert result['schemaPaths'] == [['properties', 'days', 'items', 'properties', 'dietaryNotes'],
        ['schema', 'properties', 'warnings', 'properties', 'verificationWarning']]
    assert result['parameterPath'] == ['schema', 'properties', 'UNKNOWN']
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('message', [
    "missing properties: 'PRIVATE_TOKEN'", "missing properties: 'Destination'",
    "missing properties: 'destination.private'", "missing properties: 'destination@example.test'",
    "missing properties: 'destination' + PRIVATE_TEXT", '"destination": "PRIVATE_VALUE"',
    "'destination' is valid; PRIVATE_TEXT", "missing properties: 'notActive', 'verificationWarning'",
])
def test_untrusted_content_never_echoed(schema, message):
    result = detail(message, schema)
    assert 'PRIVATE' not in json.dumps(result)
    assert set(result['missingProperties']) <= {'destination', 'verificationWarning'}


def test_names_must_be_in_current_schema_not_global_allowlist(schema):
    small = {'type': 'object', 'properties': {'status': {'type': 'string'}}}
    result = detail("missing properties: 'verificationWarning', 'status'; schema.properties.destination", small)
    assert result['missingProperties'] == ['status']
    assert result['schemaPaths'] == []
    assert 'verificationWarning' not in json.dumps(result)


def test_unknown_value_and_failed_generation_are_not_scanned(schema):
    result = detail('required properties missing', schema,
        failed_generation={'destination': 'PRIVATE_VALUE', 'warnings': []},
        request={'prompt': 'PRIVATE_PROMPT'}, description="missing properties: 'destination'")
    assert result['missingProperties'] == []
    assert 'PRIVATE' not in json.dumps(result)


def test_bounded_deduplicated_known_names(schema):
    names, _ = schema_names(schema)
    message = 'missing properties: ' + ', '.join(repr(n) for n in sorted(names))
    result = detail(message, schema)
    assert len(result['missingProperties']) <= 8
    assert len(set(result['missingProperties'])) == len(result['missingProperties'])
    assert detail("missing properties: 'destination', 'destination'", schema)['missingProperties'] == ['destination']
    assert missing_properties("missing properties: 'destination'" + 'x' * 8192, names) == []
    assert provider_error_detail(b'x' * 8193, schema)['unavailableReason'] == 'BODY_TOO_LARGE'


def test_schema_inventory_ignores_values_and_fails_closed_on_excess():
    schema = {'properties': {'status': {'enum': ['PRIVATE_ENUM'], 'description': 'PRIVATE_TEXT',
        'default': {'PRIVATE_DEFAULT': 'x'}}}, '$defs': {'Known': {'properties': {'child': {'type': 'null'}}}}}
    assert schema_names(schema) == (frozenset({'status', 'child'}), frozenset({'Known'}))
    assert schema_names({'properties': {f'field_{i}': {} for i in range(257)}}) == (frozenset(), frozenset())
    cycle = {}; cycle['items'] = cycle
    assert schema_names(cycle) == (frozenset(), frozenset())


def test_actual_provider_error_uses_outgoing_schema_once(caplog):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={'error': {'code': 'json_validate_failed',
            'message': "required: missing properties: 'status', 'verificationWarning', 'PRIVATE_VALUE'",
            'failed_generation': 'PRIVATE_OUTPUT'}})
    with pytest.raises(RecommendationError) as error:
        run(handler)
    assert error.value.code == 'AI_SCHEMA_REJECTED'
    assert len(calls) == 1
    names, _ = schema_names(calls[0]['response_format']['json_schema']['schema'])
    # test_groq.run supplies its own small schema; only its actual names may be emitted.
    expected = [n for n in ('status', 'verificationWarning') if n in names]
    assert '"missingProperties": ' + json.dumps(expected) in caplog.text
    assert 'PRIVATE' not in caplog.text
