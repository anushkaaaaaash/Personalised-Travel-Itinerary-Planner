# Course-required Groq setup — private, after installation

Groq is the default for Activity 4.1. The code uses LLMProvider ABC and async HTTPX
calls to Groq's fixed HTTPS endpoint. No real request has been sent during tests.

After the update/tests complete, open the separate project's existing backend/.env
in a local text editor. Preserve all Supabase settings. Add/update these privately:

AI_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_API_KEY=YOUR_PRIVATE_GROQ_KEY

Replace the placeholder with your own key only in the local editor. Never share
it in chat/screenshots/Git, terminal history, frontend or VITE_ variables. Ensure
.env is Git-ignored and untracked before saving; do not stage it. The installer
does not read or rewrite environment files. Restart local FastAPI after setup.
A Gemini key cannot authenticate to Groq. Optional Gemini requires explicit
AI_PROVIDER=gemini and is not needed for the supplied Epic 4 requirement.

Confirm your actual Groq project free-tier quota before approving one live call.
Do not enable billing or upgrade an account just to run this update. Requests
send trip preferences and refinement context to Groq; first use non-sensitive
sample details and review the provider's applicable data-use terms.

The default model is openai/gpt-oss-20b with strict JSON output, low reasoning
and a 4096-completion-token cap. Prompt/schema tokens also count toward quota.
Long itineraries may hit the output cap and are rejected safely; rate limits
return a safe error. No automatic retry, fallback, upgrade or duplicate save.

After approved live generation, inspect dates, budgets, interests/style/vibes,
pace, diet/mobility notes, timings, refinement and warnings. Provider output is
not proof of factual prices, geographic accuracy, accessibility or dietary safety.
Route optimization is local estimation, not live directions. Mock tests and a
valid key alone do not prove full activity completion.

Official references checked 2026-10-24:
https://console.groq.com/docs/models
https://console.groq.com/docs/structured-outputs
https://console.groq.com/docs/rate-limits
https://console.groq.com/docs/api-reference
