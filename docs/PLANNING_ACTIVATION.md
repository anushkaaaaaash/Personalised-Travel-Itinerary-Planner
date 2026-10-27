# Initial-plan background activation runbook

User approved the private temporary queue, 24-hour cleanup and OpenAI background
retention at 2026-10-27 05:22 UTC. No paid acceptance call, paid search, new hosting,
account settings change or saved-trip modification is included. Parent executes
connected DB actions only after final tests/review; this file is not evidence they
occurred.

## Additive database rollout

Target: confirmed project `rmrwxhzlmtfdrkxlkwqs`. Preserve `trips`,
`saved_itineraries`, their rows, policies and users. Do not run existing migrations
001/002 or destructive rollback.

1. Record schema/table counts without reading user content. Confirm no
   `planning_jobs`, functions with these names, or Cron job `purge-planning-jobs`.
2. Apply reviewed `backend-python/migrations/003_planning_jobs_REVIEW_ONLY.sql`
   using the connected migration tool and a descriptive new migration identity.
   This single transaction creates only the queue, indexes, service-only invoker
   functions and denies anonymous/authenticated direct access.
3. Review/apply `docs/planning_cleanup_REVIEW_ONLY.sql`: enables available
   `pg_cron` and registers one named minutely SQL purge. Check existing name first;
   `cron.schedule` updates same-name jobs rather than creating a second one.
4. Read `cron.job` and verify active, schedule `* * * * *`, exact purge command.
   Wait for `cron.job_run_details` success for this job. Do not set the verification
   flag merely because `cron.schedule` returned an ID.
5. Test logical deletion of a synthetic expired queue row with a reserved UUID,
   under a confirmed test owner (not a new user or a real saved trip). Confirm that
   row is gone after the scheduled run, and unrelated saved-table counts unchanged.
   If no authorized test owner exists, ask before creating a user; do not invent
   one or use a random real owner's row.
6. Confirm anonymous/authenticated roles cannot read queue rows or execute queue
   mutation functions. Confirm service-only queue-health RPC returns versions1/1
   and `cron_installed:true`, `cleanup_fresh:true`. Execute duplicate/CAS/owner checks using synthetic
   data only. Remove synthetic records, never real travel history.

The policy is logical removal after 24 hours plus up to one minute scheduling
latency during healthy database service; monitor failed purge jobs. Platform
backups follow the existing provider policy, not this row-expiry mechanism.

## Explicit server composition (disabled until all checks completed)

Use existing Render process; no new paid worker is inherently needed. Preserve
OpenAI `gpt-6-luna` / `max`. Factory reads only explicitly supplied process env,
not workstation `.env` files. Server composition needs `OPENAI_API_KEY`, `SUPABASE_URL` and a privileged
queue-worker credential. Do NOT assume `SUPABASE_SECRET_KEY` exists in production.
Current saved-trip operations use a publishable key plus user JWT; they must keep
that boundary. No administrative credential has been retrieved, copied or configured.
Never expose server secrets under VITE_ names.

Required flags (all exact `true`, no defaults):

- `PLANNING_JOBS_ENABLED`
- `OPENAI_BACKGROUND_RETENTION_APPROVED`
- `PLANNING_DATA_RETENTION_APPROVED`
- `PLANNING_SCHEMA_VERIFIED`
- `PLANNING_CLEANUP_VERIFIED`
- `PLANNING_WORKER_VERIFIED`
- `PLANNING_WORKER_CREDENTIAL_APPROVED` (separate action-time permission required)
- `PLANNING_PURGE_JOB_NAME=purge-planning-jobs`

`production.py` composes only a durable repository/client/coordinator. Missing
flags/config fail startup; missing schema/RPC/Cron or a purge heartbeat older than
three minutes fails lifespan before serving. The database-only single-row heartbeat
contains no trip content; each successful purge updates it. New submissions and
worker ticks recheck it, so stale cleanup stops further generation.
There is no in-memory fallback. Fixed-code worker warnings signal unconfirmed ticks.
The five-second loop resumes known provider IDs after restart, with an eight-minute
execution ceiling. Render free-tier sleep means this is not always-on delivery;
missed provider retention windows expire, never create again automatically.

The production frontend selects jobs only from `/api/auth/config`'s strict
`planning_jobs_enabled:true`. Missing/false/failed configuration stays off; there
is no new Vercel environment setting. Capability reflects a running durable
coordinator and recent cleanup/schema health, with no public request opening a DB
connection. The VITE preview flag is development/test-only, never production authority.

## Scope and evidence

Only **initial itinerary generation** is resumable. Refinement/recommendations
remain synchronous. No live source fetch is activated. Optional web research
requires separate cost consent and its citations alone never become trusted
closure/opening facts. Trusted injected facts can block infeasible plans and are
returned in a separate server-owned digest-bound evidence envelope. Edits/refinement
invalidate it; save/share/import schemas do not accept verified claims, preventing
client-provided evidence from being laundered into a trusted saved plan.

## Tests versus unverified external stages

