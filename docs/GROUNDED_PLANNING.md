# On-demand research, progressive drafts and selected-day edits

This release does not build a destination database or download websites into the planner. A completed planner response may request one of five fixed research topics (places, hours, transport, bookings, closures). Only then does a separate research request receive the original public destination/dates, and the departure city for transport. Private notes, health/accessibility information and edit instructions are not forwarded as web queries.

## Bounded work and truthful evidence

- HIGH reasoning and strict structured final output remain enabled.
- Each explicitly authorized run allows at most twelve provider creates, including research and revision work. Research reserves four tool calls initially and at most two more; unknown submissions retain their reservation. An explicit new run can renew its disclosed allowance; no automatic paid replay occurs.
- Research stores only bounded returned notes and source/citation metadata (64 KiB pack), never raw HTML or a destination catalogue. Consulted/cited sources are provenance, not a guarantee that each model claim is correct or applicable on the trip date. Receipt/freshness timestamps are not publisher update dates. There is no Maps subscription or verified real-time routing/booking guarantee.
- Each provider response has an eight-minute deadline, not an unlimited whole-trip timeout. Streaming is resumed only from a durably committed cursor on the same provider response. Complete provisional day objects are labelled drafts. Only authoritative final retrieval plus full date, cost, route and timing checks makes a section accepted.
- Accepted sections remain available during failures. Service failures do not imply that the user's budget or dates are wrong. Any suggested preference change needs explicit user confirmation.

## Editing and accounting

A completed retained trip can request one selected-day edit. This edit is one model request and does not launch additional web searches; newly proposed details remain estimates to confirm, not fresh verified facts. The original plan stays unchanged. The candidate is checked against unchanged days, route commitments, adjacent rest, total budget and exact dates. Explicit acceptance creates a new completed retained version with the original expiry; it is not an account-saved trip. Rejection does not change the original. Edits consume the remaining shared run allowance; the initial editing UI reports exhaustion rather than automatically adding another allowance. Ambiguous requests are checked by request identity, never automatically re-posted.

Whole-trip regeneration uses an explicit return to trip details and a new generation, not a covert replacement of an accepted version. Saved account trips remain a separate existing feature.

Expense summaries aggregate canonical accepted checkpoints across all pages, not just visible sections. Costs are whole-group estimates in the selected currency. Partial summaries state accepted day coverage and are not forecasts for unfinished days. A suggested 10% contingency is shown separately, with any budget gap; it does not inflate accepted prices, charge money, reserve funds or silently increase the user's budget.

## Storage and rollout

All new notes, provisional buffers and edit candidates remain on the existing encrypted Fly checkpoint volume, with the existing expiry. No new service, credential, machine or volume is required. Snapshots remain disabled. Expired content is inaccessible; physical cleanup runs while the service is available and does not promise forensic byte erasure. Saved Supabase trips are untouched.

Production starts with schema 1. The reviewed explicit schema-2 upgrade adds research and revision storage without replacing existing plans. No startup migration or reinitialization is allowed. Rollout closes new checkpoint admissions with adaptive/research/streaming disabled, checks aggregate quiescence, upgrades transactionally, verifies the existing volume/schema, then enables reviewed capabilities. Unknown upstream submissions remain quarantined; a database-only check is not proof that upstream work stopped and cannot observe stateless legacy synchronous requests. The user-requested generation pause remains necessary. Rollback after upgrade uses the new schema-aware image with new capabilities disabled, never the old schema-1-only image.

## Acceptance limits

Offline tests use actual SQLite transactions and mocked provider responses. CI browser fixtures use no real accounts or paid provider calls. Passing those checks is not proof of live web-search quality, provider streaming compatibility, live travel prices or generation latency. No paid benchmark is included in this release approval.

### Operator sequence (same tested commit throughout)

1. Obtain the user's generation pause and confirm the exact merged commit passed source review, automated checks and synthetic mobile review.
2. Dispatch the existing guarded Fly workflow with `deployment_action=stage` and that full SHA. It verifies the sole approved volume/machine, rejects secret overrides, checks aggregate local work, then explicitly disables adaptive, legacy background, research and streaming processing.
3. Dispatch `deployment_action=upgrade` at the same SHA. The fixed command is `python -m app.grounded_sqlite_upgrade --path /data/checkpoints/planning.sqlite3 --approve`; a separate `--check` follows. Both use the verified existing volume. Never run initialization, change expiry, delete old plans or repeat an uncertain mutation blindly.
4. Dispatch `deployment_action=activate` at the same SHA only after confirmed upgrade. Readiness must include schema, cleanup, research and revision checks before capability is advertised. Check the public health/capability, exact built frontend assets, single Machine and original volume after deployment.
5. A blocked quiescence/migration/readiness check is a real stop. Do not cancel, discard or re-create user work to force a deployment. Keep the failed run visible and distinguish it from subsequent read-only evidence.

These operator steps do not invoke a model. Real researched itinerary quality and provider latency remain to be observed through a separately authorized user generation.
