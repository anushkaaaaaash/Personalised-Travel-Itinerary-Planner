# Fly-local temporary planning checkpoints

This replaces only the adaptive checkpoint transport. Supabase authentication and
existing saved itineraries stay unchanged. The previously deployed Supabase
checkpoint tables/cron are not modified or used by SQLite; no database password
rotation or new database credential is required.

## Approved topology and cost

One existing Singapore shared-CPU 512 MB Machine, one encrypted 1 GB volume named
`planner_checkpoints`, mounted at `/data`. No replicas, extra Machine, automatic
volume expansion or snapshot backups. Official Fly pricing checked 2026-10-27:
[$0.15/GB/month provisioned storage](https://fly.io/docs/about/pricing/), billed
independently of the existing compute, provider usage and bandwidth charges.
[Fly volumes](https://fly.io/docs/volumes/overview/) are host-local, one Machine per
volume, and not automatically replicated. Hardware loss can lose planning progress;
replacement/deployment causes downtime. Saved Supabase trips are separate.

[Automatic snapshots can be disabled](https://fly.io/docs/volumes/snapshots/).
Both the volume API setting and `scheduled_snapshots=false` must be verified,
including an empty snapshot list, before storing user checkpoints. No restore is
implemented or authorized. Restoring an old queue could lose submission intents
and replay paid work: never activate a restored copy without separate quarantine
and recovery review. A missing/corrupt/replaced store fails closed, not auto-created.

## Storage and processing invariants

SQLite uses a fixed private file `/data/checkpoints/planning.sqlite3`, owned by
UID 10001, directory mode 0700 and database mode 0600. Normal web/worker execution
remains non-root. Explicit first initialization can run as root solely to create
the private directory, then drops groups/GID/UID before schema creation.

WAL, `synchronous=FULL`, foreign keys and `BEGIN IMMEDIATE` protect committed
submission intents, atomic claims/leases/CAS and idempotency across processes.
No transaction spans a provider await. Blocking database work runs off the event
loop, with bounded lock/query waits. There is no fallback to RAM or ephemeral disk.
SQLite has no PostgreSQL RLS: ownership is enforced by the fixed repository
operations and tested per-owner predicates. The server process can access the
checkpoint database; it is not exposed to browser SQL or a public database port.

The existing limits remain: 3 days/section, up to 12 submissions/explicit run,
16 MiB per plan and 64 MiB global logical allocation, bounded control records and
pages. No total trip-day cap. Actual file/WAL overhead is separate; disk-full and
busy states fail closed without automatic provider retries.

Expired records are denied on reads. Startup cleanup precedes readiness and runs
every 30 seconds while the adaptive process is healthy. Secure deletion plus
successful WAL truncation is required before its cleanup heartbeat becomes fresh.
This is **not** guaranteed physical erasure at exactly 24 hours: cleanup pauses
while the Machine is down or adaptive processing disabled, and resumes before
readiness on restart. No forensic NVMe-erasure claim is made. Snapshots are off.

## Guarded rollout (existing app-scoped token, no token extraction)

1. Merge only after unit, real-file/multiprocess, HTTP contract, container and UI
   checks. Container CI initializes an actual mounted test volume, restarts the
   image and proves ready capability with network disabled and zero provider calls.
2. Manually dispatch `Provision Fly checkpoint volume` with exact reviewed main
   SHA. It accepts exactly one existing approved Machine and zero volumes, sends
   one create request, then verifies exact attributes/snapshot state. An uncertain
   create is never retried automatically: inspect current volumes first.
3. Dispatch `Deploy Fly backend`, `deployment_action=stage`. It verifies the
   existing volume before deployment, mounts it with processing disabled, then
   verifies exactly one Machine with the correct attachment. No automatic new
   volume is an approved recovery action.
4. Dispatch the same workflow, `deployment_action=initialize`, once. A fixed
   Machines API exec invokes `app.adaptive_sqlite_preflight --initialize` with
   command-scoped approval flags. It cannot overwrite an existing file. API exec
   identity/permission must be proved on the live app; failure does not authorize
   SSH certificate creation, broader tokens or a privilege workaround.
5. Dispatch `deployment_action=activate`. A fixed preflight performs only scoped
   expiry maintenance and schema/health checks, never model calls. Only after it
   succeeds does deployment set the reviewed SQLite consent/readiness flags and
   run allowance. Other background transport stays disabled. No secrets are
   changed; explicit deployment environment flags control processing state.
6. Verify healthy startup, actual mounted file ownership, one Singapore Machine,
   snapshots disabled, `adaptive_planning_enabled=true` and policy 3/12. Confirm
   persistence through the initialization-to-activation restart. A real itinerary
   generation test remains a separate paid action requiring approval.

Future deployments must explicitly choose `activate` to retain processing, or
`stage` to disable it. The committed default is disabled. Neither volume creation
nor store initialization is an automatic retry or part of ordinary deployment.
