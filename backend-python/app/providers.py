"""Activity 4.1: asynchronous provider abstraction and lazy, offline factory."""
from abc import ABC, abstractmethod


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
        from .openai import OpenAIProvider
        return OpenAIProvider(values.OPENAI_API_KEY.get_secret_value(), values.OPENAI_MODEL,
            transport=transport, reasoning_effort=values.OPENAI_REASONING_EFFORT)
    except RecommendationError:
        raise
    except Exception:
        pass
    raise RecommendationError('AI_NOT_CONFIGURED', 503,
        'AI provider configuration is missing or invalid. Check the backend-only settings.')
