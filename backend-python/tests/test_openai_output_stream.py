"""Offline fake transport only; no environment credentials or paid requests."""
import asyncio
import json

import httpx
import pytest

from app.openai_background import BackgroundActivation, BackgroundError
from app.openai_output_stream import (OpenAIOutputStreamClient, OutputStreamError,
    MAX_STREAM_TEXT_BYTES, MAX_STREAM_BYTES, MAX_ENVELOPE_BYTES)

SCHEMA = {'type':'object','properties':{},'required':[],'additionalProperties':False}
APPROVED = BackgroundActivation(True, True)
RID = 'resp_stream_fixture'


def event(kind, seq, **fields):
    return {'type':kind,'sequence_number':seq,**fields}


def created(seq=0, rid=RID):
    return event('response.created',seq,response={'id':rid,'status':'queued'})


def delta(seq=1, text='private preview'):
    return event('response.output_text.delta',seq,delta=text,item_id='msg_fixture',output_index=0,content_index=0)


def terminal(seq=2, status='completed', rid=RID):
    return event('response.'+status,seq,response={'id':rid,'status':status,'output':[{'type':'reasoning','summary':'NEVER_EXPOSE'}]})


def wire(*events, newline='\n'):
    return ''.join('data: '+json.dumps(e,ensure_ascii=False)+newline+newline for e in events).encode()


class Bytes(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None): self.chunks,self.error,self.closed=chunks,error,False
    async def __aiter__(self):
        for chunk in self.chunks: yield chunk
        if self.error: raise self.error
    async def aclose(self): self.closed=True


def provider(handler, **kwargs):
    return OpenAIOutputStreamClient('fake-stream-test-key',transport=httpx.MockTransport(handler),
        activation=kwargs.pop('activation',APPROVED),**kwargs)


def reply(data):
    return httpx.Response(200,headers={'content-type':'text/event-stream; charset=utf-8'},stream=Bytes([data]))


async def collect(stream): return [update async for update in stream]


def test_create_wire_high_early_id_and_only_output_text(caplog):
    requests=[]
    def handler(request):
        requests.append(request);payload=json.loads(request.content)
        assert payload['stream'] is True and payload['background'] is True and payload['store'] is False
        assert payload['model']=='gpt-6-luna' and payload['reasoning']=={'effort':'high'}
        assert payload['text']['format']['strict'] is True
        assert 'tools' not in payload and 'include' not in payload
        return reply(wire(created(),event('response.reasoning_text.delta',1,delta='NEVER_EXPOSE'),
            event('keepalive',99999,source='NEVER_EXPOSE'),delta(2,'private preview'),terminal(3)))
    values=asyncio.run(collect(provider(handler).create_stream('system','private user',SCHEMA)))
    assert [v.kind for v in values]==['created','checkpoint','text_delta','terminal']
    assert [v.sequence_number for v in values]==[0,1,2,3]
    assert values[0].response_id==RID and values[2].text_delta=='private preview'
    assert 'NEVER_EXPOSE' not in repr(values)+caplog.text and 'private preview' not in repr(values)+caplog.text
    assert len(requests)==1


def test_split_utf8_crlf_multiline_and_sse_comments():
    raw=b': heartbeat\r\n\r\n'+wire(created(),delta(text='Kyoto 京都'),terminal(),newline='\r\n')
    stream=Bytes([raw[i:i+1] for i in range(len(raw))])
    values=asyncio.run(collect(provider(lambda _:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=stream)).create_stream('s','u',SCHEMA)))
    assert values[1].text_delta=='Kyoto 京都' and stream.closed


def test_resume_get_cursor_skips_only_previously_committed_events_and_never_creates():
    calls=[]
    def handler(request):
        calls.append(request);assert request.method=='GET'
        assert str(request.url)==f'https://api.openai.com/v1/responses/{RID}?stream=true&starting_after=4'
        return reply(wire(delta(3,'old'),event('keepalive',1),delta(5,'new'),terminal(6)))
    values=asyncio.run(collect(provider(handler).resume_stream(RID,starting_after=4,prior_text_bytes=3)))
    assert [v.sequence_number for v in values]==[5,6] and values[0].text_delta=='new' and len(calls)==1


@pytest.mark.parametrize('events',[ [created(False)], [created(),delta(0)], [created(),delta(2),delta(1)],
    [created(),terminal(rid='resp_different')], [created(),delta(text=None)], [created(),{'type':'response.output_text.delta','sequence_number':1,'delta':'x','item_id':'msg_ok','output_index':False,'content_index':0}] ])
def test_invalid_sequences_identity_and_delta_shapes_fail_closed(events):
    with pytest.raises(OutputStreamError) as caught:
        asyncio.run(collect(provider(lambda _:reply(wire(*events))).create_stream('s','u',SCHEMA)))
    assert caught.value.code=='STREAM_INVALID_RESPONSE'


@pytest.mark.parametrize('before_id',[True,False])
def test_interrupted_connection_preserves_identity_and_never_reposts(before_id):
    calls=[];raw=b'' if before_id else wire(created(),delta())
    def handler(request):calls.append(request);return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes([raw],httpx.ReadError('PRIVATE_ERROR')))
    with pytest.raises(OutputStreamError) as caught:
        asyncio.run(collect(provider(handler).create_stream('s','u',SCHEMA)))
    error=caught.value
    assert error.ambiguous_create is before_id and error.response_id==(None if before_id else RID)
    assert error.last_sequence==(-1 if before_id else 1)
    assert 'PRIVATE_ERROR' not in str(error)+repr(error.safe_metadata()) and len(calls)==1


