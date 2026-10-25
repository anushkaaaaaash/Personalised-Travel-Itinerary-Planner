"""Every request uses MockTransport and fictional data. Never reads real keys."""
import asyncio
import inspect
import json
import logging
import httpx
import pytest
from app.groq import GroqProvider, DEFAULT_MODEL, ENDPOINT, MAX_ENVELOPE_BYTES, strict_schema
from app.providers import LLMProvider, create_provider
from app.recommendations import RecommendationPayload, RecommendationService, RecommendationError, ProviderRefusal
from app.models import TripPreferences

KEY = 'fake-groq-test-key-not-secret'
MESSAGES = [{'role':'system','content':'Return JSON'}, {'role':'user','content':'Fictional trip'}]
SCHEMA = RecommendationPayload.model_json_schema()


@pytest.mark.parametrize('model',['openai/gpt-oss-20b','openai/gpt-oss-120b'])
def test_exact_duration_domain_reaches_wire_without_mutation_or_retry(model):
    from copy import deepcopy
    from app.itineraries import ItineraryPayload
    schema=ItineraryPayload.model_json_schema()
    original=deepcopy(schema)
    projected=strict_schema(schema)
    assert strict_schema(projected)==projected
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        assert body['model']==model and body['max_completion_tokens']==4096
        contract=body['response_format']['json_schema']
        assert contract['strict'] is True
        duration=contract['schema']['$defs']['ItineraryActivity']['properties']['durationMinutes']
        assert duration['type']=='integer' and duration['enum']==list(range(15,241))
        assert 'minimum' not in duration and 'maximum' not in duration
        return httpx.Response(200,json=envelope())
    provider=GroqProvider(KEY,model=model,transport=httpx.MockTransport(handler))
    assert asyncio.run(provider.generate(MESSAGES,projected))=='{}'
    assert len(calls)==1 and schema==original


@pytest.mark.parametrize('value',[14,241,480,15.5,True,'60'])
def test_projected_duration_rejects_invalid_domain(value):
    from app.itineraries import ItineraryPayload
    from app.refinement_contract import check_shape
    schema=strict_schema(ItineraryPayload.model_json_schema())
    duration=schema['$defs']['ItineraryActivity']['properties']['durationMinutes']
    with pytest.raises(ValueError):check_shape(value,duration,schema)


@pytest.mark.parametrize('value',[15,16,239,240])
def test_projected_duration_accepts_exact_boundaries(value):
    from app.itineraries import ItineraryPayload
    from app.refinement_contract import check_shape
    schema=strict_schema(ItineraryPayload.model_json_schema())
    check_shape(value,schema['$defs']['ItineraryActivity']['properties']['durationMinutes'],schema)


def envelope(content='{}', reason='stop', **extra):
    return {'choices':[{'finish_reason':reason, 'message':{'role':'assistant','content':content, **extra}}]}


def run(handler, response_schema=SCHEMA):
    provider=GroqProvider(KEY, transport=httpx.MockTransport(handler))
    return asyncio.run(provider.generate(MESSAGES, response_schema))


def test_abstract_async_contract_and_default_factory():
    assert inspect.isabstract(LLMProvider)
    assert inspect.iscoroutinefunction(GroqProvider.generate)
    with pytest.raises(TypeError):
        LLMProvider()
    provider=create_provider(configuration=lambda:{'GROQ_API_KEY':KEY})
    assert isinstance(provider, LLMProvider) and provider.name=='Groq' and provider.model==DEFAULT_MODEL


def test_factory_explicit_gemini_and_invalid():
    from app.gemini import GeminiProvider
    assert isinstance(create_provider(configuration=lambda:{'AI_PROVIDER':'gemini','GEMINI_API_KEY':KEY}), GeminiProvider)
    for values in ({}, {'AI_PROVIDER':'unknown'}, {'AI_PROVIDER':'', 'GROQ_API_KEY':KEY}):
        with pytest.raises(RecommendationError) as error:
            create_provider(configuration=lambda:values)
        assert error.value.code=='AI_NOT_CONFIGURED'


