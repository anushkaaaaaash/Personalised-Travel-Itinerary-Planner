# Disposable planning queue SQL checks

No credentials or application database connection are needed for the portable test:

```sh
npm ci --prefix backend-python/tests/sql --ignore-scripts --no-audit --no-fund
npm test --prefix backend-python/tests/sql
```

The test-only package pins PGlite **0.5.12**, including its registry integrity lock.
It is isolated from runtime/workspace dependencies and executes the review-only
migration in memory. PGlite is **single connection**: this verifies SQL syntax,
permissions, state transitions and sequential CAS, not concurrent worker safety.
`PLANNING_SQL_TEST_MODULE` remains an optional explicit module-path override.

`.github/workflows/planning-sql.yml` provisions a fresh PostgreSQL 17.11 service and
runs `planning_jobs_postgres.py` with independent psql connections. It covers
concurrent claims, a separately locked row being skipped, and cancellation beating
a stale-worker CAS. The script refuses non-loopback hosts and databases other than
`planning_queue_test`, applies the migration to that disposable database, and
truncates its queue during testing. Never run it against real application data.
No Supabase project or production migration is touched by these tests.

The real-PostgreSQL CI job must pass before treating concurrency as verified;
a local PGlite pass alone does not establish that result.
