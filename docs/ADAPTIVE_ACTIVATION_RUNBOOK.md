# Adaptive planning: activation and acceptance

Local implementation is not production activation. No new host, broad Supabase
admin key, or user-data migration is required. Keep `ADAPTIVE_PLANNING_ENABLED`
unset/false until every check below passes.

## Approval scope

- Publish the reviewed source, tests and operational documentation to the same
  Anushka repository; merge/deploy only after CI and mobile visual review.
- Apply only additive adaptive checkpoint schema, exact restricted worker grants,
  and named once-per-minute cleanup. Existing saved trips and account data remain
  untouched. Temporary checkpoint retention remains 24 hours; background provider
  retention remains approximately 10 minutes even with `store:false`.
- Provision/rotate the existing restricted worker connection directly into the
  Fly app's `PLANNING_DATABASE_URL`. Never print it or put it in Git/client code.
  Rotation invalidates any old Render copy. Check its old background worker is
  disabled first; do not broaden or transfer a project administrator key.
- Approve the processing resource policy: configurable 1–12 submissions per
  explicit run, three days per section, 16 MiB/session and 64 MiB global temporary
  allocation. These are processing/storage bounds, not a trip-duration cap.
  A 24-day plan ordinarily needs eight sections and fits one default run. Failed
  explicit retries consume the same run allowance. Uncertain creates cannot replay.

## Pricing evidence (checked 2026-10-27)

[Official pricing](https://developers.openai.com/api/docs/pricing) lists Luna
Standard at $0.10/M input tokens and $0.50/M output tokens. A request is bounded to
32,768 output tokens, so twelve requests have at most $0.196608 in the output
component at those rates, **plus input tokens**. This is not a hard total-dollar
cap. Requests explicitly use `service_tier:default`; no search/tools are enabled.
Payloads are byte-bounded; actual usage, price changes and account billing apply.
Paid acceptance tests still require separate explicit approval.

## Ordered rollout

1. Freeze hashes and independently review additive SQL, scoped grants and cleanup.
   Execute the disposable PostgreSQL concurrency suite and synthetic full-stack
   tests; PGlite alone does not prove multi-connection races.
2. After authorization, apply `005_adaptive_section_checkpoints_REVIEW_ONLY.sql`,
   `adaptive_section_worker_grants_REVIEW_ONLY.sql`, and
   `adaptive_section_cleanup_REVIEW_ONLY.sql` via the approved migration workflow.
   Verify no conflicting names, grants, legacy row-count changes or cron failures.
3. Deploy the reviewed code with adaptive generation still disabled, then securely
   provision the restricted connection. No provider call is needed for this step.
4. Run an approved read-only process command inside Fly:
   `ADAPTIVE_PREFLIGHT_APPROVED=true python -m app.adaptive_preflight`.
   It checks TLS, exact effective privileges, the health contract and fresh cleanup
   heartbeat. It never submits a job or calls OpenAI. Output is fixed codes only;
   storage diagnostics log only allowlisted phase/family/SQLSTATE, never DSN/errors.
   If it fails, diagnose that evidence; do not weaken TLS or the role audit.
5. Set existing consent flags only after verifying their actual evidence:
   `OPENAI_BACKGROUND_RETENTION_APPROVED`, `PLANNING_DATA_RETENTION_APPROVED`,
   `PLANNING_WORKER_CREDENTIAL_APPROVED`, `PLANNING_SCOPED_ROLE_VERIFIED`,
   `ADAPTIVE_SCHEMA_VERIFIED`, `ADAPTIVE_CLEANUP_VERIFIED`,
   `ADAPTIVE_WORKER_VERIFIED`, `ADAPTIVE_RESOURCE_POLICY_APPROVED` = `true`.
   Set `PLANNING_WORKER_TRANSPORT=postgres`,
   `ADAPTIVE_PURGE_JOB_NAME=adaptive-section-retention`,
   `ADAPTIVE_RUN_ALLOWANCE=12`, and `ADAPTIVE_PLANNING_ENABLED=true`.
   Keep `PLANNING_JOBS_ENABLED=false`; the two queues must not run separate paid
   concurrency budgets. No browser flag can bypass server readiness.
6. Verify healthy startup, one existing Fly machine, ready capability/policy,
   owner-isolated recovery/cancellation and cleanup heartbeat. Perform a real
   provider acceptance only if separately authorized. Do not call synthetic
   fixture results proof of a successful real itinerary.

## Scope and limits

Initial planning is adaptive; legacy whole-itinerary refinement/save/share retain
existing bounded single-itinerary contracts. Section results are read-only and
paginated; they are not silently concatenated into an oversized legacy payload.
An authenticated whole-plan text download streams accepted checkpoints in bounded
pages, with exact completed-day/cumulative-cost checks and a 24 MiB output bound.
Unfinished trips are clearly marked PARTIAL; the browser saves only after the
completion marker arrives. Download before the 24-hour checkpoint expiry to keep
a local copy. This is not account-backed long-trip Save: that requires a separate
additive saved-manifest/section format and retention approval; existing saved trips
are unchanged. No unfinished dates or provider guesses are silently filled in.
The global route outline is immutable, date coverage and cents are exact, and
location labels/transfer presence/rest gaps/repeated exact activity titles are
checked. These checks do not establish real geographic travel times, availability,
opening hours or live blockers. Prices/routes remain estimates without separately
approved trusted source integration. Model-suggested changes are labeled proposals,
never automatic edits or proof that user preferences caused a provider outage.
