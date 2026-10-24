"""Server-side Gemini REST adapter. No retries, tools, SDK, or live startup calls."""
import json
import os
import re
from pathlib import Path
import httpx
from dotenv import dotenv_values
from .recommendations import RecommendationError, RecommendationService, ProviderRefusal
from .providers import LLMProvider

DEFAULT_MODEL = 'gemini-3.5-flash-lite'
MODEL_PATTERN = re.compile(r'gemini-[a-z0-9][a-z0-9.-]{0,79}\Z')
MAX_ENVELOPE_BYTES = 262144
MAX_TEXT_BYTES = 65536


def read_configuration():
    # Same separate project's private backend/.env as Supabase; process env wins.
    # Read only upon an explicit generation request. Never read frontend env files.
    env_file = Path(__file__).resolve().parents[2] / 'backend' / '.env'
    values = {**dotenv_values(env_file, interpolate=False), **os.environ}
    return values.get('GEMINI_API_KEY', ''), values.get('GEMINI_MODEL', DEFAULT_MODEL)


def invalid_response():
    return RecommendationError('AI_INVALID_RESPONSE', 502,
        'The AI response was incomplete or invalid. No recommendations were accepted.')


class GeminiProvider(LLMProvider):
    name = 'Google Gemini'

    def __init__(self, api_key, model=DEFAULT_MODEL, transport=None):
        # Header-safe key and path-safe model; never allow arbitrary API hosts.
        if (not isinstance(api_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', api_key)
                or not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model)):
            raise RecommendationError('AI_NOT_CONFIGURED', 503,
                'Gemini is not configured correctly. Check the backend-only key and model settings. Your saved trip is unchanged.')
        self._api_key = api_key
        self.model = model
        self._transport = transport  # Test-only MockTransport; never an env-controlled URL.

    async def generate(self, messages, response_schema):
        if (len(messages) != 2 or messages[0].get('role') != 'system'
                or messages[1].get('role') != 'user'
                or not all(isinstance(m.get('content'), str) for m in messages)):
            raise invalid_response()
        payload = {
            'systemInstruction': {'parts': [{'text': messages[0]['content']}]},
            'contents': [{'role': 'user', 'parts': [{'text': messages[1]['content']}]}],
            'generationConfig': {'responseFormat': {'text': {
                'mimeType': 'APPLICATION_JSON', 'schema': response_schema}},
                'candidateCount': 1, 'maxOutputTokens': 8192},
        }
        url = 'https://generativelanguage.googleapis.com/v1beta/models/' + self.model + ':generateContent'
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10),
                    follow_redirects=False, trust_env=False, transport=self._transport) as client:
                async with client.stream('POST', url,
                        headers={'x-goog-api-key': self._api_key, 'Content-Type': 'application/json'},
                        json=payload) as response:
                    if response.status_code != 200:
                        # Do not read or expose Google error bodies, headers or credentials.
                        if response.status_code == 429:
                            raise RecommendationError('AI_RATE_LIMITED', 429,
                                'Gemini quota or rate limit reached. No automatic retry was made. Check your quota before trying again.')
                        raise RecommendationError('AI_PROVIDER_FAILED', 502,
                            'Gemini could not complete this request. Check its configuration and availability. No automatic retry was made.')
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > MAX_ENVELOPE_BYTES:
                            raise invalid_response()
        except httpx.TimeoutException:
            raise TimeoutError('Gemini request timed out') from None
        except httpx.HTTPError:
            raise RecommendationError('AI_PROVIDER_FAILED', 502,
                'Gemini could not be reached. No automatic retry was made.') from None
        try:
            envelope = json.loads(body)
            if not isinstance(envelope, dict):
                raise ValueError()
            feedback = envelope.get('promptFeedback', {})
            if not isinstance(feedback, dict):
                raise ValueError()
            if feedback.get('blockReason') not in (None, '', 'BLOCK_REASON_UNSPECIFIED'):
                raise ProviderRefusal()
            candidates = envelope.get('candidates')
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError()
            candidate = candidates[0]
            reason = candidate.get('finishReason')
            if reason in {'SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'IMAGE_SAFETY'}:
                raise ProviderRefusal()
            if reason == 'MAX_TOKENS':
                raise RecommendationError('AI_OUTPUT_TRUNCATED', 502,
                    'The AI response reached its output limit. No partial result was accepted and no automatic retry was made.')
            if reason != 'STOP':
                raise ValueError()  # Includes MAX_TOKENS: never accept partial output.
            parts = candidate['content']['parts']
            if not isinstance(parts, list) or not parts:
                raise ValueError()
            texts = []
            for part in parts:
                if not isinstance(part, dict):
                    raise ValueError()
                if part.get('thought') is True:
                    continue
                if not isinstance(part.get('text'), str) or 'functionCall' in part:
                    raise ValueError()
                texts.append(part['text'])
            text = ''.join(texts)
            if not text or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
                raise ValueError()
            # Service performs strict JSON/schema/preference checks; no markdown repair.
            return text
        except ProviderRefusal:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise invalid_response() from None


class GeminiRecommendationService:
    """Lazy configuration keeps all startup and health calls offline."""
    def __init__(self, configuration=None, transport=None):
        self.configuration = configuration
        self.transport = transport

    async def recommend(self, preferences):
        try:
            key, model = (self.configuration or read_configuration)()
        except Exception:
            raise RecommendationError('AI_NOT_CONFIGURED', 503,
                'Gemini configuration could not be read. Your saved trip is unchanged.') from None
        provider = GeminiProvider(key, model, transport=self.transport)
        return await RecommendationService(provider).recommend(preferences)