Offline Python/frontend/build, fake-provider HTTP end-to-end, and pinned PGlite
SQL execution run locally. The new disposable PostgreSQL CI concurrency test is
not yet run until authorized publication/CI; PGlite is single-connection and not
proof of cross-process locking. Hosted grants/PostgREST/Cron, exact model acceptance,
paid latency and real-source accuracy require their own explicit verified results.

## Earlier credential option — rejected for this rollout

The REST gateway remains a testable implementation, but its queue-only code does
not narrow a Supabase administrative key's underlying privileges. No broad
project key is approved or selected by production. The approved scoped database
role below supersedes that option; there is no automatic REST fallback.

## Approved scoped-role path (supersedes service-key option above)

At 2026-10-27 05:30:57 UTC the user approved creating a restricted database login
and storing its connection secret only in Render. **No broad project admin key is
approved or used.** The production factory now exclusively selects the scoped
Postgres gateway, requiring `PLANNING_WORKER_TRANSPORT=postgres`,
`PLANNING_DATABASE_URL` (server secret), `PLANNING_SCOPED_ROLE_VERIFIED=true` and
all earlier activation/retention checks. Optional `PLANNING_DB_SSLROOTCERT` selects
an approved CA file; default is the system trust store. TLS stays verify-full.
Psycopg and its binary wheel are exactly pinned3.3.6; no fallback weaker TLS.

1. Review/apply `docs/planning_worker_role_REVIEW_ONLY.sql` separately. It creates
   NOLOGIN, NOINHERIT, NOBYPASSRLS, no elevated role attributes, and permissions only
   on queue/runtime tables and fixed invoker RPCs. Existing user/trip tables and
   their policies remain untouched. A role-name conflict requires inspection,
   never dropping/replacing an existing role.
2. Before enabling LOGIN, audit effective role privileges including PUBLIC table
   and column grants, schema access, memberships and executable SECURITY DEFINER
   functions. The application role audit is defense in depth, not proof that no
   indirect privilege exists. Do not broadly revoke PUBLIC permissions used by
   the rest of the app to make a test pass; surface unexpected inherited access.
3. Obtain exact project Connect/pooler metadata from the authenticated provider.
   Do not invent a regional hostname. Render outbound IPv4 requires the shared
   pooler unless an already-approved IPv4 direct endpoint exists. Use the custom
   role username with exact project suffix and the provider-specified port.
4. Parent provisions a high-entropy password and enables LOGIN only through an
   approved secret-safe runtime/control path, with value echo suppressed. Neither
   password nor complete DSN belongs in SQL migration history, source, artifacts,
   chat output or screenshots. Do not reuse the project's admin password. Transfer
   only the restricted DSN to the existing Render backend's secret env control.
   If the available controls cannot suppress values/retain them safely, pause and
   request user handoff instead of printing or persisting the secret locally.
5. Validate TLS hostname/CA and actual Render connectivity using that restricted
   identity, queue-only access, denied saved/auth reads, schema and cleanup health.
   No OpenAI paid request is needed for these checks. Mark role/worker verified
   only after them. Keep generation off until exact backend/frontend deployment
   acceptance, and paid model testing requires its separate approved scope.

Primary connectivity references: [Render's Supabase guide](https://render.com/articles/how-to-connect-a-render-service-to-supabase-postgres)
and [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Execution checkpoint from parent

Parent reported the frozen queue migration applied at approximately05:32:22 UTC
and cleanup migration at05:32:54 UTC on2026-10-27. Exact file hashes remain:
queue `a5f3821646663bc14031e3dcedcfd0d438f6c16d3562c5f8106d0b2d86b45456`,
cleanup `bd38164dfe0d88b2eeb09a0d588af8aa2eeb746fa1cf746ba7446c784335661b`.
Hosted grant/Cron verification belongs to parent; do not infer it solely from
successful migration. At this checkpoint the scoped role/password/Render secret
and model acceptance remain unverified; source contains no generated credentials.

Request-key deduplication lasts only while its private queue record is retained.
After purge, clients must not blindly repeat an old create: resume uses read-only
request/job lookup and then offers an explicit new planning action. This is not
unlimited exactly-once billing or permanent trip-history storage.

## Final compatibility and verification boundaries

The restricted role is a queue worker with narrow inherited platform-metadata
exceptions, not a claim that PostgreSQL grants literally no nonqueue privileges.
The audit admits only the exact catalog-verified `pg_stat_statements` views and
`pg_cron` job metadata under absent schema USAGE, expected extension ownership,
strict privilege bits and own-user RLS. Cron counters permit SELECT only; USAGE or
UPDATE remains forbidden even without schema USAGE because OID calls bypass name
lookup. Private table/column grants and all executable non-system SECURITY DEFINER
functions remain rejected; reachable application invoker functions must be the six
exact reviewed queue RPC signatures. Metadata exceptions do not grant access to
saved trips or account rows, and no PUBLIC grants were changed.

Parent verified hosted empty-queue purge execution and fresh heartbeat. There is
no known authorized test app owner, so no synthetic auth account or committed test
trip was created. Actual expired-row deletion was proved only in the isolated SQL
fixture. Scoped TLS/role connectivity is a guarded deployment-startup check still
required; local executor network resolution is not evidence of Render reachability.