def test_request_shape_schema_and_logs(caplog):
    caplog.set_level(logging.DEBUG)
    calls=[]
    def handler(request):
        calls.append(request)
        assert str(request.url)==ENDPOINT
        assert request.headers['Authorization']=='Bearer '+KEY
        body=json.loads(request.content)
        assert body['model']==DEFAULT_MODEL and body['messages']==MESSAGES
        assert body['stream'] is False and 'tools' not in body
        assert body['include_reasoning'] is False
        schema=body['response_format']['json_schema']
        assert schema['strict'] is True
        assert schema['schema']['additionalProperties'] is False
        assert '$defs' in schema['schema']
        assert 'minLength' not in json.dumps(schema)
        return httpx.Response(200,json=envelope())
    assert run(handler)=='{}' and len(calls)==1
    assert KEY not in caplog.text
    assert 'minLength' in json.dumps(SCHEMA)  # Not mutated.

def test_output_schema_rejection_is_distinct_safe_and_single_call(caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(400,json={'error':{'code':'json_validate_failed','type':'invalid_request_error',
            'message':'JSON does not validate with properties anyOf enum PRIVATE_OUTPUT', 'failed_generation':'PRIVATE_OUTPUT'}})
    with pytest.raises(RecommendationError) as error:run(handler)
    assert error.value.code=='AI_SCHEMA_REJECTED' and error.value.status==502
    assert len(calls)==1 and 'PRIVATE_OUTPUT' not in str(error.value)+caplog.text
    from app.groq import schema_message_paths
    assert schema_message_paths('schema.properties.vibe.anyOf.enum PRIVATE_OUTPUT')==[['schema','properties','vibe','anyOf','enum']]

@pytest.mark.parametrize('model',['openai/gpt-oss-20b','openai/gpt-oss-120b'])
def test_null_vibe_contract_reaches_strict_wire_schema_without_retry(model):
    from app.itineraries import ItineraryPayload
    schema=ItineraryPayload.model_json_schema()
    schema['properties']['vibe']={'type':'null'}
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        assert body['model']==model and body['max_completion_tokens']==4096
        assert body['response_format']['json_schema']['strict'] is True
        assert body['response_format']['json_schema']['schema']['properties']['vibe']=={'type':'null'}
        return httpx.Response(200,json=envelope('{"vibe":null}'))
    provider=GroqProvider(KEY,model=model,transport=httpx.MockTransport(handler))
    assert asyncio.run(provider.generate(MESSAGES,schema))=='{"vibe":null}'
    assert len(calls)==1


@pytest.mark.parametrize('key,model',[('',DEFAULT_MODEL),('bad\nkey',DEFAULT_MODEL),(KEY,'https://evil.test'),(KEY,'llama-3.3-70b-versatile')])
def test_invalid_configuration(key,model):
    with pytest.raises(RecommendationError):
        GroqProvider(key,model)


@pytest.mark.parametrize('status,code',[(301,'AI_PROVIDER_FAILED'),(400,'AI_PROVIDER_FAILED'),(401,'AI_PROVIDER_FAILED'),(403,'AI_PROVIDER_FAILED'),(429,'AI_RATE_LIMITED'),(503,'AI_PROVIDER_FAILED')])
def test_status_no_retry_or_leak(status,code):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':KEY},headers={'Location':'https://evil.test'})
    with pytest.raises(RecommendationError) as error:
        run(handler)
    assert error.value.code==code and len(calls)==1 and KEY not in str(error.value)


@pytest.mark.parametrize('data',[{},[],{'choices':[]},envelope(reason='length'),envelope(reason='tool_calls'),envelope(None),envelope(''),envelope('x'*65537),envelope(tool_calls=[{}]),envelope('\ud800')])
def test_reject_invalid_or_partial(data):
    with pytest.raises(RecommendationError) as error:
        run(lambda request:httpx.Response(200,content=json.dumps(data).encode()))
    assert error.value.code==('AI_OUTPUT_TRUNCATED' if data == envelope(reason='length') else 'AI_INVALID_RESPONSE')


@pytest.mark.parametrize('data',[envelope(refusal='Cannot comply'),envelope(reason='content_filter')])
def test_refusal(data):
    with pytest.raises(ProviderRefusal):
        run(lambda request:httpx.Response(200,json=data))


def test_bad_json_and_oversize_envelope():
    for body in (b'not json',b' '* (MAX_ENVELOPE_BYTES+1)):
        with pytest.raises(RecommendationError):
            run(lambda request:httpx.Response(200,content=body))


def test_timeout_and_connection_error():
    for exception in (httpx.ReadTimeout('private'),httpx.ConnectError('private')):
        def handler(request):
            raise exception
        with pytest.raises((TimeoutError,RecommendationError)) as error:
            run(handler)
        assert 'private' not in str(error.value)


def test_full_recommendation_service_validation(payload):
    good={'destination':payload['destination'],'currency':payload['currency'],'warnings':['Unverified.'],
        'recommendations':[dict(id=str(i),category=category,name='Option',description='Description',
        whyRecommended='Culture',estimatedGroupCost=10,interestTags=['culture'],travelStyle='',
        dietaryNotes='Unspecified',mobilityNotes='Unspecified')
        for i,category in enumerate(['attraction','activity','dining'])]}
    provider=GroqProvider(KEY,transport=httpx.MockTransport(lambda request:httpx.Response(200,json=envelope(json.dumps(good)))))
    response=asyncio.run(RecommendationService(provider).recommend(TripPreferences.model_validate(payload)))
    assert response.provider=='Groq' and response.source=='ai'
    good['currency']='EUR' if payload['currency']!='EUR' else 'USD'
    with pytest.raises(RecommendationError) as error:
        asyncio.run(RecommendationService(provider).recommend(TripPreferences.model_validate(payload)))
    assert error.value.code=='AI_INVALID_RESPONSE'

def test_truncation_distinct_safe_no_retry(caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        assert json.loads(request.content)['max_completion_tokens']==4096
        return httpx.Response(200,json=envelope('PRIVATE_TRUNCATED_VALUE',reason='length'))
    with pytest.raises(RecommendationError) as error:
        run(handler)
    assert error.value.code=='AI_OUTPUT_TRUNCATED'
    assert len(calls)==1
    assert 'PRIVATE_TRUNCATED_VALUE' not in str(error.value)+caplog.text


@pytest.mark.parametrize('status,category',[(400,'BAD_REQUEST'),(401,'AUTHENTICATION'),
    (403,'FORBIDDEN'),(413,'REQUEST_TOO_LARGE'),(422,'UNPROCESSABLE_REQUEST'),
    (429,'RATE_LIMIT'),(500,'UPSTREAM_ERROR'),(503,'UPSTREAM_ERROR'),(504,'UPSTREAM_TIMEOUT')])
def test_allowlisted_http_diagnostic_without_response_body(status,category,caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':{'message':'PRIVATE_BODY','code':'PRIVATE_CODE'},
            'prompt':'PRIVATE_PROMPT','token':KEY},headers={'X-Request-ID':'PRIVATE_HEADER'})
    with pytest.raises(RecommendationError):
        run(handler)
    assert len(calls)==1
    assert f'"httpStatus": {status}' in caplog.text and f'"category": "{category}"' in caplog.text
    assert all(secret not in caplog.text for secret in ['PRIVATE_BODY','PRIVATE_CODE','PRIVATE_PROMPT','PRIVATE_HEADER',KEY])


@pytest.mark.parametrize('event',['TRANSPORT_TIMEOUT','TRANSPORT_ERROR','RESPONSE_INVALID','REFUSAL','OUTPUT_TRUNCATED'])
def test_safe_failure_phase_diagnostic(event,caplog):
    def handler(request):
        if event=='TRANSPORT_TIMEOUT': raise httpx.ReadTimeout('PRIVATE_DETAIL')
        if event=='TRANSPORT_ERROR': raise httpx.ConnectError('PRIVATE_DETAIL')
        if event=='RESPONSE_INVALID': return httpx.Response(200,content=b'PRIVATE_DETAIL')
        if event=='REFUSAL': return httpx.Response(200,json=envelope(refusal='PRIVATE_DETAIL'))
        return httpx.Response(200,json=envelope('PRIVATE_DETAIL',reason='length'))
    with pytest.raises((TimeoutError,RecommendationError,ProviderRefusal)):
        run(handler)
    assert f'"event": "{event}"' in caplog.text
    assert 'PRIVATE_DETAIL' not in caplog.text and KEY not in caplog.text


def test_diagnostic_rejects_untrusted_values(caplog):
    from app.groq import provider_diagnostic
    provider_diagnostic('PRIVATE_EVENT','PRIVATE_STATUS')
    assert 'PRIVATE_EVENT' not in caplog.text
    provider_diagnostic('HTTP_FAILURE','PRIVATE_STATUS')
    assert 'OTHER_HTTP_STATUS' in caplog.text and 'PRIVATE_STATUS' not in caplog.text



def test_specific_schema_detail_is_sanitized_and_actionable(caplog):
    body={'error':{'code':'invalid_json_schema','type':'invalid_request_error',
        'param':'response_format.json_schema.schema.properties.fixedTime.enum',
        'message':'Invalid schema: enum values must be strings, not boolean. PRIVATE_CITY PRIVATE_TOKEN',
        'request':{'secret':KEY}}}
    with pytest.raises(RecommendationError): run(lambda request:httpx.Response(400,json=body))
    assert 'invalid_json_schema' in caplog.text
    # This test's outgoing schema has no fixedTime: global knowledge is not
    # permission to echo a name absent from the active request schema.
    assert 'fixedTime' not in caplog.text and 'UNKNOWN' in caplog.text
    assert '"enum", "values", "must", "be", "strings", "not", "boolean"' in caplog.text
    assert all(v not in caplog.text for v in ['PRIVATE_CITY','PRIVATE_TOKEN',KEY])


def test_specific_error_detail_unknowns_oversize_and_invalid_json(caplog):
    from app.groq import provider_error_detail
    assert provider_error_detail(b'x'*8193)=={'detail':'UNAVAILABLE','unavailableReason':'BODY_TOO_LARGE'}
    assert provider_error_detail(b'not-json')=={'detail':'UNAVAILABLE','unavailableReason':'INVALID_JSON_OR_ENCODING'}
    result=provider_error_detail(json.dumps({'error':{'code':KEY,'type':KEY,'param':'schema.PRIVATE_FIELD',
        'message':'PRIVATE_BODY '+KEY}}).encode())
    assert result['code']==result['type']=='OTHER_OR_ABSENT'
    assert result['parameterPath']==['schema','UNKNOWN']
    assert result['schemaTerms']==[]
    assert KEY not in json.dumps(result)


def test_non200_error_body_is_bounded_and_not_retried(caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(400,content=b'PRIVATE_BODY'*2000)
    with pytest.raises(RecommendationError): run(handler)
    assert len(calls)==1 and 'UNAVAILABLE' in caplog.text and 'PRIVATE_BODY' not in caplog.text


def test_message_schema_paths_keep_only_closed_schema_vocabulary():
    from app.groq import provider_error_detail
    message="Invalid at /properties/days/anyOf/properties/day_1/mainSlots; schema.properties.verificationWarning; schema.PRIVATE_SECRET; PRIVATE prose"
    result=provider_error_detail(json.dumps({'error':{'message':message}}).encode())
    assert result['schemaPaths']==[['properties','days','anyOf','properties','day_1','mainSlots'],['schema','properties','verificationWarning']]
    assert 'PRIVATE' not in json.dumps(result)


def test_message_paths_bounded_and_ignore_arbitrary_words():
    from app.groq import schema_message_paths
    assert schema_message_paths('expected object but found array')==[]
    assert schema_message_paths('schema.days '*1000)==[]
    assert schema_message_paths('schema.days '*10)==[['schema','days']]
