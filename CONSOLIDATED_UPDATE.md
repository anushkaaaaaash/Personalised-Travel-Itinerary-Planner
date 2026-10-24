# Consolidated travel planner update

This update targets the separate -FastAPI project, not the original project.
It combines Activity 3.3 and the supplied Epic 4 requirements rather than asking
you to apply separate provider/foundation patches. The original saves and 3.2
prompt builder remain intact. No environment file is replaced.

## Included

- Dynamic prompts and categorized AI recommendations.
- Explicit abstract LLM provider interface, asynchronous Groq REST adapter as
  course-required default; Gemini remains an optional explicitly selected adapter.
- Day-by-day itinerary generation, timeline display, editable planning workflow,
  itinerary optimization/route visualization, vibes and feedback refinement.
- Saved-trip listing/detail/history with clear local-versus-owner scope.
- Email/password registration/login schemas and Supabase Auth integration;
  memory-only browser sessions, server-verified bearer identity and owner-filtered
  storage. Public mode is gated pending approved schema and real isolation tests.
- Framer Motion and Lucide React; loading, stale-response and cancellation checks.
- Offline tests, guarded single-batch installer and deployment review templates.

## One installation and verification batch

Use the supplied apply_update.py with the confirmed separate project path and
--apply. It checks all source hashes before changes, asks you to type UPDATE,
backs up affected files/package manifests, applies only listed files, merges
only the two UI dependency keys, runs npm install, Python tests, all JavaScript
workspaces and the production build. It stops on the first failure and prints
the log location. It never starts AI calls or changes a database/account.

Your existing Python environment is detected at backend-python.venv or
backend-python/.venv; no replacement environment is silently created.

## Running locally after verification

Keep the existing private frontend setting VITE_API_BASE_URL=/api. Start FastAPI
with the existing project Python, working directory backend-python:
python -m uvicorn app.main:app --host 127.0.0.1 --port 5000
In another terminal from project root: npm run dev:frontend -- --host 127.0.0.1
Do NOT use root npm run dev (that preserved command starts the old Express API).

## Still requires your private setup / approval

- Groq key/account quota and an authorized real AI request. Do not send the key
  in chat. A Gemini key cannot authenticate to Groq. See GROQ_SETUP.md.
- Review AI factual quality, timings, dietary and accessibility suitability.
  Estimated coordinates/travel times are not live directions or guarantees.
- Auth/ownership schema migration, legacy-row decisions and two-user live tests.
  Supplied SQL is review-only; it has NOT been applied.
- Vercel/Render deployment and any additional Epic 5–7 requirements not supplied.

Offline passing tests are not live provider, real auth/RLS, course submission or
public deployment proof. No GitHub push, migration or hosting change was made.