def test_clean_eof_without_terminal_is_not_success_and_keeps_known_response():
    with pytest.raises(OutputStreamError) as caught:
        asyncio.run(collect(provider(lambda _:reply(wire(created()))).create_stream('s','u',SCHEMA)))
    assert caught.value.code=='STREAM_INTERRUPTED' and caught.value.response_id==RID
    assert caught.value.ambiguous_create is False


@pytest.mark.parametrize('status,ambiguous',[(400,False),(401,False),(429,False),(500,True),(302,True)])
def test_http_failures_are_bounded_without_error_body_or_retry(status,ambiguous):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,content=b'PRIVATE_BODY')
    with pytest.raises(OutputStreamError) as caught:
        asyncio.run(collect(provider(handler).create_stream('s','u',SCHEMA)))
    assert caught.value.ambiguous_create is ambiguous and len(calls)==1
    assert 'PRIVATE_BODY' not in str(caught.value)


@pytest.mark.parametrize('raw',[b'data: {"type":"x","type":"y"}\n\n',b'data: \xff\n\n',b'data: [DONE]\n\n',b'data: {"type":',b'data: '+b'x'*(MAX_ENVELOPE_BYTES+1),b'x'*(MAX_STREAM_BYTES+1)])
def test_bounded_parser_rejects_duplicate_keys_utf8_truncation_and_oversize(raw):
    with pytest.raises(OutputStreamError):
        asyncio.run(collect(provider(lambda _:reply(raw)).create_stream('s','u',SCHEMA)))


def test_128k_output_bound_including_durable_prior_bytes():
    values=asyncio.run(collect(provider(lambda _:reply(wire(created(),delta(text='x'*MAX_STREAM_TEXT_BYTES),terminal()))).create_stream('s','u',SCHEMA)))
    assert len(values[1].text_delta)==MAX_STREAM_TEXT_BYTES
    with pytest.raises(OutputStreamError):
        asyncio.run(collect(provider(lambda _:reply(wire(delta(8,'xx'),terminal(9)))).resume_stream(RID,starting_after=7,prior_text_bytes=MAX_STREAM_TEXT_BYTES-1)))


@pytest.mark.parametrize('cursor',[-2,True,1.2,2**53])
def test_invalid_resume_cursor_does_not_touch_transport(cursor):
    def forbidden(_):pytest.fail('invalid input reached transport')
    with pytest.raises(BackgroundError):asyncio.run(collect(provider(forbidden).resume_stream(RID,starting_after=cursor)))


def test_disabled_activation_prevents_all_requests():
    def forbidden(_):pytest.fail('disabled adapter reached transport')
    p=provider(forbidden,activation=BackgroundActivation())
    for stream in (p.create_stream('s','u',SCHEMA),p.resume_stream(RID)):
        with pytest.raises(BackgroundError,match='BACKGROUND_NOT_APPROVED'):asyncio.run(collect(stream))


def test_response_id_is_yielded_before_more_network_and_consumer_cancel_closes_stream():
    class Wait(Bytes):
        async def __aiter__(self):
            yield wire(created())
            await asyncio.sleep(100)
    stream=Wait([])
    async def check():
        p=provider(lambda _:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=stream))
        result=p.create_stream('s','u',SCHEMA)
        first=await asyncio.wait_for(anext(result),.5)
        assert first.kind=='created' and first.response_id==RID
        await result.aclose();assert stream.closed
    asyncio.run(check())


def test_network_timeout_is_resumable_without_cancelling_consumer_persistence():
    class Wait(Bytes):
        async def __aiter__(self):
            yield wire(created())
            await asyncio.sleep(100)
    async def check():
        stream=Wait([])
        p=provider(lambda _:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=stream),request_timeout_seconds=.01)
        result=p.create_stream('s','u',SCHEMA)
        assert (await anext(result)).response_id==RID
        await asyncio.sleep(.03)  # consumer persistence must not receive a leaked timer cancellation
        with pytest.raises(OutputStreamError) as caught:await anext(result)
        assert caught.value.code=='STREAM_TIMEOUT' and caught.value.response_id==RID and not caught.value.ambiguous_create
        await result.aclose();assert stream.closed
    asyncio.run(check())

def test_cursor_only_events_drop_sources_error_text_refusals_and_annotations():
    values=asyncio.run(collect(provider(lambda _:reply(wire(created(),
        event('response.output_item.added',1,item={'type':'web_search_call','sources':['PRIVATE_SOURCE']}),
        event('response.refusal.delta',2,delta='PRIVATE_REFUSAL'),
        event('response.output_text.annotation.added',3,annotation={'url':'PRIVATE_SOURCE'}),
        terminal(4,'failed')))).create_stream('s','u',SCHEMA)))
    assert all(v.text_delta is None for v in values)
    assert 'PRIVATE' not in repr(values)
    assert values[-1].status=='failed'


def test_metadata_is_allowlisted_even_for_foreign_error_instances():
    value=OutputStreamError('PRIVATE_ERROR',last_sequence='PRIVATE_CURSOR',response_id='PRIVATE_ID')
    assert 'PRIVATE' not in repr(value.safe_metadata())


def test_same_connection_duplicate_is_not_silently_skipped_as_durable():
    with pytest.raises(OutputStreamError) as caught:
        asyncio.run(collect(provider(lambda _:reply(wire(delta(5,'one'),delta(5,'changed')))).resume_stream(RID,starting_after=4)))
    assert caught.value.last_sequence==5 and caught.value.response_id==RID


def test_resume_old_cursor_event_still_cannot_switch_response_identity():
    with pytest.raises(OutputStreamError):
        asyncio.run(collect(provider(lambda _:reply(wire(created(2,'resp_wrong'),terminal(6)))).resume_stream(RID,starting_after=4)))
