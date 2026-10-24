"""Offline transport checks only; every provider has a fake key and MockTransport."""
import asyncio
import json
import logging
import httpx
import pytest
from fastapi.testclient import TestClient
from app.gemini import GeminiProvider, GeminiRecommendationService, DEFAULT_MODEL, MAX_ENVELOPE_BYTES
from app.main import create_app
from app.models import TripPreferences
from app.recommendations import RecommendationError

KEY = 'fake-test-key-not-a-secret'


def result_data(payload):
    return {'destination': payload['destination'], 'currency': payload['currency'], 'warnings': ['Unverified estimates.'],
        'recommendations': [dict(id=str(i), category=c, name='Option', description='Description',
            whyRecommended='Fits culture', estimatedGroupCost=10, interestTags=['culture'], travelStyle='',
            dietaryNotes='Confirm requirements', mobilityNotes='Confirm accessibility')
            for i,c in enumerate(['attraction','activity','dining'])]}


def envelope(text, reason='STOP'):
    return {'candidates': [{'finishReason': reason, 'content': {'parts': [{'text': text}]}}]}


def request_with(payload, handler, config=None):
    service = GeminiRecommendationService(configuration=config or (lambda: (KEY, DEFAULT_MODEL)),
        transport=httpx.MockTransport(handler))
    with TestClient(create_app(recommendation_service=service)) as client:
        return client.post('/api/recommendations', json=payload)


def test_gemini_success_request_and_safe_logs(payload, caplog):
    caplog.set_level(logging.DEBUG)
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.scheme=='https' and request.url.host=='generativelanguage.googleapis.com'
        assert request.url.path==f'/v1beta/models/{DEFAULT_MODEL}:generateContent'
        assert not request.url.query and request.headers['x-goog-api-key']==KEY
        body=json.loads(request.content)
        assert body['generationConfig']['responseFormat']['text']['mimeType']=='APPLICATION_JSON'
        schema=body['generationConfig']['responseFormat']['text']['schema']
        assert '$defs' in schema and schema['additionalProperties'] is False
        assert body['generationConfig']['candidateCount']==1
        assert body['generationConfig']['maxOutputTokens']==8192
        assert 'tools' not in body and body['contents'][0]['role']=='user'
        assert 'RECOMMENDATION SELECTION STAGE' in body['systemInstruction']['parts'][0]['text']
        return httpx.Response(200,json=envelope(json.dumps(result_data(payload))))
    r=request_with(payload,handler)
    assert r.status_code==200 and r.json()['provider']=='Google Gemini'
    assert r.json()['model']==DEFAULT_MODEL and len(calls)==1
    assert KEY not in caplog.text and KEY not in r.text


@pytest.mark.parametrize('key,model', [('',DEFAULT_MODEL), ('bad\nkey',DEFAULT_MODEL),
    (KEY,'../../evil'), (KEY,'https://evil.example'), (KEY,'gemini-x?key=bad'), (KEY,'')],
    ids=['missing-key','header-injection','path-traversal','foreign-host','query-injection','empty-model'])
def test_invalid_configuration_no_network(payload,key,model):
    def forbidden(request):
        pytest.fail('Invalid config attempted network')
    r=request_with(payload,forbidden,lambda:(key,model))
    assert r.status_code==503 and r.json()['error']['code']=='AI_NOT_CONFIGURED'
    assert KEY not in r.text


@pytest.mark.parametrize('status,code', [(301,'AI_PROVIDER_FAILED'),(401,'AI_PROVIDER_FAILED'),
    (403,'AI_PROVIDER_FAILED'),(429,'AI_RATE_LIMITED'),(500,'AI_PROVIDER_FAILED')])
def test_http_error_no_retry_redirect_or_body_leak(payload,status,code):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers={'Location':'https://evil.example'},text='SECRET-GOOGLE-ERROR '+KEY)
    r=request_with(payload,handler)
    assert r.json()['error']['code']==code and len(calls)==1
    assert 'SECRET' not in r.text and KEY not in r.text


