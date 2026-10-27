"""OpenAI asynchronous HTTPX REST client. Fixed host, no retries or startup calls."""
import json
import logging
import re
import time
import httpx
from .ai_timeout import (AI_READ_TIMEOUT_SECONDS, AI_CONNECT_TIMEOUT_SECONDS,
    AI_WRITE_TIMEOUT_SECONDS, AI_POOL_TIMEOUT_SECONDS, ProviderTransportTimeout, timeout_diagnostic)
from .providers import LLMProvider
from .recommendations import RecommendationError, ProviderRefusal
from .schema_diagnostics import schema_names, missing_properties, TECHNICAL_PARTS

DEFAULT_MODEL = 'gpt-6-luna'
# Only verified production models with strict JSON Schema support.
SUPPORTED_MODELS = {'gpt-6-luna'}
MAX_OUTPUT_TOKENS = 32768
MAX_ENVELOPE_BYTES = 262144
MAX_TEXT_BYTES = 65536
ENDPOINT = 'https://api.openai.com/v1/responses'


HTTP_CATEGORIES = {
    400:'BAD_REQUEST', 401:'AUTHENTICATION', 403:'FORBIDDEN', 404:'NOT_FOUND',
    413:'REQUEST_TOO_LARGE', 422:'UNPROCESSABLE_REQUEST', 429:'RATE_LIMIT',
    500:'UPSTREAM_ERROR', 502:'UPSTREAM_ERROR', 503:'UPSTREAM_ERROR', 504:'UPSTREAM_TIMEOUT',
}
PROVIDER_EVENTS = frozenset({'HTTP_FAILURE','TRANSPORT_TIMEOUT','TRANSPORT_ERROR',
                            'RESPONSE_INVALID','REFUSAL','OUTPUT_TRUNCATED'})


ERROR_CODES = frozenset({'invalid_request_error','invalid_json_schema','invalid_schema','json_validate_failed',
    'unsupported_value','invalid_value','invalid_type','unrecognized_request_argument','context_length_exceeded',
    'model_not_found','rate_limit_exceeded','insufficient_quota','permission_denied','authentication_error'})
# Closed technical vocabulary: provider messages are never returned or logged verbatim.
SCHEMA_TERMS = frozenset("schema json_schema response_format properties required additionalproperties anyof oneof allof enum const type string strings boolean booleans integer integers number numbers object objects array arrays null nullable true false items refs ref defs definition definitions reference references root depth nesting nested maximum minimum maxitems minitems maxlength minlength pattern format max_tokens max_completion_tokens reasoning_effort include_reasoning stream model parameter parameters argument arguments invalid unsupported support supported supports not allowed allow only must should be contain contains containing values value expected found received provided missing extra duplicate invalid_request_error reserved name names has have is are in of for the to and or with at least cannot can does do unknown unrecognized unexpected exceed exceeds exceeded limit limits size compile compilation parse parsing error errors failed failure validate validation length empty nonempty json function functions tool tools strict required_properties".split())
PARAMETER_PARTS = frozenset({'response_format','json_schema','schema','properties','required','additionalProperties',
    'anyOf','oneOf','enum','const','type','items','$ref','$defs','DayCosts','NewMainActivity','status','days',
    'explanation','warnings','vibe','verificationWarning','additionalWarnings','mainSlots','main_1','main_2','main_3','main_4','day_1','day_2','day_3',
    'id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind',
    'max_tokens','max_completion_tokens','reasoning_effort','include_reasoning','stream','model'})


def schema_message_paths(message, allowed_parts=PARAMETER_PARTS):
    """Keep only closed-vocabulary dot/pointer paths, never arbitrary prose."""
    if type(message) is not str or len(message)>8192:
        return []
    paths=[]
    for candidate in re.findall(r"(?:#?/|\$\.)?[$A-Za-z_][$A-Za-z_0-9]*(?:[./][$A-Za-z_][$A-Za-z_0-9]*)+", message):
        parts=re.findall(r'[$A-Za-z_][$A-Za-z_0-9]*', candidate)
        if parts and parts[0]=='$': parts=parts[1:]
        if 1<len(parts)<=16 and all(part in allowed_parts for part in parts):
            if parts not in paths: paths.append(parts)
        if len(paths)==8: break
    return paths


