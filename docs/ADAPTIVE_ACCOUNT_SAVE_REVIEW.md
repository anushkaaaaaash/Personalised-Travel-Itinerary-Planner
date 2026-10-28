# Account trip copies — local reconstruction review

## Scope and status (2026-10-28)

This is a reviewed local reconstruction of the lost account-save slice, not a
claim to reproduce the bytes or commit identity of the earlier `e26f50c` build.
The baseline is GitHub main `30df54d2d223025e627d916904f77357a8a93643`:
all 403 file blobs were verified and its tree is exactly
`58dae7a3531ed433eea829921594e130c63cb7ee`.

The local reconstruction performed no publication, deployment, Supabase migration,
or paid provider operation. Subsequent PR publication was handled separately by
the release owner. Existing production user data remains untouched.
The SQL proposal remains REVIEW_ONLY and both activation flags default off.

## Safety contract

- A complete adaptive trip is copied as a manifest, individually bounded
  sections, and historical source notes. No 14-day flattening or truncation.
- An explicit Save request copies at most three accepted sections per POST.
  A stable owner/request/source/version identity allows read-only lookup after
  uncertainty; an unknown result never causes a blind new save.
- Only finalized copies are listed/reopened. Reads use the account archive,
  independently of the temporary planning source and its expiry.
- Logical canonical-content reservations are limited to 16 MiB per copy and
  64 MiB per owner. These are not physical database disk quotas. Owner advisory
  locks serialize concurrent quota admission and request deduplication.
- Unfinished staging lasts 24 hours. Only an explicit new save, after an absent
  request lookup, invokes cleanup of at most 100 expired staging copies owned
  by that account. Complete copies are never automatically cleaned up.
- Explicit confirmed Delete targets the account copy and version only. It never
  deletes or modifies the temporary source plan. Uncertain deletion is checked
  with a read, not automatically repeated.
- Browser recovery stores opaque identifiers only, never titles/preferences or
  trip content. Sign-out/owner changes prevent applying another owner's result.
- Historical source notes require the exact recorded section/research link and
  owner/plan binding; never attach the newest research as a substitute. Revision
  copies without a recorded link say `none_recorded`. Retained notes are marked
  `historical_unverified`, not current facts or verified bookings.
- Hashes establish consistency, not server provenance. Archive content remains
  untrusted owner content and is revalidated by the application when reopened.

## Database boundary

`docs/adaptive_saved_archive_REVIEW_ONLY.sql` adds a private `adaptive_archive`
schema and one fixed `public.adaptive_saved_archive(text,jsonb)` RPC. It does not
change the legacy saved-itinerary table or its 14-day contract.

The RPC uses a fresh restricted NOLOGIN/NOINHERIT/NOBYPASSRLS role that owns the
function, not the tables. FORCE owner RLS and verified JWT subject checks remain
active. A private INVOKER helper implements the inspected `auth.uid()` semantics
(direct JWT-sub GUC, then claims JSON `sub`); payload and user metadata never
establish ownership. This avoids asking the hosted migration actor to delegate
auth-schema privileges it does not hold with grant option.
The function has an empty search path and no dynamic SQL. Direct authenticated
schema/table/helper access, role membership, and PUBLIC/anon execution are
revoked; only the exact authenticated RPC execution is granted. User routes
forward a verified user JWT with a public key; no service-key fallback exists.

The migration supports a non-superuser CREATEROLE actor: within its transaction,
it temporarily enables SET-only creator membership and grants the new role
CREATE on `public` solely for ownership transfer. Function ACLs are set before
transfer; CREATE and effective SET/INHERIT privileges are removed before commit.
PostgreSQL may retain bootstrap-granted ADMIN-only creator metadata for the
trusted migration actor. This is not runtime access: tests require effective
SET/USAGE false and no anon/authenticated membership. That privileged actor can
administer/regrant roles, as it already administers the schema and tables.
Removing this administrative metadata requires a privileged operator and is
optional hardening, not an assertion made by this migration.

Explicit narrow grants/revokes are intentional: Supabase's October 30 Data API
default-grant change must not determine this feature's security boundary.

## Verification of the reconstructed files

- Clean baseline: 1,528 Python tests passed, 5 skipped before npm test helpers.
- Integrated Python suite: 1,606 passed; 4 native opt-in tests skipped in this
  ordinary run and separately passed on disposable PostgreSQL 17.11.
- Native PostgreSQL: three independent-connection regressions passed for
  same-request deduplication, concurrent account quota admission, and concurrent
  finalize/owner/direct-DML guards. The test refuses non-loopback databases or
  a database name other than `planning_queue_test`.
