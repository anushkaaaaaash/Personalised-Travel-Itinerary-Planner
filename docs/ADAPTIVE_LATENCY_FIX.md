# Adaptive planning latency and travel-day recovery

Local candidate, not a live-speed measurement.

## Observed issue (2026-10-27)

The supplied screenshot shows six of nine days accepted, followed by a paused
constraint proposal. It is not a table waiting to render. The proposal cites
an international return day conflicting with the mandatory fast-pace minimum,
and a generated route summary conflicting with the structured return endpoint.
Successful production provider timings were not logged, so the exact earlier
wait cannot be apportioned retrospectively. Coarse Fly metrics did not show
memory pressure or sustained CPU load.

## Small changes

- Adaptive background generation uses GPT-6 Luna `low`, rather than `xhigh`.
  Official model documentation confirms support:
  https://developers.openai.com/api/docs/models/gpt-6-luna
- Ask for concise prose without removing dates, cost categories, transit/rest,
  uncertainty warnings, or owner-isolated durable checkpoints.
- Original arrival/return dates may contain fewer main activities only with at
  least 120 minutes of explicit transfer entries. This is an estimated schedule
  rule, not verification of actual flights, availability, or time zones. Ordinary
  sightseeing dates and intermediate section boundaries retain the pace rule.
- Structured route stays and the explicit final return take precedence over
  descriptive route-summary prose. Accepted route data is not silently changed.
- Paused work is labeled paused rather than appearing to keep loading.
- Nonthrowing diagnostics report create acknowledgment duration, elapsed time
  from submission to observed terminal provider state (including polling/queue
  overhead), and local validation duration. No IDs, prompts, outputs or keys.

The 32,768-token ceiling is retained: a maximum is not a request to fill it.
Blindly reducing it can truncate otherwise valid plans and create more failed
work. Three-day sections, twelve submissions per explicit run, no automatic
retry, and all existing cost/storage/concurrency bounds remain unchanged.
Legacy synchronous refinement remains unchanged. No paid acceptance calls were
made and no numerical speedup is promised by the offline tests.

## Release safety

Do not interrupt an active provider submission to deploy this patch. The fixed
read-only pre-deploy probe reports only counts of active plans and queued,
submitting, or running sections. It must report zero before deployment. Because
this is a point-in-time probe rather than an admission lock, the operator must
also coordinate a short no-new-submissions window. Paused plans are retained;
this release does not cancel, restart or regenerate them automatically.

The existing paused model-proposed constraint can be retried explicitly using
one remaining request in the same run: accepted sections, route, and remaining
budget are retained. This applies only to known terminal failures with validated
`applicability=proposed` details on the active SQLite transport. It does not
retry uncertain submissions, exhausted budgets, or unverifiable errors, and
never starts automatically. The inactive PostgreSQL alternative remains gated
by its existing retry policy; no previously applied migration is modified.

The quiescence gate is for this already-initialized SQLite deployment. It fails
closed when the mounted store is missing, malformed, or inaccessible; it does
not silently bypass the guard for a fresh bootstrap.
