> Current status update: temporary private job storage and background retention were
> approved at 2026-10-27 05:22 UTC. Connected execution remains parent-owned after
> final checks. See PLANNING_ACTIVATION.md for the current guarded production path.
> Initial generation only is resumable; refinement/recommendations remain synchronous.
> Earlier default-off checkpoint descriptions below are implementation history.

# Travel product rebuild — local implementation, not deployed

Baseline: main `536d500e3d8639ebc998ee33950427f5ceecf73d`.

## Product decisions

- One ordinary flow: trip details → useful waiting experience → daily plan → edit/save.
  JSON import and raw prompts belong outside the ordinary traveler journey. Existing
  stored documents and compatibility code are preserved.
- Clean copy, no model/provider or save-status boilerplate in normal headings.
  Practical uncertainty must still be visible at the decision it affects.
- Motion communicates navigation and progress, honors reduced motion, and never
  fakes a percentage or claims an operation that has not happened.
- Verified observations require real provider provenance, timestamps and matching
  destination/date/subject. Missing coverage is **not** evidence of no blockers.

## What the audit actually found

The backend validates structured dates, budget, activity count and chronological
schedules. Those checks do not establish opening hours, route feasibility or current
closures. The original provider HTTP request can fail before response headers after
180 seconds. A longer browser timer or an in-memory task cannot fix that underlying
failure. Acceptance of `gpt-6-luna` with `max` remains a live verification question.

## Async implementation slices

1. `planning_jobs.py` + `planning_routes.py`: authenticated, default-off local
   preview with injected generation, bounded memory, owner-scoped request identity,
   cancellation race protection, result validation and expiry. **Not durable**;
   never enabled in production, no default paid generator.
2. `planning_repository.py`: real fixed-resource Supabase REST gateway, durable
   owner/request dedup, ambiguous-insert reconciliation, lease-based atomic state
   changes and safe output projection. Credentials are explicit server constructor
   inputs; no credential reads at import.
3. `003_planning_jobs_REVIEW_ONLY.sql`: unapplied private table and service-only
   RPCs. No browser direct writes/reads of provider IDs, inputs or leases. Claims
   use transactional admission and SKIP LOCKED. A lease lost during submission
   produces `submission_unknown`, never another paid create.
4. `planning_worker.py`: injected durable worker tick. Persist submitting BEFORE
   provider create, persist response ID BEFORE polling, resume that ID after a
   restart, reject stale/cancelled writes, decode the existing strict generation
   contract and validate the complete result. Eight-minute execution ceiling is
   distinct from data retention. No background loop starts on import.
5. `openai_background.py`: opt-in background Responses transport (separate worker
   implementation). `store:false` does NOT eliminate temporary background response
   retention. No model downgrade or alternate provider.
6. `travel_evidence.py`: strict pure assessment of trusted records, no invented
   live lookup. The current product has no newly enabled live-data provider.
7. `planningJobs.js`: default-off browser transport contract, no automatic create
   retries, clean error mapping and response identity/result checks. Not wired to
   ordinary users before end-to-end activation acceptance.

## State and recovery rules

- Duplicate click/reconnect uses the SAME request UUID and unchanged preferences.
  Changed input with that key is a 409; deliberate new attempt uses a new UUID.
- Browser disconnect is NOT cancellation. Explicit cancellation invalidates the
  database result; upstream cancellation is best effort, costs may still occur.
- Crash before provider response ID is persisted is inherently ambiguous. Do not
  claim exactly-once provider billing or silently retry it.
- Claim → submit uses a 60-second lease. Running transitions release the lease;
  the next polling tick claims it anew. Queue/RPC activation requires real database
  concurrency verification; fake gateway tests do not prove SQL execution.
- Worker tick may run in the existing Render process after approval. A sleeping
  or restarted free instance does not provide always-on execution. Requests can
  resume polling the stored response ID after wake, only within the provider's
  retention/execution window. Longer suspension must end as expired, not rerun.