def provider_error_detail(body, response_schema=None):
    """Bounded in-memory extraction; unknown values and all raw prose are discarded."""
    if not isinstance(body,(bytes,bytearray)):
        return {'detail':'UNAVAILABLE','unavailableReason':'INVALID_BODY_TYPE'}
    if len(body)>8192:
        return {'detail':'UNAVAILABLE','unavailableReason':'BODY_TOO_LARGE'}
    if not body:
        return {'detail':'UNAVAILABLE','unavailableReason':'EMPTY_BODY'}
    try:
        data=json.loads(body)
        error=data.get('error') if type(data) is dict else None
        if type(error) is not dict: return {'detail':'UNAVAILABLE','unavailableReason':'ERROR_OBJECT_ABSENT'}
        result={}
        for name in ('code','type'):
            value=error.get(name)
            result[name]=value if type(value) is str and value in ERROR_CODES else 'OTHER_OR_ABSENT'
        names, definitions = schema_names(response_schema) if response_schema is not None else (frozenset(), frozenset())
        allowed_parts = (TECHNICAL_PARTS | names | definitions) if response_schema is not None else PARAMETER_PARTS
        param=error.get('param')
        parts=re.findall(r'[$A-Za-z_][$A-Za-z_0-9]*',param) if type(param) is str and len(param)<=500 else []
        result['parameterPath']=[part if part in allowed_parts else 'UNKNOWN' for part in parts[:16]]
        message=error.get('message')
        result['schemaPaths']=schema_message_paths(message, allowed_parts)
        if response_schema is not None:
            result['missingProperties']=missing_properties(message, names)
        # Each emitted token comes from the closed technical dictionary, not provider prose.
        tokens=re.findall(r'[A-Za-z_][A-Za-z_0-9-]*',message.lower()) if type(message) is str else []
        result['schemaTerms']=[word for word in tokens if word in SCHEMA_TERMS][:96]
        return result
    except (ValueError,TypeError,UnicodeError):
        return {'detail':'UNAVAILABLE','unavailableReason':'INVALID_JSON_OR_ENCODING'}


async def read_error_detail(response, response_schema=None):
    body=bytearray()
    async for chunk in response.aiter_bytes(chunk_size=4096):
        body.extend(chunk)
        if len(body)>8192: return {'detail':'UNAVAILABLE','unavailableReason':'BODY_TOO_LARGE'}
    return provider_error_detail(body, response_schema)


def provider_diagnostic(event, status=None, detail=None):
    """Only fixed event/category names and allowlisted status integers; never bodies."""
    if type(event) is not str or event not in PROVIDER_EVENTS:
        return
    diagnostic={'event':event}
    if event=='HTTP_FAILURE':
        known=type(status) is int and status in HTTP_CATEGORIES
        diagnostic.update(httpStatus=status if known else None,
                          category=HTTP_CATEGORIES[status] if known else 'OTHER_HTTP_STATUS')
        if detail is not None:
            diagnostic['errorDetail']=detail
    logging.getLogger(__name__).warning('AI provider diagnostic: %s',json.dumps(diagnostic))


def invalid_response():
    provider_diagnostic('RESPONSE_INVALID')
    return RecommendationError('AI_INVALID_RESPONSE', 502,
        'The AI response was incomplete or invalid. No generated result was accepted.')


def strict_schema(schema):
    """Project to documented structural subset; retain full local validation.

    The small integer duration domain is represented using supported enum values.
    Other length/numeric constraints remain locally enforced. Never mutate the
    Pydantic schema; the service still enforces all original constraints.
    """
    allowed = {'type', 'title', 'description', 'enum', 'anyOf', '$ref'}
    def project(node, property_name=None):
        if not isinstance(node, dict):
            raise ValueError('Expected schema object')
        result = {key: value for key, value in node.items() if key in allowed}
        if (property_name == 'durationMinutes' and node.get('type') == 'integer'
                and node.get('minimum') == 15 and node.get('maximum') == 240):
            # Do not rely on undocumented minimum/maximum support or prose alone.
            # This is the exact accepted domain, not rounding or repairing output.
            result['enum'] = [value for value in range(15, 241)
                              if 'enum' not in node or value in node['enum']]
        if 'anyOf' in node:
            result['anyOf'] = [project(item) for item in node['anyOf']]
        if '$defs' in node:
            result['$defs'] = {key: project(value) for key,value in node['$defs'].items()}
        if 'items' in node:
            result['items'] = project(node['items'])
        if node.get('type') == 'object':
            properties = node.get('properties', {})
            result['properties'] = {key: project(value, key) for key,value in properties.items()}
            result['required'] = list(properties)
            result['additionalProperties'] = False
        return result
    return project(schema)


