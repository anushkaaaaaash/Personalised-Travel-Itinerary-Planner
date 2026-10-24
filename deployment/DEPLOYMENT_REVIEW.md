# Vercel frontend / Render backend — prepared, NOT deployed

These are review-only templates, not root auto-discovery configuration. Nothing
has been uploaded, deployed or connected to a Git provider. No paid plan chosen.

## Required before enabling public access

1. Review and separately approve the ownership migration; back up existing data.
   Apply only after approval, decide legacy-row ownership explicitly, then test
   two real users cannot read/change one another's trips or NULL-owner rows.
2. Configure Supabase Auth confirmations, password policy, redirect URLs and
   abuse/rate limits. Verify real sign-up/login/logout and expired sessions.
3. Use public/publishable Supabase key + verified user bearer for owned storage,
   NEVER the privileged legacy secret key in production. See AUTH_SETUP.md.
4. Verify Groq live output and account quota with non-sensitive preferences.
5. Set exact FRONTEND_ORIGIN to the HTTPS Vercel origin; no wildcard CORS.
   Set VITE_API_BASE_URL on Vercel to https://YOUR-RENDER-HOST/api.
   VITE_ values are public: NEVER place AI keys or Supabase secret keys there.
6. Only after the above checks set APP_MODE=production,
   TRIP_OWNERSHIP_ENABLED=true and TRIP_OWNERSHIP_SCHEMA_VERIFIED=true.
   Flags record an operator's verification; they do not perform a migration.

The provided Render template deliberately leaves both ownership flags false,
so it returns 503 until setup is reviewed. Do not treat this as a successful
public deployment. Hosting, quotas, billing and provider data terms must be
reviewed on the user's accounts; this update makes no account changes.

## Platform commands (after approval)

Render root directory backend-python; build pip install -r requirements.txt;
start uvicorn app.main:app --host 0.0.0.0 --port $PORT. This public binding is
ONLY for the reviewed authenticated deployment, not local privileged mode.
Vercel project root is repository root; npm run build outputs frontend/dist.
Use the templates only after the concrete hosts/environment settings are known.

Official references checked 2026-10-24:
https://render.com/docs/deploy-fastapi
https://vercel.com/docs/frameworks/frontend/vite
