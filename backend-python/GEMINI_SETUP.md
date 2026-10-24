> Optional adapter only. The supplied Epic 4 explicitly requires Groq, which is
> now the default. Follow GROQ_SETUP.md; do not configure Gemini unless explicitly
> choosing AI_PROVIDER=gemini for a separate optional test.

# Activity 3.3: Gemini adapter (live validation still required)

Connects the recommendation service to Google's documented generateContent REST
endpoint using existing HTTPX. Default model: gemini-3.5-flash-lite (configurable).

## Private configuration — only when guided

Use the separate FastAPI project's existing backend/.env (same private file as
Supabase), never frontend/.env, VITE_ variables, Git, screenshots, chat or the
original project. Preserve existing Supabase lines. Settings: GEMINI_API_KEY and
optional GEMINI_MODEL; process environment overrides the file. The installer
never reads or changes any .env. Do not put keys in shell commands/history.

Confirm Google project tier/quota and costs before a live request; key presence
does not establish free-tier eligibility. Do not enable billing simply to make
this patch work. Restart FastAPI after setup. Generation sends trip preferences
(including diet/mobility notes) to Google; first test should use non-sensitive
sample data. Google's applicable data-use terms and quotas remain relevant.

## Safety

Missing/invalid config returns 503 without network. One request per explicit
Generate action; no automatic retries/fallbacks. Fixed HTTPS Google host, header
key, no redirects/proxy-env. HTTP timeout 25 seconds inside the existing 30-second
service timeout. One candidate, 8192 max output tokens, bounded response bytes.
Refusals, partial output, bad JSON/schema/preferences are rejected. Rate/quota
limits return safe errors, never automatic upgrades. Results are unverified
suggestions, not bookings. Generating never saves or overwrites a trip.

## Offline checks (separate project root)

```powershell
.\backend-python\.venv\Scripts\python.exe -m pytest -c .\backend-python\pytest.ini .\backend-python\tests
```

Tests disable default Gemini key lookup, using fake keys and MockTransport only.
No Google account, billing change or live call needed. Windows-safe IDs preserved.

## Remaining

Passing offline tests is not proof of a successful real Google call. After
approved setup, inspect real results for different interests, budgets/styles,
and diet/mobility preferences. Existing fetch/history/full-itinerary-persistence
gaps remain separate. This adds no tables, auth, public deployment or Git changes.
Keep the privileged backend bound to loopback.

Protocol references checked 2026-10-24:
- https://ai.google.dev/api/generate-content (ResponseFormatConfig)
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/structured-output
