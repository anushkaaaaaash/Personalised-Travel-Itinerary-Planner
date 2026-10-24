import pytest

@pytest.fixture
def payload():
    return dict(destination='Goa', departureCity='Mumbai', startDate='2026-10-24', endDate='2026-10-29',
                travelers=2, budget=2500, currency='INR', interests=['culture', 'food'],
                dietaryNeeds='', travelPace='balanced')


@pytest.fixture(autouse=True)
def no_live_gemini_configuration(monkeypatch):
    # Tests never consume a developer's real backend key, even if .env exists.
    monkeypatch.setattr('app.gemini.read_configuration', lambda: ('', 'gemini-3.5-flash-lite'))

@pytest.fixture(autouse=True)
def no_live_auth_configuration(monkeypatch):
    # Never consume real auth credentials or accidentally send verification requests.
    for name in ('SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_ANON_KEY'):
        monkeypatch.delenv(name, raising=False)

@pytest.fixture(autouse=True)
def no_live_provider_configuration(monkeypatch):
    # A test must explicitly inject fake config; never read a developer's .env.
    for name in ('AI_PROVIDER', 'GROQ_API_KEY', 'GROQ_MODEL', 'GEMINI_API_KEY', 'GEMINI_MODEL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('app.providers.read_configuration', lambda: {})
