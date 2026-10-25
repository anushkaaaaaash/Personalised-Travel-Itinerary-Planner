"""Groq asynchronous HTTPX REST client. Fixed host, no retries or startup calls."""
import json
import logging
import re
import httpx
from .providers import LLMProvider
from .recommendations import RecommendationError, ProviderRefusal

DEFAULT_MODEL = 'openai/gpt-oss-20b'
# Only verified production models with strict JSON Schema support.
SUPPORTED_MODELS = {'openai/gpt-oss-20b', 'openai/gpt-oss-120b'}
MAX_ENVELOPE_BYTES = 262144
MAX_TEXT_BYTES = 65536
ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'


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
    'explanation','warnings','vibe','verificationWarning','mainSlots','main_1','main_2','main_3','main_4','day_1','day_2','day_3',
    'id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind',
    'max_tokens','max_completion_tokens','reasoning_effort','include_reasoning','stream','model'})


def schema_message_paths(message):
    """Keep only closed-vocabulary dot/pointer paths, never arbitrary prose."""
    if type(message) is not str or len(message)>8192:
        return []
    paths=[]
    for candidate in re.findall(r"(?:#?/|\$\.)?[$A-Za-z_][$A-Za-z_0-9]*(?:[./][$A-Za-z_][$A-Za-z_0-9]*)+", message):
        parts=re.findall(r'[$A-Za-z_][$A-Za-z_0-9]*', candidate)
        if parts and parts[0]=='$': parts=parts[1:]
        if 1<len(parts)<=16 and all(part in PARAMETER_PARTS for part in parts):
            if parts not in paths: paths.append(parts)
        if len(paths)==8: break
    return paths


def provider_error_detail(body):
    """Bounded in-memory extraction; unknown values and all raw prose are discarded."""
    if not isinstance(body,(bytes,bytearray)) or len(body)>8192:
        return {'detail':'UNAVAILABLE'}
    try:
        data=json.loads(body)
        error=data.get('error') if type(data) is dict else None
        if type(error) is not dict: return {'detail':'UNAVAILABLE'}
        result={}
        for name in ('code','type'):
            value=error.get(name)
            result[name]=value if type(value) is str and value in ERROR_CODES else 'OTHER_OR_ABSENT'
        param=error.get('param')
        parts=re.findall(r'[$A-Za-z_][$A-Za-z_0-9]*',param) if type(param) is str and len(param)<=500 else []
        result['parameterPath']=[part if part in PARAMETER_PARTS else 'UNKNOWN' for part in parts[:16]]
        message=error.get('message')
        result['schemaPaths']=schema_message_paths(message)
        # Each emitted token comes from the closed technical dictionary, not provider prose.
        tokens=re.findall(r'[A-Za-z_][A-Za-z_0-9-]*',message.lower()) if type(message) is str else []
        result['schemaTerms']=[word for word in tokens if word in SCHEMA_TERMS][:96]
        return result
    except (ValueError,TypeError,UnicodeError):
        return {'detail':'UNAVAILABLE'}


async def read_error_detail(response):
    body=bytearray()
    async for chunk in response.aiter_bytes(chunk_size=4096):
        body.extend(chunk)
        if len(body)>8192: return {'detail':'UNAVAILABLE'}
    return provider_error_detail(body)


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


class GroqProvider(LLMProvider):
    name = 'Groq'

    def __init__(self, api_key, model=DEFAULT_MODEL, transport=None):
        if (not isinstance(api_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', api_key)
                or not isinstance(model, str) or model not in SUPPORTED_MODELS):
            raise RecommendationError('AI_NOT_CONFIGURED', 503,
                'Groq is not configured correctly. Check the backend-only key and supported model.')
        self._api_key, self.model, self._transport = api_key, model, transport

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
        payload = {'model': self.model, 'messages': messages, 'stream': False,
            'max_completion_tokens': 4096, 'reasoning_effort': 'low', 'include_reasoning': False,
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'travel_response', 'strict': True, 'schema': schema}}}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10),
                    follow_redirects=False, trust_env=False, transport=self._transport) as client:
                async with client.stream('POST', ENDPOINT,
                        headers={'Authorization': 'Bearer ' + self._api_key,
                                 'Content-Type': 'application/json'}, json=payload) as response:
                    if response.status_code != 200:
                        detail = await read_error_detail(response)
                        provider_diagnostic('HTTP_FAILURE', response.status_code, detail)
                        if response.status_code == 400 and detail.get('code') == 'json_validate_failed':
                            raise RecommendationError('AI_SCHEMA_REJECTED', 502,
                                'The AI provider rejected its output against the required schema. No result was accepted and no automatic retry was made.')
                        # Provider error bodies may echo private input. Never expose them.
                        if response.status_code == 429:
                            raise RecommendationError('AI_RATE_LIMITED', 429,
                                'Groq quota or rate limit reached. No automatic retry was made.')
                        raise RecommendationError('AI_PROVIDER_FAILED', 502,
                            'Groq could not complete this request. Check configuration and availability. No automatic retry was made.')
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > MAX_ENVELOPE_BYTES:
                            raise invalid_response()
        except httpx.TimeoutException:
            provider_diagnostic('TRANSPORT_TIMEOUT')
            raise TimeoutError('Groq request timed out') from None
        except httpx.HTTPError:
            provider_diagnostic('TRANSPORT_ERROR')
            raise RecommendationError('AI_PROVIDER_FAILED', 502,
                'Groq could not be reached. No automatic retry was made.') from None
        try:
            envelope = json.loads(body)
            choices = envelope['choices']
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError()
            choice = choices[0]
            message = choice['message']
            if message.get('refusal') or choice.get('finish_reason') == 'content_filter':
                provider_diagnostic('REFUSAL')
                raise ProviderRefusal()
            if choice.get('finish_reason') == 'length':
                provider_diagnostic('OUTPUT_TRUNCATED')
                raise RecommendationError('AI_OUTPUT_TRUNCATED', 502,
                    'The AI response reached its output limit. No partial result was accepted and no automatic retry was made.')
            if (choice.get('finish_reason') != 'stop' or message.get('role') != 'assistant'
                    or message.get('tool_calls') or message.get('function_call')):
                raise ValueError()
            text = message['content']
            if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
                raise ValueError()
            return text  # Strict JSON + domain validation remains mandatory in service.
        except ProviderRefusal:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise invalid_response() from None
