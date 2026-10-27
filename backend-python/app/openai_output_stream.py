"""Isolated, opt-in Responses background output stream adapter (not runtime-wired).

Official docs verified 2026-10-27:
https://developers.openai.com/api/docs/guides/background
https://developers.openai.com/api/reference/resources/responses/streaming-events

Each call uses one HTTP request. A dropped connection never creates a replacement.
The caller must persist create intent before POST, then atomically commit each
cursor with its private UNVALIDATED preview before requesting another event.
Resume only from that durable cursor, not an exception's observed last_sequence.
Keepalives are connection counters, not stored-event cursors. A terminal event is
not an accepted itinerary: retrieve and run the existing domain validation later.
"""
import asyncio
from dataclasses import dataclass, field
from contextlib import aclosing
import json
import re
import time

import httpx

from .openai import ENDPOINT, MAX_ENVELOPE_BYTES, MAX_OUTPUT_TOKENS, strict_schema
from .openai_background import OpenAIBackgroundClient, BackgroundError, _response_id

MAX_STREAM_BYTES = 2 * 1024 * 1024
MAX_STREAM_EVENTS = 20000
MAX_STREAM_TEXT_BYTES = 131072
MAX_SEQUENCE = 2**53 - 1
_STREAM_ERRORS = frozenset({'STREAM_HTTP_FAILED','STREAM_INVALID_RESPONSE','STREAM_INTERRUPTED',
                            'STREAM_TIMEOUT','STREAM_TRANSPORT_FAILED'})
_TERMINAL = {'response.completed': 'completed', 'response.failed': 'failed',
             'response.incomplete': 'incomplete', 'response.cancelled': 'cancelled'}


@dataclass(frozen=True)
class OutputStreamUpdate:
    response_id: str
    sequence_number: int
    kind: str
    text_delta: str | None = field(default=None, repr=False)
    status: str | None = None
    item_id: str | None = None
    output_index: int | None = None
    content_index: int | None = None


class OutputStreamError(BackgroundError):
    def __init__(self, code, *, response_id=None, last_sequence=-1,
                 creating=False, http_status=None, ambiguous_create=None):
        super().__init__(code, ambiguous_create=(creating and response_id is None)
                         if ambiguous_create is None else ambiguous_create,
                         phase='create' if creating else 'retrieve', http_status=http_status)
        self.response_id = response_id
        self.last_sequence = last_sequence

    def safe_metadata(self):
        return {'code': self.code if type(self.code) is str and self.code in _STREAM_ERRORS else 'STREAM_UNCLASSIFIED',
                'phase': self.phase, 'ambiguous_create': self.ambiguous_create,
                'has_response_id': self.response_id is not None,
                'last_sequence': self.last_sequence if type(self.last_sequence) is int and -1 <= self.last_sequence <= MAX_SEQUENCE else None}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


