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
    from .configuration import private_backend_values
    return private_backend_values()


def create_provider(configuration=None, transport=None, *, for_refinement=False) -> LLMProvider:
    # No key reads or provider calls at module import / application startup.
    from .recommendations import RecommendationError
    try:
        from .configuration import ProviderSettings
        values = ProviderSettings.model_validate((configuration or read_configuration)())
        selected = values.AI_PROVIDER
        if selected == 'groq':
            from .groq import GroqProvider, DEFAULT_MODEL
            return GroqProvider(values.GROQ_API_KEY.get_secret_value(),
                values.GROQ_REFINEMENT_MODEL if for_refinement else values.GROQ_MODEL, transport=transport)
        if selected == 'gemini':
            from .gemini import GeminiProvider, DEFAULT_MODEL
            return GeminiProvider(values.GEMINI_API_KEY.get_secret_value(),values.GEMINI_MODEL, transport=transport)
    except RecommendationError:
        raise
    except Exception:
        pass
    raise RecommendationError('AI_NOT_CONFIGURED', 503,
        'AI provider configuration is missing or invalid. Check the backend-only settings.')