class OpenAIProvider(LLMProvider):
    name = 'OpenAI'

    def __init__(self, api_key, model=DEFAULT_MODEL, transport=None, *, reasoning_effort="max"):
        if (not isinstance(api_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', api_key)
                or not isinstance(model, str) or model not in SUPPORTED_MODELS
                or reasoning_effort != "max"):
            raise RecommendationError('AI_NOT_CONFIGURED', 503,
                'OpenAI is not configured correctly. Check the backend-only key and supported model.')
        self._api_key, self.model, self._transport = api_key, model, transport
        self.reasoning_effort = reasoning_effort

    async def generate(self, messages, response_schema):
        if (not isinstance(messages, list) or len(messages) != 2
                or not all(isinstance(m, dict) for m in messages)
                or [m.get('role') for m in messages] != ['system', 'user']
                or not all(isinstance(m.get('content'), str) for m in messages)):
            raise invalid_response()
        try:
            schema = strict_schema(response_schema)
        except (ValueError, TypeError, AttributeError):
            raise invalid_response() from None
        payload = {'model': self.model, 'input': messages, 'stream': False, 'store': False,
            'max_output_tokens': MAX_OUTPUT_TOKENS, 'reasoning': {'effort': self.reasoning_effort},
            'text': {'format': {'type': 'json_schema',
                'name': 'travel_response', 'strict': True, 'schema': schema}}}
        started = time.monotonic()
        stage = 'WAIT_RESPONSE'
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(
                    read=AI_READ_TIMEOUT_SECONDS, connect=AI_CONNECT_TIMEOUT_SECONDS,
                    write=AI_WRITE_TIMEOUT_SECONDS, pool=AI_POOL_TIMEOUT_SECONDS),
                    follow_redirects=False, trust_env=False, transport=self._transport) as client:
                async with client.stream('POST', ENDPOINT,
                        headers={'Authorization': 'Bearer ' + self._api_key,
                                 'Content-Type': 'application/json'}, json=payload) as response:
                    if response.status_code != 200:
                        stage = 'READ_ERROR_BODY'
                        detail = await read_error_detail(response, schema)
                        provider_diagnostic('HTTP_FAILURE', response.status_code, detail)
                        if response.status_code == 400 and detail.get('code') == 'json_validate_failed':
                            raise RecommendationError('AI_SCHEMA_REJECTED', 502,
                                'The AI provider rejected its output against the required schema. No result was accepted and no automatic retry was made.')
                        # Provider error bodies may echo private input. Never expose them.
                        if response.status_code == 429:
                            raise RecommendationError('AI_RATE_LIMITED', 429,
                                'OpenAI quota or rate limit reached. No automatic retry was made.')
                        raise RecommendationError('AI_PROVIDER_FAILED', 502,
                            'OpenAI could not complete this request. Check configuration and availability. No automatic retry was made.')
                    stage = 'READ_RESPONSE_BODY'
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > MAX_ENVELOPE_BYTES:
                            raise invalid_response()
        except httpx.TimeoutException as exc:
            subtype = next((label for kind, label in ((httpx.ReadTimeout, 'READ'),
                (httpx.ConnectTimeout, 'CONNECT'), (httpx.WriteTimeout, 'WRITE'),
                (httpx.PoolTimeout, 'POOL')) if isinstance(exc, kind)), 'OTHER')
            timeout_diagnostic('TRANSPORT_TIMEOUT', subtype, stage, time.monotonic() - started)
            raise ProviderTransportTimeout('OpenAI request timed out') from None
        except httpx.HTTPError:
            provider_diagnostic('TRANSPORT_ERROR')
            raise RecommendationError('AI_PROVIDER_FAILED', 502,
                'OpenAI could not be reached. No automatic retry was made.') from None
        try:
            envelope = json.loads(body)
            if not isinstance(envelope, dict):
                raise ValueError()
            if envelope.get('status') == 'incomplete':
                detail = envelope.get('incomplete_details')
                if isinstance(detail, dict) and detail.get('reason') == 'content_filter':
                    provider_diagnostic('REFUSAL')
                    raise ProviderRefusal()
                provider_diagnostic('OUTPUT_TRUNCATED')
                raise RecommendationError('AI_OUTPUT_TRUNCATED', 502,
                    'The AI response was incomplete. No partial result was accepted and no automatic retry was made.')
            if envelope.get('status') != 'completed' or envelope.get('error'):
                raise ValueError()
            output = envelope.get('output')
            if not isinstance(output, list) or not output:
                raise ValueError()
            messages = []
            for item in output:
                if not isinstance(item, dict):
                    raise ValueError()
                if item.get('type') == 'reasoning':
                    continue  # Never return, store or log model reasoning.
                if item.get('type') != 'message':
                    raise ValueError()  # No tools or external actions were requested.
                messages.append(item)
            if len(messages) != 1:
                raise ValueError()
            message = messages[0]
            if message.get('role') != 'assistant' or message.get('status') != 'completed':
                raise ValueError()
            content = message.get('content')
            if not isinstance(content, list) or not content:
                raise ValueError()
            if any(isinstance(part, dict) and part.get('type') == 'refusal' for part in content):
                provider_diagnostic('REFUSAL')
                raise ProviderRefusal()
            if len(content) != 1 or not isinstance(content[0], dict) or content[0].get('type') != 'output_text':
                raise ValueError()
            text = content[0].get('text')
            if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
                raise ValueError()
            return text  # Strict JSON + domain validation remains mandatory in service.
        except ProviderRefusal:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise invalid_response() from None
