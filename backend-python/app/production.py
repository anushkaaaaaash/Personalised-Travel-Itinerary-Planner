"""Explicit cloud entry point; fails before binding when required setup is missing."""
import os
from .auth import SupabaseAuthService
from .production_security import settings

def create_production_app():
    settings(SupabaseAuthService())
    from .configuration import ProviderSettings
    try:provider=ProviderSettings.model_validate(dict(os.environ))
    except Exception:raise RuntimeError('Invalid production provider settings.') from None
    if provider.AI_PROVIDER!='openai' or not provider.OPENAI_API_KEY.get_secret_value().strip():
        raise RuntimeError('Production AI configuration is incomplete. No provider request was made.')
    from .providers import create_provider
    try:create_provider(configuration=lambda:dict(os.environ))
    except Exception:raise RuntimeError('Production AI configuration is invalid. No provider request was made.') from None
    from .main import create_app
    return create_app()
