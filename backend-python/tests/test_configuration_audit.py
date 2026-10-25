"""Synthetic configuration only: never opens real environment files or networks."""
import pytest
from app import configuration as cfg
from app.providers import create_provider
from app.recommendations import RecommendationError


@pytest.mark.parametrize('marker,value',[
    ('APP_ENV','staging'),('APP_ENV','production'),('APP_MODE','production'),
    ('RENDER','true'),('VERCEL','1'),
])
def test_each_hosted_marker_prevents_file_fallback(monkeypatch,marker,value):
    for key in ('APP_ENV','APP_MODE','RENDER','VERCEL'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv(marker,value)
    monkeypatch.setattr(cfg,'dotenv_values',lambda *a,**k:pytest.fail('Local file read'))
    assert cfg.private_backend_values()[marker]==value


def test_explicit_blank_process_key_does_not_reactivate_file_key(monkeypatch):
    for key in ('APP_ENV','APP_MODE','RENDER','VERCEL'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setattr(cfg,'dotenv_values',lambda *a,**k:{'GROQ_API_KEY':'synthetic-file-only'})
    monkeypatch.setenv('GROQ_API_KEY','')
    values=cfg.private_backend_values()
    assert values['GROQ_API_KEY']==''
    with pytest.raises(RecommendationError) as error:create_provider(lambda:values)
    assert error.value.code=='AI_NOT_CONFIGURED'


def test_public_auth_selection_never_uses_administrative_key(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://synthetic.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','synthetic-admin-only')
    monkeypatch.delenv('SUPABASE_PUBLISHABLE_KEY',raising=False)
    monkeypatch.delenv('SUPABASE_ANON_KEY',raising=False)
    assert cfg.public_auth_values()==('https://synthetic.supabase.co','')
    monkeypatch.setenv('SUPABASE_ANON_KEY','synthetic-anon')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','synthetic-public')
    assert cfg.public_auth_values()[1]=='synthetic-public'


@pytest.mark.parametrize('provider',['huggingface','ollama','unknown'])
def test_unimplemented_provider_fails_without_claiming_support(provider):
    with pytest.raises(RecommendationError) as error:
        create_provider(lambda:{'AI_PROVIDER':provider,'GROQ_API_KEY':'synthetic-provider-only'})
    assert error.value.code=='AI_NOT_CONFIGURED'


def test_secret_model_serialization_masks_values():
    settings=cfg.ProviderSettings(GROQ_API_KEY='synthetic-private-only')
    assert 'synthetic-private-only' not in repr(settings)+settings.model_dump_json()
