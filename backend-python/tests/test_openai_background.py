"""Offline only: fictional key, HTTPX fake transport, no environment discovery."""
import asyncio
import json
import logging

import httpx
import pytest

from app.openai_background import (BackgroundActivation, BackgroundError,
    OpenAIBackgroundClient, MAX_ENVELOPE_BYTES)

KEY = 'fake-background-test-key'
SCHEMA = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
APPROVED = BackgroundActivation(True, True)


def envelope(status='queued', **changes):
    value = {'object': 'response', 'id': 'resp_test123', 'status': status, 'output': [], 'error': None}
    if status == 'completed':
        value['output'] = [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                            'content': [{'type': 'output_text', 'text': '{}'}]}]
    value.update(changes)
    return value


def client(handler, **options):
    return OpenAIBackgroundClient(KEY, transport=httpx.MockTransport(handler),
                                  activation=options.pop('activation', APPROVED), **options)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('activation', [None, BackgroundActivation(), BackgroundActivation(True, False),
                                       BackgroundActivation(False, True), BackgroundActivation(1, True)])
def test_default_and_partial_gate_prevent_every_request(activation):
    def forbidden(request):
        pytest.fail('Disabled adapter touched transport')
    provider = client(forbidden, activation=activation)
    for call in (provider.create('system', 'user', SCHEMA), provider.retrieve('resp_test123'), provider.cancel('resp_test123')):
        with pytest.raises(BackgroundError, match='BACKGROUND_NOT_APPROVED'):
            run(call)


def test_create_exact_wire_and_safe_metadata(caplog):
    calls = []
    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert request.url == 'https://api.openai.com/v1/responses'
        assert payload['background'] is True and payload['store'] is False and payload['stream'] is False
        assert payload['model'] == 'gpt-6-luna' and payload['reasoning'] == {'effort': 'max'}
        assert payload['text']['format']['strict'] is True
        assert 'include' not in payload and 'metadata' not in payload
        return httpx.Response(200, json=envelope('completed', usage={'input_tokens': 2, 'output_tokens': 3,
            'total_tokens': 5, 'unknown': 'private'}, output=[{'type': 'reasoning', 'summary': 'PRIVATE_REASONING'},
            {'type': 'message', 'role': 'assistant', 'status': 'completed',
             'content': [{'type': 'output_text', 'text': '{"private":"trip"}'}]}]))
    with caplog.at_level(logging.WARNING):
        result = run(client(handler).create('PRIVATE_SYSTEM', 'PRIVATE_USER', SCHEMA))
    assert len(calls) == 1 and result.output_text == '{"private":"trip"}'
    assert result.safe_metadata()['usage'] == {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5}
    assert 'private' not in repr(result) and 'PRIVATE' not in caplog.text


@pytest.mark.parametrize('status', ['queued', 'in_progress', 'failed', 'cancelled', 'incomplete'])
def test_non_success_never_exposes_partial_text(status):
    changes = {'output': envelope('completed')['output']}
    if status == 'incomplete':
        changes['incomplete_details'] = {'reason': 'max_output_tokens'}
    result = run(client(lambda r: httpx.Response(200, json=envelope(status, **changes))).retrieve('resp_test123'))
    assert result.status == status and result.output_text is None


def test_refusal_and_cancel_completion_race_discard_output():
    refused = envelope('completed', output=[{'type': 'message', 'role': 'assistant', 'status': 'completed',
                     'content': [{'type': 'refusal', 'refusal': 'PRIVATE_REFUSAL'}]}])
    result = run(client(lambda r: httpx.Response(200, json=refused)).retrieve('resp_test123'))
    assert result.refused and result.output_text is None
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope('completed'))
    result = run(client(handler).cancel('resp_test123'))
    assert result.status == 'completed' and result.output_text is None
    assert calls[0].method == 'POST' and calls[0].url.path.endswith('/resp_test123/cancel')


@pytest.mark.parametrize('changes', [{'id':'resp_wrong'}, {'object':'other'}, {'status':'unknown'},
    {'status': []}, {'output':{}}, {'error':{'message':'secret'}}, {'usage':{'input_tokens':True}},
    {'output':[{'type':'function_call'}]}, {'output':[False]}, {'output':[{'type':'message','role':'user','content':[]}]},
    {'status':'completed', 'output':[]}, {'status':'incomplete'}, {'usage': []}])
def test_malformed_response_fails_closed(changes):
    with pytest.raises(BackgroundError, match='BACKGROUND_INVALID_RESPONSE'):
        run(client(lambda r: httpx.Response(200, json=envelope(**changes))).retrieve('resp_test123'))


@pytest.mark.parametrize('response_id', ['../evil', 'resp_x/y', '', 'x', 'resp_' + 'a'*193, None, 123])
def test_invalid_ids_never_hit_transport(response_id):
    def forbidden(request):
        pytest.fail('Invalid ID hit transport')
    with pytest.raises(BackgroundError, match='BACKGROUND_INVALID_RESPONSE_ID'):
        run(client(forbidden).retrieve(response_id))


@pytest.mark.parametrize('kind', ['timeout', 'network', 'server', 'invalid', 'oversize', 'content_type'])
def test_ambiguous_create_never_retries(kind, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == 'timeout':
            raise httpx.ReadTimeout('PRIVATE_PROVIDER_ERROR')
        if kind == 'network':
            raise httpx.ConnectError('PRIVATE_PROVIDER_ERROR')
        if kind == 'server':
            return httpx.Response(503, text='PRIVATE_PROVIDER_ERROR')
        if kind == 'oversize':
            return httpx.Response(200, content=b'x'*(MAX_ENVELOPE_BYTES+1), headers={'content-type':'application/json'})
        if kind == 'content_type':
            return httpx.Response(200, text='PRIVATE_PROVIDER_ERROR')
        return httpx.Response(200, json=[])
    with pytest.raises(BackgroundError) as caught:
        run(client(handler).create('system', 'user', SCHEMA))
    assert caught.value.ambiguous_create and len(calls) == 1
    assert 'PRIVATE' not in str(caught.value) + caplog.text


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422, 429])
def test_explicit_http_rejection_is_not_ambiguous(status):
    with pytest.raises(BackgroundError) as caught:
        run(client(lambda r: httpx.Response(status, text='PRIVATE')).create('system', 'user', SCHEMA))
    assert not caught.value.ambiguous_create


def test_wall_deadline_binds_slow_transport():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=envelope())
    with pytest.raises(BackgroundError) as caught:
        run(client(slow, request_timeout_seconds=.01).create('system', 'user', SCHEMA))
    assert caught.value.ambiguous_create and caught.value.code == 'BACKGROUND_TRANSPORT_FAILED'


def test_task_cancellation_propagates_without_retry():
    calls = []
    async def cancelled(request):
        calls.append(request)
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run(client(cancelled).create('system', 'user', SCHEMA))
    assert len(calls) == 1


@pytest.mark.parametrize('timeout', [0, -1, 61, True, float('nan'), float('inf')])
def test_timeout_validation(timeout):
    with pytest.raises(BackgroundError, match='BACKGROUND_INVALID_TIMEOUT'):
        client(lambda r: None, request_timeout_seconds=timeout)


def test_invalid_or_oversized_request_prevents_submission():
    def forbidden(request):
        pytest.fail('Invalid payload hit transport')
    for system, schema in [('', SCHEMA), ('x'*MAX_ENVELOPE_BYTES, SCHEMA), ('system', [])]:
        with pytest.raises(BackgroundError, match='BACKGROUND_INVALID_REQUEST'):
            run(client(forbidden).create(system, 'user', schema))
