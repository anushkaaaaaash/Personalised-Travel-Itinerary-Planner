#!/usr/bin/env bash
# Synthetic CI database only. No credentials or application data are mounted.
set -euo pipefail
unset PGSERVICE PGSERVICEFILE
name="roamora-sql-${GITHUB_RUN_ID:?CI run identity required}-${GITHUB_RUN_ATTEMPT:?CI attempt required}"
cleanup() { docker rm --force --volumes "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Bridge port publishing makes inet_server_addr() a non-loopback address. Keep
# the test's exact loopback guard, instead run the isolated server on loopback.
docker run --detach --rm --name "$name" --network host \
  --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=512m \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=disposable-test-password \
  -e POSTGRES_DB=planning_queue_test \
  postgres:17.11@sha256:5bf4cdb7aa4b9241bcebf00f15933b1939c928d00f03a36395fbab28e02b8b31 \
  -c listen_addresses=127.0.0.1 -p 55432 >/dev/null
ready=false
for attempt in {1..60}; do
  if docker exec "$name" pg_isready -h 127.0.0.1 -p 55432 -U postgres -d planning_queue_test >/dev/null 2>&1; then
    ready=true; break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo 'Disposable PostgreSQL did not become ready.' >&2
  exit 1
fi
export PLANNING_SQL_TEST_DATABASE_URL=postgresql://postgres:disposable-test-password@127.0.0.1:55432/planning_queue_test
export PGHOSTADDR=127.0.0.1
python - <<'PY'
import os
import psycopg
with psycopg.connect(os.environ['PLANNING_SQL_TEST_DATABASE_URL'], hostaddr='127.0.0.1', connect_timeout=5) as connection:
    actual = connection.execute('select current_database(),host(inet_server_addr())').fetchone()
    if actual != ('planning_queue_test', '127.0.0.1'):
        raise SystemExit('Refusing native SQL tests: unexpected database/address.')
PY
python backend-python/tests/sql/planning_jobs_postgres.py
python -m pytest -q -c backend-python/pytest.ini \
  backend-python/tests/test_adaptive_archive_postgres.py \
  backend-python/tests/test_adaptive_archive_migration_postgres.py