async def _sse_events(chunks):
    """Bound frames before JSON parsing; CRLF and split UTF-8 are accepted."""
    pending = bytearray()
    fields = []
    frame_bytes = total_bytes = events = 0
    async for chunk in chunks:
        total_bytes += len(chunk)
        if total_bytes > MAX_STREAM_BYTES:
            raise ValueError('stream_bound')
        pending.extend(chunk)
        offset = 0
        while (end := pending.find(b'\n', offset)) >= 0:
            raw = pending[offset:end]
            offset = end + 1
            frame_bytes += len(raw) + 1
            if frame_bytes > MAX_ENVELOPE_BYTES:
                raise ValueError('frame_bound')
            line = bytes(raw).removesuffix(b'\r').decode('utf-8', errors='strict')
            if not line:
                if fields:
                    events += 1
                    if events > MAX_STREAM_EVENTS:
                        raise ValueError('event_bound')
                    data = '\n'.join(fields)
                    fields = []
                    # Responses uses explicit terminal events, not a bare DONE marker.
                    if data == '[DONE]':
                        raise ValueError('missing_terminal')
                    yield json.loads(data, object_pairs_hook=_unique,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                frame_bytes = 0
            elif line.startswith('data:'):
                value = line[5:]
                fields.append(value[1:] if value.startswith(' ') else value)
            # Comments/event/id/retry fields never control the durable cursor.
        del pending[:offset]
        if len(pending) + frame_bytes > MAX_ENVELOPE_BYTES:
            raise ValueError('frame_bound')
    if pending or fields:
        raise ValueError('truncated_frame')


async def _timed_chunks(response, seconds):
    # A timeout context must not span yield: that could cancel consumer persistence.
    deadline = time.monotonic() + seconds
    iterator = response.aiter_bytes().__aiter__()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield chunk


class OpenAIOutputStreamClient(OpenAIBackgroundClient):
    """Real fake-transport-testable adapter; production selection remains disabled."""

    async def create_stream(self, system_prompt, user_prompt, schema):
        self._activation.require()
        if any(type(p) is not str or not p.strip() for p in (system_prompt, user_prompt)):
            raise BackgroundError('BACKGROUND_INVALID_REQUEST')
        try:
            payload = {'model': self.model, 'service_tier': 'default', 'background': True,
                'store': False, 'stream': True, 'reasoning': {'effort': self.reasoning_effort},
                'max_output_tokens': MAX_OUTPUT_TOKENS,
                'input': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
                'text': {'format': {'type': 'json_schema', 'name': 'travel_response',
                                   'strict': True, 'schema': strict_schema(schema)}}}
            if len(json.dumps(payload, allow_nan=False).encode()) > MAX_ENVELOPE_BYTES:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise BackgroundError('BACKGROUND_INVALID_REQUEST') from None
        async with aclosing(self._output_stream('POST', ENDPOINT, payload=payload, creating=True)) as updates:
            async for update in updates:
                yield update

    async def resume_stream(self, response_id, *, starting_after=-1, prior_text_bytes=0):
        self._activation.require()
        rid = _response_id(response_id)
        if type(starting_after) is not int or not -1 <= starting_after <= MAX_SEQUENCE:
            raise BackgroundError('BACKGROUND_INVALID_REQUEST')
        if type(prior_text_bytes) is not int or not 0 <= prior_text_bytes <= MAX_STREAM_TEXT_BYTES:
            raise BackgroundError('BACKGROUND_INVALID_REQUEST')
        params = {'stream': 'true'}
        if starting_after >= 0:
            params['starting_after'] = str(starting_after)
        async with aclosing(self._output_stream('GET', ENDPOINT + '/' + rid,
                params=params, expected_id=rid, starting_after=starting_after, prior_text_bytes=prior_text_bytes)) as updates:
            async for update in updates:
                yield update

    async def _output_stream(self, method, url, *, payload=None, params=None,
                             expected_id=None, starting_after=-1, creating=False, prior_text_bytes=0):
        rid, last, text_bytes = expected_id, starting_after, prior_text_bytes
        def fail(code, **options):
            return OutputStreamError(code, response_id=rid, last_sequence=last,
                                     creating=creating, **options)
        try:
            async with httpx.AsyncClient(transport=self._transport, trust_env=False,
                    follow_redirects=False, timeout=httpx.Timeout(self._timeout)) as client:
                async with client.stream(method, url, json=payload, params=params,
                        headers={'Authorization': 'Bearer ' + self._api_key,
                                 'Content-Type': 'application/json', 'Accept': 'text/event-stream'}) as response:
                    if response.status_code != 200:
                        raise fail('STREAM_HTTP_FAILED', http_status=response.status_code,
                                   ambiguous_create=creating and response.status_code not in {400,401,403,404,413,422,429})
                    if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'text/event-stream':
                        raise fail('STREAM_INVALID_RESPONSE')
                    async for event in _sse_events(_timed_chunks(response, self._timeout)):
                        if type(event) is not dict or type(event.get('type')) is not str:
                            raise ValueError()
                        kind = event['type']
                        if kind == 'keepalive':
                            continue  # Do not persist heartbeat sequence_number values.
                        seq = event.get('sequence_number')
                        if type(seq) is not int or not 0 <= seq <= MAX_SEQUENCE:
                            raise ValueError()
                        envelope = event.get('response')
                        if envelope is not None:
                            if type(envelope) is not dict:
                                raise ValueError()
                            candidate = _response_id(envelope.get('id'))
                            if rid is not None and candidate != rid:
                                raise ValueError()
                            rid = candidate
                        if rid is None:
                            raise ValueError()
                        if seq <= starting_after:
                            continue  # Already durably committed before this connection.
                        if seq <= last:
                            raise ValueError()
                        status = None
                        if kind in _TERMINAL:
                            status = _TERMINAL[kind]
                            if not envelope or envelope.get('status') != status:
                                raise ValueError()
                            last = seq
                            yield OutputStreamUpdate(rid, seq, 'terminal', status=status)
                            return
                        if kind == 'response.output_text.delta':
                            text = event.get('delta')
                            item = event.get('item_id')
                            oi, ci = event.get('output_index'), event.get('content_index')
                            if (type(text) is not str or type(item) is not str
                                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', item)
                                    or any(type(index) is not int or not 0 <= index <= 10000 for index in (oi,ci))):
                                raise ValueError()
                            text_bytes += len(text.encode('utf-8'))
                            if text_bytes > MAX_STREAM_TEXT_BYTES:
                                raise ValueError()
                            last = seq
                            yield OutputStreamUpdate(rid, seq, 'text_delta', text, None, item, oi, ci)
                        else:
                            last = seq
                            # No refusal text, tool arguments/results, annotations, logprobs,
                            # reasoning summaries, encrypted reasoning, or raw payload escapes.
                            yield OutputStreamUpdate(rid, seq,
                                'created' if kind == 'response.created' else 'checkpoint')
                    raise fail('STREAM_INTERRUPTED')
        except OutputStreamError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise fail('STREAM_TIMEOUT') from None
        except httpx.HTTPError:
            raise fail('STREAM_TRANSPORT_FAILED') from None
        except (ValueError, TypeError, UnicodeError, RecursionError, BackgroundError):
            raise fail('STREAM_INVALID_RESPONSE') from None
