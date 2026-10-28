# Bounded planning recovery review (local only)

## Goal and safety floor
Reduce avoidable manual retry prompts without promising unlimited generation,
resetting request allowance, duplicating uncertain paid requests, losing accepted
days, or changing provider data retention. No production or paid-provider testing
is part of this change.

## Same-response continuation
Grounded generation now checks a known response ID for up to a 30-minute local
ceiling (research retains its separate existing limit). The original submission
timestamp is preserved across polling/restart. A final GET precedes deadline
cancellation, so an already-complete valid response is not discarded simply
because a timer elapsed. Transient GET errors preserve the same identity; 404
stops without issuing a new create. At the ceiling, nonterminal work is marked
failed and cancellation is attempted; uncertain cancellation never permits an
automatic replacement.

This is not a 30-minute provider availability guarantee. Current OpenAI background
[documentation](https://developers.openai.com/api/docs/guides/background) describes
roughly ten minutes of temporary polling retention for `store=false`. The existing
`store=false` setting is unchanged. We do not silently enable longer provider
retention. A provider response can become unavailable before the local ceiling.

## One narrowly qualified automatic replacement
The full parsed response must have the expected response ID, no refusal, and one
of these exact terminal classifications:
- `failed` plus provider error code `server_error` or `rate_limit_exceeded`;
- `incomplete` plus reason `max_output_tokens`.

These fields are documented in the Responses
[API reference](https://developers.openai.com/api/reference/resources/responses/methods/retrieve).
Only fixed server-side classification metadata is retained; raw provider error
messages are neither logged nor exposed. Generic historical failure codes never
authorize automatic replay. HTTP errors, ambiguous submissions, missing responses,
ID mismatch, refusal/content filtering, billing/auth failures, research failures,
malformed/domain-invalid output and constraint conflicts are not automatic-retry
triggers.

For the SQLite runtime, failure and deterministic successor scheduling are atomic.
A durable lineage marker allows at most one automatic replacement, including
through manual/research retry descendants; a smaller replacement cannot reset it.
Output-limit recovery requests one day; transient failure retains the original
bounded work size. A persisted 15-second delay precedes admission. Normal storage,
owner, global paid-work and remaining-create checks still apply; the existing
submitting transition spends the existing allowance. No new allowance is granted.
Accepted checkpoints, dates, journey strategy and committed expenses are unchanged.
Only these proven-terminal failed rows release the conservative uncertain-work
reservation. Generic failures/cancellation/unknown work retain existing protection.

Legacy non-SQLite gateways do not receive the new recovery-specific codes. No
hosted schema migration or provider/model/prompt/output-budget change is needed.

## Browser recovery and complete-day display
UI work is reviewed separately alongside this backend change: only GET status/page
reconciliation may reconnect automatically, never paid create/retry/cancel POSTs.
Completed days must remain visible while later pages or network status load. A
complete PDF and a paginated browser view are not evidence of missing generation;
all retained pages must be loaded and shown without repeating provider work.

## Limits that remain explicit
A permanently unavailable response, failed bounded recovery, exhausted allowance,
research/constraint problems or storage limits can still require attention. These
are not hidden behind an endless spinner. Unlimited completion or lower provider
latency has not been measured or promised.

Late nonterminal failure/cancellation after the old ten-minute submission window
now records a bounded additional ten-minute paid-work hold. This avoids treating
an unconfirmed long-running cancellation as a free global slot. The original
submission timestamp stays unchanged; repeated cancellation does not renew this
hold. Proven-terminal automatic-recovery codes do not need that extra hold.

Backend review independently passed 172 targeted parser, worker, real-SQLite and
streaming tests, including deterministic replay/collision, owner/CAS, cancellation,
late holds, existing accepted data and allowance limits. No source blocker found.

## Final continuous-day and reconnect behavior
The retained-plan and account-saved views now follow all validated read cursors
and append the complete dated itinerary automatically. Empty pages containing
only failed historical rows do not stop traversal. The reader enforces identity,
accepted-frontier/date continuity, monotonic cursors, 24 MiB content and 1,024-read
limits; missing/inconsistent pages stop without silently accepting a truncated
trip. Previously loaded days remain when a later read or recheck fails. Owner,
session and navigation changes cancel/ignore stale responses. This is display
assembly only: server checkpoints, save/export/refinement bodies and paid requests
are not flattened or regenerated.

Transient browser status failures receive three bounded GET-only reconnects with
2/5/10-second backoff. Exhaustion presents an honest check-status action. Create,
retry and cancel POSTs are never automatically replayed. Real-client mounted
fixtures cover the reported first-three-to-all-17-day display, saved long trips,
empty failed-row pages, expired/missing snapshot reads and owner-change races.

## Integrated local verification and release boundary
- Backend: **1,681 passed, 4 skipped** (explicit opt-in native PostgreSQL tests).
- Frontend: **615 passed**; shared validation **27**, legacy backend **81**,
  deployment guards **35**; all three pinned PGlite suites passed.
- Production build, public-asset pattern check, local application/PDF smoke and
  `git diff --check` passed. The PDF smoke is local, not a fresh container result.
- Independent backend and UI source/safety reviews found no blocker; targeted
  tests independently exercised recovery, retention, identity and all-day reads.
- Synthetic 17-day desktop/mobile browser scenarios are included. Actual new
  browser pixels and exact-head hosted CI are not claimed here.
- Source was restored from Library version 5; its archive SHA256 was
  `5cd4ec017286ca733ef5cbbd9ef3e0668488a3bf74f292b8d9f6f8017e96d214`,
  and the restored baseline tree exactly matched
  `1887bc6499e8c4313fd17cf32d6c6a602956475a`. Local Git ancestry is reconstructed.
- This change is local and unreleased. Prior authorization for a different release
  is not treated as permission to publish/merge/deploy this one. No production
  database changes, paid test calls, retention expansion or quota increase occurred.
