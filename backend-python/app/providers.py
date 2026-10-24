"""Activity 4.1: asynchronous provider abstraction and lazy, offline factory."""
from abc import ABC, abstractmethod
import os
from pathlib import Path
from dotenv import dotenv_values


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(self, messages: list[dict], response_schema: dict) -> dict | str:
        """Return untrusted generated JSON; callers validate domain constraints."""
        raise NotImplementedError


def read_configuration():
    env_file = Path(__file__).resolve().parents[2] / 'backend' / '.env'
    return {**dotenv_values(env_file, interpolate=False), **os.environ}


def create_provider(configuration=None, transport=None, *, for_refinement=False) -> LLMProvider:
    # No key reads or provider calls at module import / application startup.
    from .recommendations import RecommendationError
    try:
        values = (configuration or read_configuration)()
        selected = values.get('AI_PROVIDER', 'groq')
        if selected == 'groq':
            from .groq import GroqProvider, DEFAULT_MODEL
            return GroqProvider(values.get('GROQ_API_KEY', ''),
                ('openai/gpt-oss-120b' if for_refinement else values.get('GROQ_MODEL', DEFAULT_MODEL)), transport=transport)
        if selected == 'gemini':
            from .gemini import GeminiProvider, DEFAULT_MODEL
            return GeminiProvider(values.get('GEMINI_API_KEY', ''),
                values.get('GEMINI_MODEL', DEFAULT_MODEL), transport=transport)
    except RecommendationError:
        raise
    except Exception:
        pass
    raise RecommendationError('AI_NOT_CONFIGURED', 503,
        'AI provider configuration is missing or invalid. Check the backend-only settings.')
