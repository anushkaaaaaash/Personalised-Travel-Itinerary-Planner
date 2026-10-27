"""Opt-in background Responses adapter; no configuration discovery or persistence.

Background store=False still retains provider response data for roughly 10 minutes.
Activation needs a separate, explicit retention approval; it is NOT granted by
constructing this class. Docs checked 2026-10-27:
https://developers.openai.com/api/docs/guides/background
https://developers.openai.com/api/docs/models/gpt-6-luna

The owner-scoped worker must durably record submission intent before create,
never resubmit an ambiguous create, and reject late completion after cancellation
or expiry. Output is private, unvalidated input for the existing domain service,
not an accepted itinerary. This module never logs provider bodies or exceptions.
"""
import asyncio
from dataclasses import dataclass, field
import json
import math
import re

import httpx

from .openai import ENDPOINT, MAX_ENVELOPE_BYTES, MAX_OUTPUT_TOKENS, MAX_TEXT_BYTES, strict_schema

STATUSES = frozenset({'queued', 'in_progress', 'completed', 'failed', 'incomplete', 'cancelled'})
TERMINAL_STATUSES = STATUSES - {'queued', 'in_progress'}
DIAGNOSTIC_CODES = frozenset({'BACKGROUND_NOT_APPROVED','BACKGROUND_INVALID_RESPONSE_ID',
    'BACKGROUND_INVALID_RESPONSE','BACKGROUND_NOT_CONFIGURED','BACKGROUND_INVALID_TIMEOUT',
    'BACKGROUND_INVALID_REQUEST','BACKGROUND_HTTP_FAILED','BACKGROUND_TRANSPORT_FAILED'})
PARSE_REASONS = frozenset({'json','envelope','identity','status','usage','output_shape','message_phase','content','text_limit','final_text','incomplete_reason','content_type','envelope_limit','research_envelope','research_calls','research_sources','research_citations','research_pack','citation_shape','citation_span','citation_title','citation_url','citation_unconsulted','citation_missing','citation_source_count'})
DIAGNOSTIC_PHASES = frozenset({'create','retrieve','cancel'})


def background_error_metadata(error, phase):
    """Only fixed allowlisted metadata; never exception strings or provider bodies."""
    metadata = {'phase': phase if type(phase) is str and phase in DIAGNOSTIC_PHASES else 'unknown',
        'code': 'BACKGROUND_UNCLASSIFIED', 'ambiguous_create': phase == 'create'}
    if isinstance(error, BackgroundError):
        code = error.code
        if type(code) is str and code in DIAGNOSTIC_CODES:
            metadata['code'] = code
        if type(error.ambiguous_create) is bool:
            metadata['ambiguous_create'] = error.ambiguous_create
        if error.confirmed_terminal is True:
            metadata['confirmed_terminal'] = True
        status = error.http_status
        if type(status) is int and 100 <= status <= 599:
            metadata['http_status'] = status
        reason = error.parse_reason
        if type(reason) is str and reason in PARSE_REASONS:
            metadata['parse_reason'] = reason
        kind = error.transport_kind
        if type(kind) is str and kind in {'timeout','transport'}:
            metadata['transport'] = kind
    return metadata


class BackgroundError(Exception):
    def __init__(self, code, *, ambiguous_create=False, phase=None, http_status=None, transport_kind=None, parse_reason=None, confirmed_terminal=False):
        super().__init__(code)
        self.confirmed_terminal = confirmed_terminal is True
        self.parse_reason = parse_reason
        self.code = code
        self.ambiguous_create = ambiguous_create
        self.phase, self.http_status, self.transport_kind = phase, http_status, transport_kind

    def safe_metadata(self):
        return background_error_metadata(self, self.phase)


@dataclass(frozen=True)
class BackgroundActivation:
    enabled: bool = False
    temporary_retention_approved: bool = False

    def require(self):
        if self.enabled is not True or self.temporary_retention_approved is not True:
            raise BackgroundError('BACKGROUND_NOT_APPROVED')


@dataclass(frozen=True)
class BackgroundResponse:
    response_id: str
    status: str
    output_text: str | None = field(default=None, repr=False)
    usage: dict = field(default_factory=dict)
    refused: bool = False

    def safe_metadata(self):
        return {'response_id': self.response_id, 'status': self.status,
                'usage': dict(self.usage), 'refused': self.refused}


