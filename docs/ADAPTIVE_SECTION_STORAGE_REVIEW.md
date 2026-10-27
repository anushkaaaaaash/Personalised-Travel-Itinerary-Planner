# Adaptive checkpoints — offline storage candidate

**Disabled and unapplied.** This candidate does not fix or diagnose the current
production startup-storage failure, and does not establish provider acceptance.

The date range has no policy day cap. A section contains at most three dates;
its accepted result is immutable and stored separately, with exact date coverage,
whole-group cents, start/end location, previous activity end, and fixed validation
provenance. A bounded global journey strategy covers every original date with
contiguous stays, is immutable after the first acceptance, and constrains section
end locations. Exact normalized principal-activity titles cannot repeat across
accepted sections; this is not a claim of semantic duplicate detection. Results are paginated three rows at a time, never joined into a large
stored JSON blob. Failed attempts remain separate; accepted sections are not
regenerated. Uncertain submission cannot be retried automatically or through the
known-failure retry operation. Cancel preserves accepted checkpoints until expiry.

## Explicit resource policy (requires operator approval)

- Default/max run allowance: **12 provider submissions**. A 24-day trip needs eight
  three-day sections and fits one run, absent failures. Known failure retries also
  consume this allowance; explicit continuation grants another bounded run.
- One active/paused plan per owner; 50 globally. These are service admission limits,
  not calendar limits. Completed/cancelled rows still consume retained storage.
- **16 MiB per plan / 64 MiB application-wide** allocation. Reserve 48 KiB per
  manifest, 16 KiB per attempt (including bounded failure proposals), and 128 KiB
  for a pending checkpoint, plus 512 bytes per persisted continuation request. Replace the checkpoint reservation with its actual
  serialized size upon acceptance. Shared transaction advisory locking protects
  reservation admission. Insufficient capacity pauses before starting paid work.
  An explicit retry of shared-capacity checks preserves remaining submissions and
  accepted checkpoints; when still full it creates no control row or allocation, and the same request ID may resume after cleanup frees capacity.
  The per-plan ceiling cannot be bypassed by Continue and never truncates results.
- These allocations are **not measured physical PostgreSQL usage or a verified
  hosting quota**. Index/WAL/engine overhead and other application tables need
  separate deployment capacity review.
- Data expires after 24 hours. An independently approved once-per-minute purge
  deletes manifests and cascades their section/run rows. Health requires a fresh
  purge heartbeat; no cron is activated by the code or migration draft.

## Activation prerequisites

1. Independently review `005_adaptive_section_checkpoints_REVIEW_ONLY.sql`.
2. Review exact adapter RPC mappings and the isolated worker role's table audit.
3. Separately review `adaptive_section_worker_grants_REVIEW_ONLY.sql`; no new
   credentials, role inheritance, BYPASSRLS, or access to auth/trips/saved plans.
4. Separately review `adaptive_section_cleanup_REVIEW_ONLY.sql` and retention.
5. Run actual PostgreSQL multi-connection lease/reservation tests. PGlite proves
   SQL execution but is single-connection and cannot establish race safety alone.
6. Coordinate one shared provider admission policy if legacy background jobs and
   adaptive sections are ever enabled simultaneously. The isolated draft's two
   active-provider allowance currently covers adaptive sections only.
7. Confirm end-to-end auth, recovery, pagination, cancellation and real-provider
   behavior in an explicitly approved environment before any production claim.

Get/read responses include `expires_at`; public APIs must report expiration and
must never expose provider response IDs, raw preferences in log messages, or
lease tokens. A generic user-facing failure is not evidence of a provider cause.