- Frontend: all 567 tests passed; 27 shared-validation and 81 legacy backend
  tests passed; production build and public-asset check passed.
- Deployment tooling: 35 checkpoint/CI-runner/activation tests passed with mocked operations.
- All three disposable PGlite SQL suites passed (planning, adaptive, archive).
- Independent security review re-ran the archive Python/frontend/SQL tests and
  found no blocker in the current source.

The local browser harness could not start Chromium because of runtime socket and
execution-wrapper restrictions. This was not worked around. The authorized PR33
visual CI subsequently passed at head `71ec9c05bb37fc59cdad27b17cb5a8c38fd7a11f`
(tree `3f4c0dffa4e58045b15723f312039d85b3e5e970`). Independent inspection accepted
10 new mobile/desktop Save, saved collection/detail, and Delete-confirmation
captures. The run recorded 87 screenshots, 60 themes, and zero runtime,
unexpected-request, or readiness errors. Artifact ID: `12792051346`, run
`40631401483`. The release-preflight corrections below do not alter frontend or
shared files; exact equality was checked. Fresh CI remains required for the
corrected release commit.

## Release gates (not performed here)

1. Review/publish only with explicit authority; preserve the source tree and
   rerun required CI on the exact release commit, including visual fixtures.
2. Obtain explicit approval for the additive SQL migration. Inspect current
   grants and existing objects first; the proposal intentionally rejects a
   conflicting role/schema rather than replacing unrelated objects.
3. Verify RPC privileges/RLS with two synthetic owners and no service-role
   fallback in an authorized test environment. Retain existing account data.
4. Only after schema and application verification, authorize deployment and
   explicitly set both `ADAPTIVE_SAVED_TRIPS_ENABLED=true` and
   `ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED=true`.
5. Verify Save/reopen after the source closes, pagination beyond 14 days, owner
   isolation, historical labels, ambiguity recovery, and confirmed Delete.
   Disabling the two flags must not delete stored copies or roll back tables.

Offline commands: `python -m pytest -q -c backend-python/pytest.ini
backend-python/tests`, `npm test`, `npm run build`, and
`npm test --prefix backend-python/tests/sql`. Native SQL tests require the
explicit disposable loopback URL described in `backend-python/tests/sql/README.md`.

## Release-preflight corrections

The first PR CI run exposed a Docker bridge-address mismatch in the native test
guard, not a reason to relax it. `run_native_ci.sh` now starts digest-pinned
PostgreSQL 17.11 with host networking but listens only on `127.0.0.1:55432`, uses
tmpfs data, and always removes its run-scoped container. It checks the actual
database/address before test DDL and strips service-file libpq overrides. The
standalone legacy harness now pins and checks the address too. Local shell and
mocked cleanup tests pass. Actual Docker execution subsequently passed in
PR33 run `40632717976`, job `122632587993`, at exact head
`8dc079b820ab54e43f39424af0a51f1e7f444831`: all queue concurrency checks and
four archive/restricted-migration cases passed. All four workflows were green
for that head; later changes still require their own exact-commit CI.

The hosted read-only privilege preflight also exposed the non-superuser and
auth-schema grant limitations addressed above. A separate native regression
creates a disposable child database and a hosted-like restricted migration
actor; it validates migration success and final privilege/ownership invariants.
No hosted schema was changed to diagnose or test these corrections.

Corrected migration and runner validation: on a fresh disposable PostgreSQL17.11
cluster, the existing queue concurrency checks and all four archive/native
restricted-migration tests passed together. The SQL proposal SHA256 is
`15a3762db3abe42bdb0533dc06063c9a89befbe1f6c262235f0cb072a7e9985a`.
Independent security review approved this exact SQL. The migration regression
also verifies an injected precommit failure rolls back role/schema/grant changes.

## Explicit deployment activation

Checked-in Fly configuration and the `stage` deployment action explicitly keep
both archive flags false. The `activate` action sets both true only after an
offline dispatch gate passes: `saved_archive_schema_verified` must be explicitly
true and `verified_saved_archive_sql_sha256` must match the exact checked-in SQL.
The confirmation defaults false. Missing/mismatched values stop before any Fly
operation. Stage and checkpoint-upgrade actions do not require this attestation.

This is an operator attestation, not automated proof of hosted database state.
The release owner must separately apply the authorized migration and verify its
catalog, ownership, RLS, grants, and owner isolation before supplying the inputs.
No deployment action runs the Supabase migration. The name-only Fly secret guard
rejects both archive flag names so secrets cannot override the reviewed state.
Existing exact-main-SHA, one-Machine, volume, and quiescence checks are unchanged.