def _response_id(value):
    if type(value) is not str or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}', value):
        raise BackgroundError('BACKGROUND_INVALID_RESPONSE_ID')
    return value


def _answer_messages(output):
    """Official output-message phase: commentary is never final plan content.

    https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_output_message.py
    Legacy unphased output remains subject to the existing single-text rule.
    """
    messages = [item for item in output if type(item) is dict and item.get('type') == 'message']
    phases = [item.get('phase') for item in messages]
    if any(type(phase) is not str or phase not in {'commentary','final_answer'} for phase in phases if phase is not None):
        raise ValueError()
    if any(phase is not None for phase in phases):
        finals = [item for item in messages if item.get('phase') == 'final_answer']
        if None in phases or len(finals) > 1:
            raise ValueError()
        return finals
    return messages


def _parse(body, expected_id=None, *, discard_output=False):
    reason = 'json'
    try:
        data = json.loads(body)
        reason = 'envelope'
        if type(data) is not dict or data.get('object') != 'response':
            raise ValueError()
        reason = 'identity'
        rid = _response_id(data.get('id'))
        status = data.get('status')
        if expected_id is not None and rid != expected_id:
            raise ValueError()
        reason = 'status'
        if type(status) is not str or status not in STATUSES:
            raise ValueError()
        error = data.get('error')
        if error is not None and (type(error) is not dict or status != 'failed'):
            raise ValueError()
        reason = 'usage'
        usage = data.get('usage')
        safe_usage = {}
        if usage is not None:
            if type(usage) is not dict:
                raise ValueError()
            for key in ('input_tokens', 'output_tokens', 'total_tokens'):
                value = usage.get(key)
                if value is not None:
                    if type(value) is not int or not 0 <= value <= 10**9:
                        raise ValueError()
                    safe_usage[key] = value
        reason = 'output_shape'
        output = data.get('output', [])
        if type(output) is not list:
            raise ValueError()
        reason = 'message_phase'
        answers = _answer_messages(output)
        reason = 'content'
        texts, all_texts, refused = [], [], False
        for item in output:
            if type(item) is not dict:
                raise ValueError()
            if item.get('type') == 'reasoning':
                continue  # Never expose summaries, encrypted reasoning or raw reasoning.
            if (item.get('type') != 'message' or item.get('role') != 'assistant'
                    or type(item.get('content')) is not list):
                raise ValueError()
            if status == 'completed' and item.get('status') != 'completed':
                raise ValueError()
            for part in item['content']:
                if type(part) is not dict:
                    raise ValueError()
                if part.get('type') == 'refusal':
                    refused = True
                elif part.get('type') == 'output_text' and type(part.get('text')) is str:
                    all_texts.append(part['text'])
                    if any(item is answer for answer in answers):
                        texts.append(part['text'])
                else:
                    raise ValueError()
        text = ''.join(texts)
        reason = 'text_limit'
        if sum(len(value.encode('utf-8')) for value in all_texts) > MAX_TEXT_BYTES:
            raise ValueError()
        reason = 'final_text'
        if status == 'completed' and not refused and (len(texts) != 1 or not text.strip()):
            raise ValueError()
        if status == 'incomplete':
            reason = 'incomplete_reason'
            details = data.get('incomplete_details')
            if type(details) is not dict or details.get('reason') not in {'max_output_tokens', 'max_messages', 'content_filter', 'steered', None}:
                raise ValueError()
            refused = refused or details.get('reason') == 'content_filter'
        return BackgroundResponse(rid, status,
            text if status == 'completed' and not refused and not discard_output else None,
            safe_usage, refused)
    except (ValueError, TypeError, UnicodeError, RecursionError, BackgroundError):
        raise BackgroundError('BACKGROUND_INVALID_RESPONSE', parse_reason=reason) from None