## Activation decisions and remaining gates

As of the local checkpoint no push, DB migration, paid generation or deployment occurred; parent records any later connected execution separately.
Required before turning on the real path:

1. Approve the private queue migration and temporary preference/result storage.
   Proposed retention target is 24 hours, NOT a current deletion guarantee. SQL
   expiry hides output but does not itself delete rows. Configure and verify an
   approved database-side scheduled purge (e.g. existing Supabase Cron if enabled),
   including job monitoring and actual deletion; app sleep cannot be the purge
   mechanism. Do not activate on a promise of lazy cleanup.
2. Approve OpenAI background temporary retention (~10 minutes even with
   `store:false`), and one bounded paid model/structured-output acceptance check.
3. Explicitly configure the production factory with the tested injected durable
   coordinator and worker lifespan, then enable routes after approval. The local
   preview includes authenticated start/read/request-ID recovery/cancel and a
   five-second polling loop; production activation now requires all approval/verification flags plus live schema/cleanup health (see activation runbook).
   Keep current synchronous routes unchanged until rollout acceptance.
4. Validate the draft against hosted Supabase after approval, including concurrent
   workers, grants/PostgREST, and actual purge monitoring. Local PostgreSQL-WASM
   execution already covers schema/RPC syntax, denied browser roles, deduplication,
   owner cancellation, CAS/lease recovery and atomic owner admission. This does not
   prove hosted configuration or multi-process behavior.
5. For actual current blockers, approve a bounded source-grounded lookup path;
   source provenance must come from transport observations, not model-authored URLs.
6. Independent review, full offline suites/build, draft publication only when
   authorized, then live smoke tests for the exact deployed revision.

No new paid worker, encryption key, repository, fork or external secret destination
is inherently required by this design. Platform private storage remains the existing
Supabase trust boundary. New paid infrastructure needs separate approval if later
shown necessary.

## Offline verification evidence

- `tests/sql/planning_jobs.mjs` executes the draft on isolated PostgreSQL-WASM
  (PGlite 0.5.12), with fake auth role/schema setup; not a mocked SQL string test.
  Package installed only under `/tmp/travel-sql-qa`, never in app dependencies.
- `test_planning_integration.py` covers actual HTTP routes, authenticated owner
  isolation, request-ID recovery after a lost create response, real repository and
  background client over fake HTTP transports, worker recreation, and planned /
  infeasible validated outcomes. Exactly one provider create occurs in each case.
- Production Supabase project read-only discovery found `pg_cron` available but
  not installed. Its installation and schedule need explicit approval. Official
  [Cron documentation](https://supabase.com/docs/guides/cron) describes database-side
  SQL scheduling and `cron.job_run_details` monitoring independent of app uptime.
- Proposed purge after approval: database-side minute schedule removing expired
  queue rows; define a 24-hour plus scheduling-latency policy, alert on failed runs,
  test a synthetic expired row is actually removed. Do not claim exact 24-hour
  deletion without that verified mechanism. Provider temporary retention is a
  separate policy and cannot be enforced by our database purge.
- Admission defaults: maximum 1000 retained rows, 100 queued/active/uncertain jobs,
  two queued/active/uncertain per owner, twelve creates per owner per 24 hours.
  Uncertain submissions reserve admission; never call this exactly-once billing.

## Evidence lifecycle

The job response has a separate server-owned `evidence` envelope, not writable
itinerary fields. It is bound to the entire validated result by a cross-language
SHA256 typed-value representation (IEEE754 numeric bytes avoid exponent-format
mismatches). Only trusted adapter assessments populate it; source research prose
cannot self-promote. Freshness and exact scope are rechecked server-side and in UI.
Any edit/refinement clears it. Current save/share schemas deliberately omit the
private job envelope, so restored/imported plans never inherit counterfeit verified
claims. Preserving refreshed evidence across saved documents requires a separately
reviewed server-owned evidence storage extension; it is not silently client-writable.