@pytest.mark.parametrize('kind,code', [('timeout','AI_TIMEOUT'),('network','AI_PROVIDER_FAILED')])
def test_transport_error_safe(payload,kind,code):
    def handler(request):
        if kind=='timeout': raise httpx.ReadTimeout(KEY,request=request)
        raise httpx.ConnectError(KEY,request=request)
    r=request_with(payload,handler)
    assert r.json()['error']['code']==code and KEY not in r.text


@pytest.mark.parametrize('kind', ['prompt-block','safety','recitation','prohibited'])
def test_refusal(payload,kind):
    data={'promptFeedback':{'blockReason':'SAFETY'}} if kind=='prompt-block' else envelope('{}',
        {'safety':'SAFETY','recitation':'RECITATION','prohibited':'PROHIBITED_CONTENT'}[kind])
    r=request_with(payload,lambda req:httpx.Response(200,json=data))
    assert r.json()['error']['code']=='AI_REFUSED'


@pytest.mark.parametrize('kind', ['not-json','null','no-candidates','empty-candidates','truncated',
    'nontext','empty-text','oversized-envelope','oversized-text','invalid-inner-json','bad-schema'],
    ids=lambda value:value)
def test_invalid_response(payload,kind):
    cases={
        'not-json':b'not-json', 'null':b'null', 'no-candidates':b'{}',
        'empty-candidates':json.dumps({'candidates':[]}).encode(),
        'truncated':json.dumps(envelope('{}','MAX_TOKENS')).encode(),
        'nontext':json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'functionCall':{}}]}}]}).encode(),
        'empty-text':json.dumps(envelope('')).encode(),
        'oversized-envelope':b'x'*(MAX_ENVELOPE_BYTES+1),
        'oversized-text':json.dumps(envelope('x'*65537)).encode(),
        'invalid-inner-json':json.dumps(envelope('not-json')).encode(),
        'bad-schema':json.dumps(envelope('{}')).encode(),
    }
    r=request_with(payload,lambda req:httpx.Response(200,content=cases[kind]))
    assert r.status_code==502 and r.json()['error']['code']==('AI_OUTPUT_TRUNCATED' if kind=='truncated' else 'AI_INVALID_RESPONSE')


def test_default_app_without_config_is_offline(payload):
    with TestClient(create_app()) as client:
        assert client.get('/api/health').status_code==200
        r=client.post('/api/recommendations',json=payload)
    assert r.status_code==503


def test_configuration_read_error_safe(payload):
    def broken(): raise ValueError(KEY)
    r=request_with(payload,lambda req:pytest.fail('No network expected'),broken)
    assert r.status_code==503 and KEY not in r.text


def test_configuration_backend_only_and_process_override(monkeypatch):
    import app.gemini as module
    monkeypatch.undo()  # Restore real loader, then mock every config input below.
    seen=[]
    monkeypatch.setattr(module, 'dotenv_values', lambda path, interpolate: (seen.append((path,interpolate)) or
        {'GEMINI_API_KEY':'file-test-key','GEMINI_MODEL':'gemini-file-model'}))
    monkeypatch.setattr(module.os, 'environ', {'GEMINI_API_KEY':KEY,'GEMINI_MODEL':DEFAULT_MODEL})
    assert module.read_configuration()==(KEY,DEFAULT_MODEL)
    assert seen[0][0].name=='.env' and seen[0][0].parent.name=='backend' and seen[0][1] is False


def test_thought_part_not_exposed(payload):
    data=envelope(json.dumps(result_data(payload)))
    data['candidates'][0]['content']['parts'].insert(0,{'thought':True,'text':'PRIVATE-THOUGHT'})
    r=request_with(payload,lambda req:httpx.Response(200,json=data))
    assert r.status_code==200 and 'PRIVATE-THOUGHT' not in r.text
