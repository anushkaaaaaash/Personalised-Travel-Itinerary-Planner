"""Typed provider settings and explicit environment precedence. Never logs values."""
import os
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values
from pydantic import BaseModel,ConfigDict,SecretStr,field_validator

def hosted_environment():
    return (os.getenv('APP_MODE','local').lower()=='production' or bool(os.getenv('RENDER'))
        or bool(os.getenv('VERCEL')) or os.getenv('APP_ENV','').lower() in {'production','staging'})

def private_backend_values():
    # Hosted deployments never load workstation files. Local --env-file values already
    # in the process take precedence over the legacy separate-project fallback file.
    if hosted_environment():return dict(os.environ)
    path=Path(__file__).resolve().parents[2]/'backend'/'.env'
    return {**dotenv_values(path,interpolate=False),**os.environ}

def public_auth_values():
    return os.getenv('SUPABASE_URL',''),os.getenv('SUPABASE_PUBLISHABLE_KEY') or os.getenv('SUPABASE_ANON_KEY','')

class ProviderSettings(BaseModel):
    model_config=ConfigDict(extra='ignore',hide_input_in_errors=True)
    AI_PROVIDER: Literal['groq','gemini']='groq'
    GROQ_API_KEY: SecretStr=SecretStr('')
    GROQ_MODEL: Literal['openai/gpt-oss-20b','openai/gpt-oss-120b']='openai/gpt-oss-20b'
    GROQ_REFINEMENT_MODEL: Literal['openai/gpt-oss-20b','openai/gpt-oss-120b']='openai/gpt-oss-120b'
    GEMINI_API_KEY: SecretStr=SecretStr('')
    GEMINI_MODEL: str='gemini-3.5-flash-lite'

    @field_validator('GEMINI_MODEL')
    @classmethod
    def bounded_model(cls,value):
        if not value or len(value)>100 or any(ord(c)<33 for c in value):raise ValueError('Invalid model configuration')
        return value