class OpenAIBackgroundClient:
    """Explicit credentials only. Every method makes at most one HTTP request.

    Caller owns authentication/response-ID binding and durable lifecycle state.
    cancel() discards output even if provider completion won the cancellation race.
    """
    model = 'gpt-6-luna'
    # User-selected effort; structured output and local acceptance gates remain mandatory.
    reasoning_effort = 'high'

    def __init__(self, api_key, *, activation=None, transport=None, request_timeout_seconds=30):
        if type(api_key) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', api_key):
            raise BackgroundError('BACKGROUND_NOT_CONFIGURED')
        if (type(request_timeout_seconds) not in (int, float)
                or not math.isfinite(request_timeout_seconds) or not 0 < request_timeout_seconds <= 60):
            raise BackgroundError('BACKGROUND_INVALID_TIMEOUT')
        if activation is not None and type(activation) is not BackgroundActivation:
            raise BackgroundError('BACKGROUND_NOT_APPROVED')
        self._activation = activation or BackgroundActivation()
        self._api_key, self._transport = api_key, transport
        self._timeout = request_timeout_seconds

    async def create(self, system_prompt, user_prompt, schema):
        self._activation.require()
        if any(type(p) is not str or not p.strip() for p in (system_prompt, user_prompt)):
            raise BackgroundError('BACKGROUND_INVALID_REQUEST')
        try:
            payload = {'model': self.model, 'service_tier': 'default', 'background': True, 'store': False, 'stream': False,
                'reasoning': {'effort': self.reasoning_effort}, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                'input': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
                'text': {'format': {'type': 'json_schema', 'name': 'travel_response',
                                    'strict': True, 'schema': strict_schema(schema)}}}
            if len(json.dumps(payload, allow_nan=False).encode('utf-8')) > MAX_ENVELOPE_BYTES:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise BackgroundError('BACKGROUND_INVALID_REQUEST') from None
        return await self._request('POST', ENDPOINT, payload=payload, creating=True)

    async def retrieve(self, response_id):
        self._activation.require()
        rid = _response_id(response_id)
        return await self._request('GET', ENDPOINT + '/' + rid, expected_id=rid)

    async def cancel(self, response_id):
        self._activation.require()
        rid = _response_id(response_id)
        return await self._request('POST', ENDPOINT + '/' + rid + '/cancel', expected_id=rid,
                                   discard_output=True)

    async def _request(self, method, url, *, payload=None, expected_id=None, creating=False, discard_output=False):
        # No SDK retries, redirects, environment proxies, or unbounded streaming.
        phase = 'create' if creating else ('cancel' if discard_output else 'retrieve')
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(transport=self._transport, trust_env=False,
                        follow_redirects=False, timeout=httpx.Timeout(self._timeout)) as client:
                    async with client.stream(method, url, json=payload,
                            headers={'Authorization': 'Bearer ' + self._api_key,
                                     'Content-Type': 'application/json'}) as response:
                        if response.status_code != 200:
                            # Never parse or log error bodies; 5xx create acceptance is uncertain.
                            raise BackgroundError('BACKGROUND_HTTP_FAILED',
                                ambiguous_create=creating and response.status_code not in {400, 401, 403, 404, 413, 422, 429},
                                phase=phase, http_status=response.status_code)
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise BackgroundError('BACKGROUND_INVALID_RESPONSE', ambiguous_create=creating, phase=phase, http_status=200, parse_reason='content_type')
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=16384):
                            body.extend(chunk)
                            if len(body) > MAX_ENVELOPE_BYTES:
                                raise BackgroundError('BACKGROUND_INVALID_RESPONSE', ambiguous_create=creating, phase=phase, http_status=200, parse_reason='envelope_limit')
                try:
                    return _parse(body, expected_id, discard_output=discard_output)
                except BackgroundError as error:
                    raise BackgroundError('BACKGROUND_INVALID_RESPONSE', ambiguous_create=creating, phase=phase, http_status=200, parse_reason=error.parse_reason) from None
        except (httpx.TimeoutException, TimeoutError):
            raise BackgroundError('BACKGROUND_TRANSPORT_FAILED', ambiguous_create=creating, phase=phase, transport_kind='timeout') from None
        except httpx.HTTPError:
            raise BackgroundError('BACKGROUND_TRANSPORT_FAILED', ambiguous_create=creating, phase=phase, transport_kind='transport') from None
