"""Destructive SQL integration test for a disposable loopback CI database ONLY.

Requires psql and PLANNING_SQL_TEST_DATABASE_URL. Not auto-collected by pytest.
Never point this at Supabase or an application database. Concurrent subprocesses
use independent PostgreSQL connections, unlike the single-connection PGlite test.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlparse
from uuid import uuid4

url = os.environ.get('PLANNING_SQL_TEST_DATABASE_URL', '')
parsed = urlparse(url)
if parsed.scheme not in {'postgresql', 'postgres'} or parsed.hostname not in {'localhost', '127.0.0.1'} or parsed.path != '/planning_queue_test' or parsed.query:
    raise SystemExit('Refusing SQL QA: explicit disposable loopback planning_queue_test database required.')
command = ['psql', '--no-psqlrc', '--quiet', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1']
# PGDATABASE from the environment is a database name, not reliably expanded as
# a conninfo URI by every psql/libpq combination. Pass validated loopback fields
# explicitly; keep even disposable credentials out of command arguments.
environment = {
    **os.environ, 'PGHOST': parsed.hostname, 'PGPORT': str(parsed.port or 5432),
    'PGDATABASE': 'planning_queue_test', 'PGUSER': unquote(parsed.username or 'postgres'),
    'PGPASSWORD': unquote(parsed.password or ''),
}


def sql(statement):
    completed = subprocess.run(command, input=statement, text=True, capture_output=True, env=environment, timeout=15)
    if completed.returncode:
        raise AssertionError('Disposable SQL integration query failed: ' + completed.stderr)
    return completed.stdout.strip()


def value(statement):
    return json.loads(sql(statement))


def literal(data):
    return "'" + str(data).replace("'", "''") + "'"


sql('create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create table auth.users(id uuid primary key);')
sql(Path(__file__).resolve().parents[2].joinpath('migrations/003_planning_jobs_REVIEW_ONLY.sql').read_text())
sql(Path(__file__).resolve().parents[2].joinpath('migrations/004_abandon_uncertain_planning_jobs_REVIEW_ONLY.sql').read_text())
owners = [str(uuid4()), str(uuid4())]
sql('insert into auth.users values ' + ','.join('('+literal(owner)+')' for owner in owners) + ';')


def enqueue(owner):
    row = dict(id=str(uuid4()), user_id=owner, request_id=str(uuid4()), input_hash='a'*64, preferences={'destination':'SQL fixture'})
    sql('set role service_role; select id from enqueue_planning_job('+literal(json.dumps(row))+'::jsonb);')
    return row


def claim():
    return value('set role service_role; select coalesce(json_agg(j),\'[]\'::json) from claim_planning_job('+literal(uuid4())+'::uuid) j;')


# Two separate connections racing for the same queue cannot claim one row twice.
rows = [enqueue(owner) for owner in owners]
with ThreadPoolExecutor(max_workers=2) as pool:
    claims = list(pool.map(lambda _: claim(), range(2)))
assert all(len(item) == 1 for item in claims), claims
assert len({item[0]['id'] for item in claims}) == 2

# Reset only the disposable queue and demonstrate a locked first row is skipped.
sql('truncate planning_jobs;')
rows = [enqueue(owner) for owner in owners]
first = value('select row_to_json(j) from (select id from planning_jobs order by created_at,id limit 1) j;')['id']
locker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
try:
    locker.stdin.write('begin; select id from planning_jobs where id='+literal(first)+'::uuid for update;\n\\echo ROW_LOCKED\n')
    locker.stdin.flush()
    while True:
        line = locker.stdout.readline()
        if 'ROW_LOCKED' in line: break
        if not line: raise AssertionError('Lock connection ended before acquiring row lock.')
    # A short server timeout makes accidental blocking fail, not merely pass late.
    second = value('set statement_timeout=1000; set role service_role; select coalesce(json_agg(j),\'[]\'::json) from claim_planning_job('+literal(uuid4())+'::uuid) j;')
    assert len(second) == 1 and second[0]['id'] != first, second
finally:
    if locker.poll() is None:
        locker.stdin.write('rollback;\n'); locker.stdin.close()
        locker.wait(timeout=5)
    assert locker.returncode == 0

# Cancellation on another connection wins over a stale worker's success CAS.
claimed = second[0]
for state, response in [('submitting', 'null'), ('running', "'resp_sql_fixture'")]:
    claimed = value('set role service_role; select row_to_json(j) from transition_planning_job('+','.join([
        literal(claimed['id'])+'::uuid', literal(claimed['lease_token'])+'::uuid', str(claimed['version']),
        literal(state), response, 'null', 'null'])+') j;')
claimed = claim()[0]  # running work has priority over the other queued record
assert claimed['provider_response_id'] == 'resp_sql_fixture'
owner = next(row['user_id'] for row in rows if row['id'] == claimed['id'])
sql('set role service_role; select id from cancel_planning_job('+literal(owner)+'::uuid,'+literal(claimed['id'])+'::uuid);')
remaining = sql('set role service_role; select count(*) from transition_planning_job('+','.join([
    literal(claimed['id'])+'::uuid', literal(claimed['lease_token'])+'::uuid', str(claimed['version']),
    "'succeeded'", 'null', "'{\"days\":[]}'::jsonb", 'null'])+');')
assert remaining == '0'
assert sql('select status from planning_jobs where id='+literal(claimed['id'])+'::uuid;') == 'cancelled'
print('PASS: real PostgreSQL independent-connection claims, locked-row SKIP LOCKED, and cancellation/stale-worker CAS.')

# Explicitly abandon uncertain submissions; never reset/recreate their request IDs.
sql('truncate planning_jobs;')
uncertain = [enqueue(owner) for owner in owners]
sql("update planning_jobs set status='submission_unknown',error_code='JOB_SUBMISSION_UNCONFIRMED';")
assert sql('set role service_role; select count(*) from cancel_planning_job('+literal(owners[1])+'::uuid,'+literal(uncertain[0]['id'])+'::uuid);') == '0'
for pending in uncertain:
    assert sql('set role service_role; select status from cancel_planning_job('+literal(pending['user_id'])+'::uuid,'+literal(pending['id'])+'::uuid);') == 'cancelled'
    assert sql('set role service_role; select status from enqueue_planning_job('+literal(json.dumps(pending))+'::jsonb);') == 'cancelled'
next_job = enqueue(owners[0])
assert claim() == []
sql("update planning_jobs set created_at=now()-interval '9 minutes',expires_at=now()+interval '23 hours' where id="+literal(uncertain[0]['id'])+'::uuid;')
assert claim() == []
sql("update planning_jobs set created_at=now()-interval '11 minutes',expires_at=now()+interval '23 hours' where id="+literal(uncertain[0]['id'])+'::uuid;')
assert claim()[0]['id'] == next_job['id']
assert sql('set role service_role; select status from enqueue_planning_job('+literal(json.dumps(uncertain[0]))+'::jsonb);') == 'cancelled'
print('PASS: explicit owner abandonment of unknown submission; replay remains cancelled; capacity preserved until 10-minute reserve elapses.')
