import pytest

@pytest.fixture
def payload():
    return dict(destination='Goa', departureCity='Mumbai', startDate='2026-10-24', endDate='2026-10-29',
                travelers=2, budget=2500, currency='INR', interests=['culture', 'food'],
                dietaryNeeds='', travelPace='balanced')


@pytest.fixture(autouse=True)
def no_live_auth_configuration(monkeypatch):
    # Never consume real auth credentials or accidentally send verification requests.
    for name in ('SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_ANON_KEY'):
        monkeypatch.delenv(name, raising=False)

@pytest.fixture(autouse=True)
def no_live_provider_configuration(monkeypatch):
    # A test must explicitly inject fake config; never read a developer's .env.
    for name in ('AI_PROVIDER', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_REASONING_EFFORT', 'GROQ_API_KEY', 'GEMINI_API_KEY', 'GEMINI_MODEL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('app.providers.read_configuration', lambda: {})

@pytest.fixture(autouse=True)
def no_private_dotenv_reads(monkeypatch):
    # Isolate the low-level loader too; config precedence tests replace this fake.
    monkeypatch.setattr('app.configuration.dotenv_values', lambda *a, **k: {})
    monkeypatch.setattr('app.storage.dotenv_values', lambda *a, **k: {})
