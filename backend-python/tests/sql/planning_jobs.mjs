// Isolated PostgreSQL-WASM migration test. No connection strings or network.
// npm ci --prefix backend-python/tests/sql --ignore-scripts
// npm test --prefix backend-python/tests/sql
// PGlite is single-connection: use planning_jobs_postgres.py for concurrent SQL races.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const modulePath = process.env.PLANNING_SQL_TEST_MODULE || '@electric-sql/pglite';
const { PGlite } = await import(modulePath);
const db = new PGlite();
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create table auth.users(id uuid primary key);`);
  const sql=await fs.readFile(new URL('../../migrations/003_planning_jobs_REVIEW_ONLY.sql',import.meta.url),'utf8');
  await db.exec(sql);
  const owner='11111111-1111-4111-8111-111111111111';
  const other='22222222-2222-4222-8222-222222222222';
  const worker='33333333-3333-4333-8333-333333333333';
  await db.query('insert into auth.users(id) values ($1),($2)',[owner,other]);
  const input=(id,request,user=owner)=>({id,user_id:user,request_id:request,input_hash:'a'.repeat(64),preferences:{destination:'test'}});
  const row=input('44444444-4444-4444-8444-444444444444','55555555-5555-4555-8555-555555555555');
  for (const role of ['anon','authenticated']) {
    await db.exec(`set role ${role}`);
    await assert.rejects(db.query('select * from public.planning_jobs'),/permission denied/);
    await assert.rejects(db.query('select * from public.planning_job_runtime'),/permission denied/);
    await assert.rejects(db.query('select * from public.enqueue_planning_job($1)',[row]),/permission denied/);
    await assert.rejects(db.query('select * from public.claim_planning_job($1)',[worker]),/permission denied/);
    await db.exec('reset role');
  }
  await db.exec('set role service_role');
  let created=(await db.query('select * from public.enqueue_planning_job($1)',[row])).rows[0];
  assert.equal(created.status,'queued');
  assert.equal((await db.query('select * from public.enqueue_planning_job($1)',[row])).rows[0].id,created.id);
  let claimed=(await db.query('select * from public.claim_planning_job($1)',[worker])).rows[0];
  assert.ok(claimed.lease_token);assert.equal(claimed.version,2);
  const transition=async (r,status,response=null,result=null)=> (await db.query(
    'select * from public.transition_planning_job($1,$2,$3,$4,$5,$6,$7)',
    [r.id,r.lease_token,r.version,status,response,result,null])).rows;
  let submitting=(await transition(claimed,'submitting'))[0];
  assert.equal(submitting.status,'submitting');
  assert.equal((await transition(claimed,'running','resp_late')).length,0);
  let running=(await transition(submitting,'running','resp_test'))[0];
  assert.equal(running.lease_token,null);assert.equal(running.lease_until,null);
  claimed=(await db.query('select * from public.claim_planning_job($1)',[worker])).rows[0];
  assert.equal(claimed.provider_response_id,'resp_test');
  assert.equal((await db.query('select * from public.cancel_planning_job($1,$2)',[other,claimed.id])).rows.length,0);
  const cancelled=(await db.query('select * from public.cancel_planning_job($1,$2)',[owner,claimed.id])).rows[0];
  assert.equal(cancelled.status,'cancelled');
  assert.equal((await transition(claimed,'succeeded',null,{days:[]})).length,0);
  // Expired submitting lease is quarantined and can never be claimed for resubmit.
  const second=input('66666666-6666-4666-8666-666666666666','77777777-7777-4777-8777-777777777777',other);
  await db.query('select * from public.enqueue_planning_job($1)',[second]);
  claimed=(await db.query('select * from public.claim_planning_job($1)',[worker])).rows[0];
  submitting=(await transition(claimed,'submitting'))[0];
  await db.query("update planning_jobs set lease_until=now()-interval '1 second' where id=$1",[submitting.id]);
  await db.query('select * from public.claim_planning_job($1)',[worker]);
  assert.equal((await db.query('select status from planning_jobs where id=$1',[submitting.id])).rows[0].status,'submission_unknown');
  assert.equal((await db.query('select * from public.claim_planning_job($1)',[worker])).rows.length,0);
  // Atomic owner admission counts pending and uncertain work.
  await db.exec("update planning_jobs set status='failed',provider_response_id=null where status in ('cancelled','submission_unknown')");
  for(let i=8;i<=9;i++) await db.query('select * from public.enqueue_planning_job($1)',[input(`${i}`.repeat(8)+'-1111-4111-8111-111111111111',`${i}`.repeat(8)+'-2222-4222-8222-222222222222')]);
  await assert.rejects(db.query('select * from public.enqueue_planning_job($1)',[input('aaaaaaaa-1111-4111-8111-111111111111','aaaaaaaa-2222-4222-8222-222222222222')]),/admission limit/);
  let health=(await db.query('select * from public.planning_queue_health()')).rows[0];
  assert.equal(health.cleanup_fresh,false); // installed Cron remains a hosted verification.
  await db.query("update public.planning_jobs set created_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' where id=$1",[row.id]);
  const purged=(await db.query('select public.purge_expired_planning_jobs() as removed')).rows[0];
  assert.equal(purged.removed,1);
  assert.equal((await db.query('select id from public.planning_jobs where id=$1',[row.id])).rows.length,0);
  health=(await db.query('select * from public.planning_queue_health()')).rows[0];assert.equal(health.cleanup_fresh,true);
  await db.exec('reset role; create table public.trips(id integer); create table public.saved_itineraries(id integer);');
  await db.exec(await fs.readFile(new URL('../../../docs/planning_worker_role_REVIEW_ONLY.sql',import.meta.url),'utf8'));
  await db.exec('set role planning_queue_worker');
  assert.ok((await db.query('select * from public.planning_jobs')).rows.length>=1);
  assert.ok((await db.query('select * from public.planning_queue_health()')).rows.length===1);
  await assert.rejects(db.query('select * from public.trips'),/permission denied/);
  await assert.rejects(db.query('select * from public.saved_itineraries'),/permission denied/);
  await assert.rejects(db.query('select * from auth.users'),/permission denied/);
  const flags=(await db.query("select rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls from pg_roles where rolname=current_user")).rows[0];
  assert.ok(Object.values(flags).every(value=>value===false));
  console.log('PASS: SQL migration; anonymous/authenticated denied; dedup; owner cancellation; lease/CAS; restart quarantine; atomic owner admission; logical purge and heartbeat; restricted-role queue access and legacy/auth denial.');
} finally { await db.close(); }
