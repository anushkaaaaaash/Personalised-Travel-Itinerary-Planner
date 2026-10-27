"""Offline deadline/diagnostic coverage; fake transports only, never live AI."""
import asyncio
import json
import logging
import httpx
import pytest
from app.ai_timeout import (AI_SERVICE_TIMEOUT_SECONDS, ProviderTransportTimeout,
    wait_for_provider, timeout_diagnostic)
from app.openai import OpenAIProvider
from app.itineraries import ItineraryService
from app.recommendations import RecommendationService
from test_openai import MESSAGES, SCHEMA, KEY, envelope


def diagnostics(caplog):
    return [json.loads(record.message.split('AI provider diagnostic: ', 1)[1])
            for record in caplog.records if 'AI provider diagnostic: ' in record.message]


def test_coordinated_backend_deadlines_and_unchanged_wire_policy():
    assert ItineraryService().timeout_seconds == RecommendationService().timeout_seconds == AI_SERVICE_TIMEOUT_SECONDS == 190
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.extensions['timeout'] == {'connect':10, 'read':180, 'write':45, 'pool':45}
        body=json.loads(request.content)
        assert body['model']=='gpt-6-luna' and body['reasoning']=={'effort':'max'}
        assert body['store'] is False and body['stream'] is False
        assert body['max_output_tokens']==32768 and body['text']['format']['strict'] is True
        return httpx.Response(200,json=envelope())
    p=OpenAIProvider(KEY,transport=httpx.MockTransport(handler))
    assert asyncio.run(p.generate(MESSAGES,SCHEMA))=='{}'
    assert len(calls)==1


@pytest.mark.parametrize('kind,label',[(httpx.ReadTimeout,'READ'),(httpx.ConnectTimeout,'CONNECT'),
    (httpx.WriteTimeout,'WRITE'),(httpx.PoolTimeout,'POOL'),(httpx.TimeoutException,'OTHER')])
def test_transport_timeout_is_classified_without_raw_content_or_retries(kind,label,caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        raise kind('PRIVATE_EXCEPTION_AND_URL',request=request)
    p=OpenAIProvider(KEY,transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderTransportTimeout):
        asyncio.run(wait_for_provider(p.generate(MESSAGES,SCHEMA),190))
    values=diagnostics(caplog)
    assert len(values)==len(calls)==1
    assert values[0]['event']=='TRANSPORT_TIMEOUT' and values[0]['timeoutType']==label
    assert values[0]['stage']=='WAIT_RESPONSE'
    assert type(values[0]['elapsedMs']) is int and 0<=values[0]['elapsedMs']<=3600000
    assert not any(private in caplog.text for private in ('PRIVATE_EXCEPTION_AND_URL',KEY,'Return JSON','Fictional trip','Authorization'))


@pytest.mark.parametrize('status,stage',[(200,'READ_RESPONSE_BODY'),(400,'READ_ERROR_BODY')])
def test_body_timeout_has_correct_stage(status,stage,caplog):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout('PRIVATE_BODY')
            yield b''
    p=OpenAIProvider(KEY,transport=httpx.MockTransport(lambda _:httpx.Response(status,stream=Stream())))
    with pytest.raises(ProviderTransportTimeout):asyncio.run(p.generate(MESSAGES,SCHEMA))
    assert diagnostics(caplog)[0]['stage']==stage
    assert 'PRIVATE_BODY' not in caplog.text


def test_total_deadline_cancels_single_call_and_logs_distinctly(caplog):
    calls=[]; canceled=[]
    async def slow():
        calls.append(1)
        try:await asyncio.sleep(10)
        finally:canceled.append(1)
    with pytest.raises(TimeoutError):asyncio.run(wait_for_provider(slow(),0.001))
    assert calls==canceled==[1]
    value=diagnostics(caplog)
    assert len(value)==1 and value[0]['event']=='SERVICE_TIMEOUT'
    assert value[0]['timeoutType']=='TOTAL' and value[0]['stage']=='PROVIDER_CALL'


def test_delayed_success_and_explicit_cancellation_have_no_false_timeout(caplog):
    async def success():
        await asyncio.sleep(0.005)
        return 'complete'
    assert asyncio.run(wait_for_provider(success(),0.1))=='complete'
    async def cancel():
        task=asyncio.create_task(wait_for_provider(asyncio.sleep(10),190))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(cancel())
    assert diagnostics(caplog)==[]


@pytest.mark.parametrize('event,subtype,stage,elapsed',[
    ('PRIVATE','READ','WAIT_RESPONSE',1),('TRANSPORT_TIMEOUT','PRIVATE','WAIT_RESPONSE',1),
    ('TRANSPORT_TIMEOUT','READ','PRIVATE',1),('TRANSPORT_TIMEOUT','READ','WAIT_RESPONSE','PRIVATE'),
    ('TRANSPORT_TIMEOUT','READ','WAIT_RESPONSE',float('nan')),
    ('TRANSPORT_TIMEOUT','READ','WAIT_RESPONSE',float('inf'))])
def test_timeout_telemetry_rejects_non_allowlisted_values(event,subtype,stage,elapsed,caplog):
    caplog.set_level(logging.WARNING)
    timeout_diagnostic(event,subtype,stage,elapsed)
    assert diagnostics(caplog)==[]


def test_provider_raised_timeout_is_not_mislabelled_as_service_deadline(caplog):
    async def provider():
        raise TimeoutError('PRIVATE_PROVIDER_TIMEOUT')
    with pytest.raises(TimeoutError):asyncio.run(wait_for_provider(provider(),190))
    assert diagnostics(caplog)==[]


@pytest.mark.parametrize('seconds,expected',[(-1,0),(0.125,125),(1e300,3600000)])
def test_elapsed_is_bounded_integer(seconds,expected,caplog):
    timeout_diagnostic('TRANSPORT_TIMEOUT','READ','WAIT_RESPONSE',seconds)
    assert diagnostics(caplog)[0]['elapsedMs']==expected
