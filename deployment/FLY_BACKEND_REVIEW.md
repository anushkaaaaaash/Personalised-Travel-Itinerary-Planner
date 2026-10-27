# Fly backend candidate — local preparation only

Based on verified main `e4a1cde8af443e927a8eca7dd8dda043c3d4c515`.
No Fly app/Machine was created, no image built remotely, no secret read/transferred,
no repository publication, and no Vercel/Render/Supabase settings changed.

## Architecture

Keep the existing Vercel frontend and Supabase auth/saved trips/private queue.
Deploy only the Python FastAPI backend to Fly; the root Node/Express package is
legacy and must not be selected by the generic public-repository build flow.
The root Dockerfile explicitly starts `app.production:create_production_app` on
8080 with one Uvicorn worker, non-root UID10001, no access log and verified HTTPS
upstream clients. Only application Python and pinned requirements enter the build
context; workstation credentials, Git history, frontend, tests and data do not.
No Fly volume/database or new paid search/provider operation is needed.

The root fly.toml uses approved Singapore/512MB/always-on settings and the proposed
app `personalised-travel-itinerary-planner`. Its matching fly.dev hostname is a
configuration candidate, NOT a claim the app/domain exists. On a name collision,
revise BOTH API_HOST and the health-check Host header before creation. Saved-schema
verification remains false and background jobs false until runtime prerequisites
are verified. Do not weaken Host/CORS/auth guards to pass health checks.

## Decisions and approvals still required

1. Confirm the Fly organization/account and app name. The UI proposed
   `mohith-mohan` Personal / `personalised-travel-itinerary-planner`, but that is
   only a proposed app name; availability is not verified.
2. User approved region, Machine size/count and budget at 2026-10-27 08:00 UTC.
   Approved choice is Singapore, one shared CPU,
   512MB, always-on (autostop off), no HA. This avoids sleeping during a durable
   background job but does not guarantee uptime. The UI's Amsterdam/256MB defaults
   were not accepted. Fly's published lowest-region 512MB reference is $3.69 per
   30-day always-on Machine; region, rootfs/storage, network and other charges vary.
   The authenticated Fly calculator subsequently quoted Singapore $4.69/month
   compute at 730h; user approved that plus usage charges, not a hard bill cap.
   Amsterdam/256MB defaults were rejected. No assumption of free hosting.
3. User explicitly approved the new secret destination: OpenAI API key and a scoped
   queue-worker DB credential in Fly secrets. Prior consent for the restricted
   Render secret alone did NOT authorize copying it; the new approval does cover
   Fly secret storage. Do not use a broad
   Supabase admin/service key. Prefer separately revocable Fly-scoped credentials
   if approved; no new role/credential is created by these files.
4. User approved publication of these Docker/TOML/test/documentation files to the same
   GitHub repo and deployment of the exact reviewed commit. No new repo or fork.
5. Approve Vercel API endpoint cutover only after the new backend is healthy and
   authenticated ownership checks pass. Keep the existing frontend origin and
   Supabase data; do not delete or stop the old backend before rollback is ready.

## Safe rollout sequence (not executed)

- Review Dockerfile, deny-by-default .dockerignore and TOML; select the app and
  region explicitly. Validate with Fly CLI and build the image in an authorized
  environment. Pin the approved base-image digest before a reproducible release.
- Use repository root build context, not `backend/`. Use the reviewed root fly.toml explicitly. Do not click a
  generic Node auto-build deployment without these settings.
- Configure exact approved API_HOST and matching health header, FRONTEND_ORIGIN,
  Supabase URL/publishable key and OpenAI runtime secret using approved secret
  controls. No key in Docker ARG/ENV, source, terminal output, image or screenshots.
- Mark SAVED_ITINERARIES_SCHEMA_VERIFIED only from the already verified target DB;
  keep legacy ownership flags false. Start with PLANNING_JOBS_ENABLED=false.
- Deploy exactly one Machine explicitly (`--ha=false`; Fly's deploy HA defaults can otherwise
  create more than one). Confirm TLS host/health, rejected unknown Host/origin,
  unauthenticated401, authenticated owner isolation and saved-trip continuity.
- The existing Render background startup failed JOB_STORAGE_UNCONFIRMED. Merely
  moving providers is NOT a proven fix. Diagnostic-only commits9576c20/53922be are
  still unpublished after approval-review denial and intentionally NOT included
  in this main-based candidate. Resolve publication/diagnosis and verify scoped
  pooled TLS/role/schema/cleanup from Fly before enabling background flags.
- Background activation still requires every existing explicit retention/schema/
  cleanup/worker/credential flag and successful startup guard. Do not bypass it.
  No paid model call is included; actual generation needs separate acceptance.
- After successful backend acceptance, change Vercel's approved API base setting,
  rebuild, verify login/saved-trip/initial-planning UI and monitor rollback. Retain
  Render until cutover is proven; don't run duplicate background consumers during
  migration without deliberate coordination (leases prevent duplicate claims,
  but concurrency and process-local quotas still need review).

## Offline evidence and limits

20 focused deployment/production-boundary tests pass with fake configuration,
no dotenv reads and no network/provider calls. Tests verify Python-only/non-root
entrypoint, one worker, port alignment, no secret config, Host-aware health probes,
auth/CORS enforcement and fail-closed unverified setup. TOML parses with Python's
standard library. Docker/flyctl are unavailable here: no image build, official
Fly config validation, remote networking, live auth or performance proof claimed.
No live-source fetching is enabled. Only initial generation is resumable.

Official references checked 2026-10-27:
- https://docs.fly.io/reference/configuration
- https://docs.fly.io/python/frameworks/fastapi
- https://docs.fly.io/about/pricing

The `Fly backend container` CI workflow builds the actual Dockerfile and starts it
with synthetic configuration and `--network none`, verifies UID10001/health and
disabled jobs, then removes it. It also executes the pinned Moby matcher against
synthetic secret/cache/data paths. Its first remote CI run is pending publication;
none of these tests copies real credentials or contacts Supabase/OpenAI.
