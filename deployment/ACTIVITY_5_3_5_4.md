# Activity 5.3: readiness, not a live deployment

## 5.3 testing and production boundary

Activity 5.2's private detail route, hooks, saved API, edit/regenerate/download and motion/icon layout are reused. Deterministic scenarios cover a solo weekend, relaxed luxury couple with nature interests, and an adventure/culture budget group. They demonstrate prompt/context propagation and output-contract validation, **not live LLM quality or real-world suitability**. Existing tests cover timeouts, provider rejection/rate limits, timeline/budget constraints, owner isolation, stale updates and export recovery.

Production disables `/api/trips`, `/api/trips/*`, `/api/history` and aliases before any legacy store can run. Local legacy behavior is retained. No ownership assignment or migration of existing records is needed. Full plans continue using verified Supabase JWTs, public keys and owner-scoped RLS. No public route obtains an admin client. Production requires exact API Host and HTTPS frontend Origin; cross-origin browser requests from other origins are rejected. Tokens remain memory-only and expire; refresh requires sign-in again on the existing route.

The explicit cloud startup factory fails if production mode, verified saved schema, public auth configuration, exact hosts or AI configuration are missing. Setting a verification flag does not verify or migrate the database. Old legacy ownership flags must remain false. Production never reads a workstation `.env`. Logs must omit access URLs/bodies/tokens; the reviewed command disables access logging. Existing bounded request/response parsing and provider timeouts remain in place.

Conservative in-process limits: 30 account requests/minute across the instance; 6 AI requests/user/minute; 60 AI requests/hour across the instance; 2 simultaneous AI requests. There are no automatic provider retries. These limits reset on restart and are **not distributed quotas or a billing guarantee**. Use one worker/instance for this initial configuration and approve provider-side spend limits before opening public access. Benchmark numbers from local mocked calls do not establish internet latency, cold-start performance or scalability.

CI performs offline Python/JS tests, deterministic lockfile installation, a hosted-mode frontend build, public-bundle pattern checks and tracked-env exclusion. No deployment credentials are used. A passing static scan cannot establish that arbitrary strings contain no secrets. The build uses minification and emits no source maps by default; its measured size should be reported with the test evidence.

## Required deployment configuration (broader Activity 5.4 is queued)

Provider settings use typed Pydantic models and `SecretStr`. Environment/process values win over the separate project's legacy local fallback file. `uvicorn --env-file backend-python/.env.local` explicitly loads local auth settings into the process; existing process variables win according to dotenv behavior. Staging/production use process environment only, with `APP_MODE=production` and `APP_ENV=staging` or `production`. No actual environment files are committed or modified by this change.

| Configuration | Application |
|---|---|
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` (or existing `SUPABASE_ANON_KEY`) | Backend public client + verified user JWT; never a service-key fallback |
| `SAVED_ITINERARIES_SCHEMA_VERIFIED` | Operator attestation after inspecting the existing table/RLS |
| `APP_MODE`, `APP_ENV`, `API_HOST`, `FRONTEND_ORIGIN` | Explicit local/hosted boundary and exact domains |
| `AI_PROVIDER=groq`, `GROQ_API_KEY` | Existing backend-only Groq credential; no new key required |
| `GROQ_MODEL` | Default `openai/gpt-oss-20b`; supported model validation |
| `GROQ_REFINEMENT_MODEL` | Default `openai/gpt-oss-120b`; explicit environment override, no silent switch |
| `VITE_API_BASE_URL` | Public frontend build setting: local `/api`, hosted exact `https://BACKEND/api` |
| Supabase secret/service-role key | Local explicit administration only; do not configure it on the public app host |
| `SECRET_KEY`, `ALGORITHM`, token expiry | Not used: Supabase issues/signs/verifies sessions. Creating an unused local signing key would not secure this application |
| Hugging Face token / Ollama URL and models | Optional alternative-provider exercises; no supported adapter, token, installation or model download is claimed here |

The supplied course screenshots are reference examples, not credentials to copy. If custom JWT signing or an alternative provider is mandatory for assessment, clarify that requirement before changing the authentication architecture or installing another provider. Existing Gemini support is retained but not selected for this production plan.

Frontend key/token/secret/password-named `VITE_` variables are rejected during configuration because Vite bundles these values publicly. Hosted builds require a valid HTTPS `/api` backend URL. The Vercel root must be the repository root, retaining the workspace lockfile and `shared/` imports: install `npm ci --ignore-scripts`, build `npm run build`, output `frontend/dist`. The review-only SPA rewrite covers direct `/itineraries/:tripID` navigation; it is not a backend API proxy.

## Exact approval needed before cloud setup

1. The user selected a **free course demo**: Vercel Hobby and Render Free only. No payment method, paid resource, upgrade or overage is authorized. Render says Free is not for production and sleeps after inactivity; Vercel Hobby is limited to personal non-commercial use. No cloud service has been created.
2. Identify the user's Vercel and Render accounts/teams. Approve connecting **only the existing repository** and the necessary Git provider permissions. No new repository is needed.
3. Approve creating one frontend project and one backend service, selected regions/plan, and public exposure. Keep automatic deployment off until verification.
4. Approve transmitting the existing Groq key plus existing Supabase public auth key/project URL to **Render backend environment storage**. Never send a service-role key or signing secret to Vercel. Vercel receives only the exact public API base URL.
5. Once hostnames are assigned, approve `API_HOST`, `FRONTEND_ORIGIN`, and `VITE_API_BASE_URL`, plus any actual Supabase Site URL/redirect or email-confirmation setting change if needed. Password login itself does not justify weakening email verification.
6. After settings are reviewed, run bounded deployed health/sign-in/owner-read/export checks. Any new account, real AI charge, write/delete or cleanup test requires its specific approval. Verify provider-side limits and rollback by disabling the service if checks fail.

These are pending actions, not completed deployment steps. No cloud resource, OAuth grant, key transmission, billing change, database mutation or SkillWallet submission has occurred.

Official references checked 2026-10-24: [Render FastAPI](https://render.com/docs/deploy-fastapi), [Render Free limitations](https://render.com/docs/free), [Render pricing](https://render.com/pricing), [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite), [Vercel Hobby](https://vercel.com/docs/plans/hobby).
