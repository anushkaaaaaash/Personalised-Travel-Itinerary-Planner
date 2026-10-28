# Account trip copies — local reconstruction review

## Scope and status (2026-10-28)

This is a reviewed local reconstruction of the lost account-save slice, not a
claim to reproduce the bytes or commit identity of the earlier `e26f50c` build.
The baseline is GitHub main `30df54d2d223025e627d916904f77357a8a93643`:
all 403 file blobs were verified and its tree is exactly
`58dae7a3531ed433eea829921594e130c63cb7ee`.

Nothing in this work has been published, deployed, migrated into Supabase, or
used to initiate a paid provider operation. Existing user data is untouched.
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
function, not the tables. FORCE owner RLS and `auth.uid()` checks remain active.
The function has an empty search path and no dynamic SQL. Direct authenticated
schema/table/helper access, role membership, and PUBLIC/anon execution are
revoked; only the exact authenticated RPC execution is granted. User routes
forward a verified user JWT with a public key; no service-key fallback exists.

Explicit narrow grants/revokes are intentional: Supabase's October 30 Data API
default-grant change must not determine this feature's security boundary.

## Verification of the reconstructed files

- Clean baseline: 1,528 Python tests passed, 5 skipped before npm test helpers.
- Integrated Python suite: 1,606 passed; 3 native opt-in tests skipped in this
  ordinary run and separately passed on disposable PostgreSQL 17.11.
- Native PostgreSQL: three independent-connection regressions passed for
  same-request deduplication, concurrent account quota admission, and concurrent
  finalize/owner/direct-DML guards. The test refuses non-loopback databases or
  a database name other than `planning_queue_test`.
- Frontend: all 567 tests passed; 27 shared-validation and 81 legacy backend
  tests passed; production build and public-asset check passed.
- Deployment tooling: 22 checkpoint tests passed with mocked operations.
- All three disposable PGlite SQL suites passed (planning, adaptive, archive).
- Independent security review re-ran the archive Python/frontend/SQL tests and
  found no blocker in the current source.

Actual new browser pixels are **not verified**. The synthetic visual harness
could not start Chromium: the sandbox denied its process-singleton socket; the
approval-reviewed execution wrapper failed during restricted-directory setup,
before any page opened. No workaround or further retry was attempted. Run the
synthetic visual CI in an authorized environment before release.

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
