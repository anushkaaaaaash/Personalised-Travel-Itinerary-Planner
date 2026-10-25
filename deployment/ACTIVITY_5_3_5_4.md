# Activity 5.3 course-demo acceptance and Activity 5.4 configuration

## Recorded acceptance (2026-10-25)

PR #8 merged at `0fc98046ba46d79f5dc0ff600f46bafef201538e` after independent review,
612 Python tests, 358 JavaScript tests, build/scans and both GitHub CI runs passed.
Vercel reported successful deployment for this commit; public frontend and API health
returned 200. The operator subsequently confirmed the Render deployment and supplied
the rendered three-day production itinerary. This is user-run browser evidence,
not an autonomous authenticated test or an independently read Render commit ID.

The submitted result covered December 11–13 with durations 30–150 minutes and
chronological, non-overlapping activities. It showed USD956.66 estimated cost and
USD1543.34 remaining. This demonstrates successful bounded production generation;
it does not establish factual travel accuracy. The text's day-one main-activity
count disagreed with its listed activities, a domestic flight was described as
international, and a beach name was unverified. AI prose and prices require review.
No additional export test, data write, account change or AI request was performed
for this documentation update. Earlier owner-isolation, CRUD and export evidence
remains separate. Activity 5.3 is implemented and tested as a free course demo,
not certified for reliable always-on production or travel booking.

## 5.3 testing and production boundary

Activity 5.2's private detail route, hooks, saved API, edit/regenerate/download and motion/icon layout are reused. Deterministic scenarios cover a solo weekend, relaxed luxury couple with nature interests, and an adventure/culture budget group. They demonstrate prompt/context propagation and output-contract validation, **not live LLM quality or real-world suitability**. Existing tests cover timeouts, provider rejection/rate limits, timeline/budget constraints, owner isolation, stale updates and export recovery.

Production disables `/api/trips`, `/api/trips/*`, `/api/history` and aliases before any legacy store can run. Local legacy behavior is retained. No ownership assignment or migration of existing records is needed. Full plans continue using verified Supabase JWTs, public keys and owner-scoped RLS. No public route obtains an admin client. Production requires exact API Host and HTTPS frontend Origin; cross-origin browser requests from other origins are rejected. Tokens remain memory-only and expire; refresh requires sign-in again on the existing route.

The explicit cloud startup factory fails if production mode, verified saved schema, public auth configuration, exact hosts or AI configuration are missing. Setting a verification flag does not verify or migrate the database. Old legacy ownership flags must remain false. Production never reads a workstation `.env`. Logs must omit access URLs/bodies/tokens; the reviewed command disables access logging. Existing bounded request/response parsing and provider timeouts remain in place.

Conservative in-process limits: 30 account requests/minute across the instance; 6 AI requests/user/minute; 60 AI requests/hour across the instance; 2 simultaneous AI requests. There are no automatic provider retries. These limits reset on restart and are **not distributed quotas or a billing guarantee**. Use one worker/instance for this initial configuration and approve provider-side spend limits before opening public access. Benchmark numbers from local mocked calls do not establish internet latency, cold-start performance or scalability.

CI performs offline Python/JS tests, deterministic lockfile installation, a hosted-mode frontend build, public-bundle pattern checks and tracked-env exclusion. No deployment credentials are used. A passing static scan cannot establish that arbitrary strings contain no secrets. The build uses minification and emits no source maps by default; its measured size should be reported with the test evidence.

## Required deployment configuration

### Explicit preview-origin approval

The backend supports one optional `FRONTEND_PREVIEW_ORIGIN` alongside `FRONTEND_ORIGIN`; each must be a complete HTTPS origin. Matching is exact, never a wildcard or Vercel suffix. An invalid optional value fails production setup closed. Leaving it unset preserves single-origin behavior. This permits browser requests from that site's code; verified authentication and owner-scoped access are still required.

The approved production origin is `https://personalised-travel-itinerary-plann.vercel.app`.
The single approved preview origin is `https://personalised-travel-itinerary-planner-git-f-7a86cd-anushka-76c5.vercel.app`;
it supersedes the old `f-0f4c9b` alias, which must remain blocked. Do not substitute
another PR alias without explicit approval. No settings are changed by these docs.
Never disable preview protection or email confirmation to make access work.

### Vercel frontend-only project

Use a single Vite project with Root Directory `frontend`, Node.js 24.x, and **Include source files outside of the Root Directory in the Build Step** enabled. Set Install Command to `cd .. && npm ci --ignore-scripts`, Build Command to `npm run build`, and Output Directory to `dist`. The root lockfile and workspace installation are required; frontend imports `shared/` and `deployment/frontend_config.mjs` outside its directory.

`frontend/vercel.json` is the active SPA rewrite configuration for this layout, allowing direct `/itineraries/:id` navigation to load the app. It declares no backend services or API proxy. Set only the public `VITE_API_BASE_URL` to the verified Render HTTPS endpoint ending in `/api`; backend credentials belong exclusively on Render. Do not deploy the autodetected Express or FastAPI Services entries to Vercel. The older `deployment/vercel.REVIEW_ONLY.json` describes an alternative repository-root build and is not automatically loaded; do not mix its `frontend/dist` output setting with a frontend-root project. Cloud deployment and direct-route acceptance remain separate from local configuration tests.

Render must use `PYTHON_VERSION=3.13.7`, matching the locally verified Python interpreter. Render supports a fully qualified released version through this environment variable ([official runtime documentation](https://render.com/docs/python-version)); do not rely on its changing default. CI also checks the current Python 3.13 patch. A future runtime upgrade requires testing before changing this pin.

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

Frontend key/token/secret/password-named `VITE_` variables are rejected because Vite
bundles them publicly. Hosted builds require a valid HTTPS `/api` backend URL.
Use the frontend-root configuration above; the repository-root template is only
an alternative, not a second required deployment.

## Cloud change boundaries

1. The existing deployment uses a **free course demo**: Vercel Hobby and Render Free only. No payment method, paid resource, upgrade or overage is authorized. Render Free sleeps after inactivity; Vercel Hobby is limited to personal non-commercial use.
2. Identify the user's Vercel and Render accounts/teams. Approve connecting **only the existing repository** and the necessary Git provider permissions. No new repository is needed.
3. Approve creating one frontend project and one backend service, selected regions/plan, and public exposure. Keep automatic deployment off until verification.
4. Approve transmitting the existing Groq key plus existing Supabase public auth key/project URL to **Render backend environment storage**. Never send a service-role key or signing secret to Vercel. Vercel receives only the exact public API base URL.
5. Once hostnames are assigned, approve `API_HOST`, `FRONTEND_ORIGIN`, and `VITE_API_BASE_URL`, plus any actual Supabase Site URL/redirect or email-confirmation setting change if needed. Password login itself does not justify weakening email verification.
6. After settings are reviewed, run bounded deployed health/sign-in/owner-read/export checks. Any new account, real AI charge, write/delete or cleanup test requires its specific approval. Verify provider-side limits and rollback by disabling the service if checks fail.

The existing projects and approved environment values were configured by the
operator during 5.3. The list above describes approval boundaries for future
changes, not instructions to recreate those resources. This audit changes no
cloud settings, keys, billing, database records or SkillWallet progress.

Official references checked 2026-10-24: [Render FastAPI](https://render.com/docs/deploy-fastapi), [Render Free limitations](https://render.com/docs/free), [Render pricing](https://render.com/pricing), [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite), [Vercel Hobby](https://vercel.com/docs/plans/hobby).
