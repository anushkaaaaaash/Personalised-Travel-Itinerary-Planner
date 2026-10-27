import asyncio
import json
from uuid import uuid4
import pytest
from app.planning_postgres import PlanningPostgresGateway, ROLE_AUDIT
from app.planning_repository import JobRepositoryError

URL='postgresql://planning_queue_worker.abcdefghijklmnopqrst:fixture-password@aws-0-test.pooler.supabase.com:6543/postgres'


class Cursor:
    def __init__(self, rows): self.rows=rows
    async def fetchmany(self, count):
        assert count==2
        return self.rows[:count]


class Connection:
    def __init__(self, rows=None, audit=None, fail=None):
        self.rows=rows if rows is not None else [(json.dumps({'status':'queued'}),)]
        self.audit=audit or {'role':'planning_queue_worker','safe':True}
        self.fail, self.queries, self.exited = fail, [], False
    async def __aenter__(self): return self
    async def __aexit__(self, *args):
        self.exited=True
        if self.fail=='commit': raise RuntimeError('fixture-password commit ambiguity')
    async def execute(self, query, params=None):
        self.queries.append((query, params))
        if query.startswith('SET LOCAL'): return Cursor([])
        if query==ROLE_AUDIT: return Cursor([(json.dumps(self.audit),)])
        if self.fail=='query': raise RuntimeError('fixture-password SQL error')
        return Cursor(self.rows)


class Factory:
    def __init__(self, connection): self.connection=connection; self.calls=[]
    async def __call__(self, **kwargs): self.calls.append(kwargs); return self.connection


def gateway(connection):
    factory=Factory(connection)
    return PlanningPostgresGateway(URL, enabled=True, connection_factory=factory),factory


def test_fixed_rpc_and_secure_connection_kwargs():
    async def scenario():
        conn=Connection(); api,factory=gateway(conn)
        worker=str(uuid4())
        assert await api.request('POST','rpc/claim_planning_job',payload={'worker':worker})==[{'status':'queued'}]
        query,params=conn.queries[-1]
        assert 'public.claim_planning_job(%s::uuid)' in query and params==[worker]
        assert worker not in query and conn.exited
        config=factory.calls[0]
        assert config['sslmode']=='verify-full' and config['sslrootcert']=='system'
        assert config['prepare_threshold'] is None and config['autocommit'] is False
        assert 'fixture-password' not in repr(api)
    asyncio.run(scenario())


@pytest.mark.parametrize('selector',['id','request_id'])
def test_owner_bound_get(selector):
    async def scenario():
        conn=Connection(); api,_=gateway(conn)
        owner,identity=str(uuid4()),str(uuid4())
        await api.request('GET','planning_jobs',params={'user_id':'eq.'+owner,selector:'eq.'+identity,'limit':'1'})
        query,params=conn.queries[-1]
        assert 'WHERE user_id=%s::uuid' in query and params==[owner,identity]
    asyncio.run(scenario())


@pytest.mark.parametrize('method,resource,params,payload',[
    ('POST','rpc/arbitrary_sql',None,{'sql':'drop table auth.users'}),
    ('DELETE','planning_jobs',None,{}),
    ('GET','saved_itineraries',{},None),
    ('GET','planning_jobs',{'id':'eq.'+str(uuid4()),'limit':'1'},None),
    ('GET','planning_jobs',{'user_id':'eq.x;drop table auth.users','id':'eq.'+str(uuid4()),'limit':'1'},None),
    ('GET','planning_jobs',{'user_id':'eq.'+str(uuid4()),'id':'eq.'+str(uuid4()),'limit':'100'},None),
    ('POST','rpc/claim_planning_job',None,{'worker':str(uuid4()),'sql':'anything'}),
])
def test_invalid_operations_rejected_before_connection(method,resource,params,payload):
    async def scenario():
        api,factory=gateway(Connection())
        with pytest.raises(JobRepositoryError): await api.request(method,resource,params=params,payload=payload)
        assert not factory.calls
    asyncio.run(scenario())


@pytest.mark.parametrize('failure',['query','commit'])
def test_ambiguous_operation_never_retried_or_leaks_details(failure):
    async def scenario():
        api,factory=gateway(Connection(fail=failure))
        with pytest.raises(JobRepositoryError) as caught:
            await api.request('POST','rpc/planning_queue_health',payload={})
        assert len(factory.calls)==1
        assert 'password' not in str(caught.value)
    asyncio.run(scenario())


@pytest.mark.parametrize('rows',[[('{}',),('{}',)], [('x'*524289,)], [('[]',)], [({'bad':'driver shape'},)]])
def test_bounded_rows_and_results(rows):
    async def scenario():
        api,_=gateway(Connection(rows=rows))
        with pytest.raises(JobRepositoryError): await api.request('POST','rpc/planning_queue_health',payload={})
    asyncio.run(scenario())


@pytest.mark.parametrize('audit',[{'role':'postgres','safe':True},{'role':'planning_queue_worker','safe':False}])
def test_admin_or_overprivileged_role_denied_before_operation(audit):
    async def scenario():
        conn=Connection(audit=audit); api,_=gateway(conn)
        with pytest.raises(JobRepositoryError) as caught: await api.request('POST','rpc/planning_queue_health',payload={})
        assert caught.value.status==403 and len(conn.queries)==3
    asyncio.run(scenario())


@pytest.mark.parametrize('url',[URL+'?sslmode=disable',URL.replace('pooler.supabase.com','example.com'),URL.replace(':6543',':1234'),URL.replace('planning_queue_worker.','postgres.'),URL.replace('fixture-password',''),URL+'#options'])
def test_connection_configuration_rejected(url):
    with pytest.raises(JobRepositoryError): PlanningPostgresGateway(url,enabled=True)


def test_disabled_by_default():
    with pytest.raises(JobRepositoryError): PlanningPostgresGateway(URL)


def test_json_is_bound_not_interpolated():
    async def scenario():
        conn=Connection(); api,_=gateway(conn)
        payload={'request_row':{'preferences':{'destination':"'); DROP TABLE auth.users; --"}}}
        await api.request('POST','rpc/enqueue_planning_job',payload=payload)
        query,params=conn.queries[-1]
        assert 'DROP' not in query and 'DROP' in params[0]
    asyncio.run(scenario())


def test_role_audit_covers_indirect_and_column_privilege_paths():
    assert "has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')" in ROLE_AUDIT
    assert "has_schema_privilege(current_user,n.oid,'CREATE')" in ROLE_AUDIT
    assert "p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')" in ROLE_AUDIT
    assert "c.relname IN ('planning_jobs','planning_job_runtime')" in ROLE_AUDIT
    assert "c.relkind IN ('r','p')" in ROLE_AUDIT
    assert "has_sequence_privilege(current_user,c.oid,'USAGE,UPDATE')" in ROLE_AUDIT
    assert "has_database_privilege(current_user,current_database(),'CREATE')" in ROLE_AUDIT
    assert 'saved_itineraries' not in ROLE_AUDIT  # deny all other application tables, not just known names


def test_actual_sql_audit_denies_public_definer_column_and_schema_escalation():
    """Optional isolated PGlite proof; no connection URL, credentials or network."""
    import pathlib
    import shutil
    import subprocess
    root = pathlib.Path(__file__).resolve().parents[2]
    module = root / 'backend-python/tests/sql/node_modules/@electric-sql/pglite/dist/index.js'
    if not shutil.which('node') or not module.exists():
        pytest.skip('Install the pinned test-only PGlite package to run SQL isolation proof.')
    script = r'''
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.argv[1]).href);
const audit=process.argv[2];
const db=new PGlite();
try {
 await db.exec(`create schema auth; create role planning_queue_worker login;
   revoke create on schema public from public;
   create table public.planning_jobs(id integer); create table public.planning_job_runtime(id integer);
   create table public.saved_itineraries(secret text); insert into public.saved_itineraries values ('private');
   grant select,insert,update,delete on planning_jobs,planning_job_runtime to planning_queue_worker;`);
 const safe=async()=>{await db.exec('set role planning_queue_worker');
   const value=(await db.query(audit)).rows[0]; await db.exec('reset role');
   return JSON.parse(Object.values(value)[0]).safe;};
 if(!await safe()) throw Error('Restricted baseline unexpectedly rejected');
 await db.exec(`create function public.fixture() returns text language sql security definer as
   $$select secret from public.saved_itineraries limit 1$$;`);
 await db.exec('set role planning_queue_worker');
 if((await db.query('select public.fixture() as secret')).rows[0].secret!=='private') throw Error('Exploit setup did not expose row');
 await db.exec('reset role');
 if(await safe()) throw Error('PUBLIC EXECUTE definer escape accepted');
 await db.exec('revoke execute on function public.fixture() from public');
 if(!await safe()) throw Error('Definer revoke did not restore isolation');
 await db.exec('grant select(secret) on saved_itineraries to planning_queue_worker');
 if(await safe()) throw Error('Column-only grant accepted');
 await db.exec('revoke select(secret) on saved_itineraries from planning_queue_worker');
 await db.exec('grant create on schema public to planning_queue_worker');
 if(await safe()) throw Error('Schema CREATE escape accepted');
 await db.exec('revoke create on schema public from planning_queue_worker');
 await db.exec('create sequence public.foreign_sequence; grant usage on sequence public.foreign_sequence to planning_queue_worker');
 if(await safe()) throw Error('Nonqueue sequence grant accepted');
 await db.exec('revoke usage on sequence public.foreign_sequence from planning_queue_worker');
 await db.exec(`create schema unrelated; create table unrelated.private_data(value text);
   create sequence unrelated.private_sequence;
   create function unrelated.hidden_definer() returns text language sql security definer as $$select secret from public.saved_itineraries limit 1$$;
   grant select on unrelated.private_data to planning_queue_worker;
   grant usage on sequence unrelated.private_sequence to planning_queue_worker;`);
 if(await safe()) throw Error('Raw private grants/definer escaped conservative audit');
 await db.exec('set role planning_queue_worker');
 for(const sql of ['select * from unrelated.private_data',"select nextval('unrelated.private_sequence')",'select unrelated.hidden_definer()']) {
   let denied=false;try{await db.query(sql);}catch(error){denied=String(error).includes('permission denied');}
   if(!denied)throw Error('Schema-USAGE denial was not enforced');
 }
 await db.exec('reset role; grant usage on schema unrelated to planning_queue_worker');
 if(await safe()) throw Error('Other-schema access with USAGE accepted');
 await db.exec('revoke select on unrelated.private_data from planning_queue_worker; revoke usage on sequence unrelated.private_sequence from planning_queue_worker');
 if(await safe()) throw Error('Reachable definer accepted');
 await db.exec('revoke execute on function unrelated.hidden_definer() from public');
 if(!await safe()) throw Error('Revoked accessible grants did not restore safety');
 await db.exec('grant usage on sequence unrelated.private_sequence to planning_queue_worker');
 if(await safe()) throw Error('Reachable sequence accepted');
 await db.exec('revoke usage on schema unrelated from planning_queue_worker');
 if(await safe()) throw Error('Raw sequence USAGE must remain unsafe despite absent schema USAGE');
 await db.exec('revoke usage on sequence unrelated.private_sequence from planning_queue_worker');
 if(!await safe()) throw Error('Revoking all raw private grants did not restore isolation');
 console.log('PASS SQL least-privilege audit');
} finally { await db.close(); }
'''
    completed = subprocess.run(['node', '--input-type=module', '-e', script, str(module), ROLE_AUDIT],
        text=True, capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert 'PASS SQL least-privilege audit' in completed.stdout

def test_privilege_functions_guard_relation_kinds_with_case():
    # PostgreSQL may reorder WHERE predicates; has_sequence_privilege(indexOID)
    # raises42809 unless the function itself is inside a CASE guard.
    assert "CASE WHEN c.relkind='S' THEN" in ROLE_AUDIT
    assert "CASE WHEN c.relkind IN ('r','p','v','m','f') THEN" in ROLE_AUDIT

def test_definitive_admission_failure_matches_rest_without_echo_or_retry():
    from types import SimpleNamespace
    class AdmissionError(Exception):
        sqlstate='P0001'
        diag=SimpleNamespace(message_primary='Planning admission limit reached')
    class Rejected(Connection):
        async def execute(self,query,params=None):
            if 'public.enqueue_planning_job' in query:raise AdmissionError('fixture-password must not leak')
            return await super().execute(query,params)
    async def scenario():
        api,factory=gateway(Rejected())
        with pytest.raises(JobRepositoryError) as error:
            await api.request('POST','rpc/enqueue_planning_job',payload={'request_row':{}})
        assert error.value.code=='JOB_ADMISSION_REJECTED' and error.value.status==429
        assert len(factory.calls)==1 and 'fixture-password' not in str(error.value)
    asyncio.run(scenario())

def test_actual_sql_platform_metadata_exceptions_are_exact_and_nonmutating():
    import pathlib, shutil, subprocess
    root=pathlib.Path(__file__).resolve().parents[2]
    module=root/'backend-python/tests/sql/node_modules/@electric-sql/pglite/dist/index.js'
    if not shutil.which('node') or not module.exists():pytest.skip('Install pinned SQL test dependency.')
    script=r'''
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.argv[1]).href);const audit=process.argv[2];const db=new PGlite();
try {
 await db.exec(`create schema auth;create role planning_queue_worker login;create role supabase_admin;
   revoke create on schema public from public;create schema extensions;create schema cron;
   create view extensions.pg_stat_statements as select 1 as n;
   create view extensions.pg_stat_statements_info as select 1 as n;
   grant select on extensions.pg_stat_statements,extensions.pg_stat_statements_info to public;
   create table cron.job(username text);create table cron.job_run_details(username text);
   alter table cron.job owner to supabase_admin;alter table cron.job_run_details owner to supabase_admin;
   alter table cron.job enable row level security;alter table cron.job_run_details enable row level security;
   create policy own_job on cron.job using(username=CURRENT_USER);
   create policy own_runs on cron.job_run_details using(username=CURRENT_USER);
   grant select on cron.job,cron.job_run_details to public;grant delete on cron.job_run_details to public;
   create sequence cron.jobid_seq;create sequence cron.runid_seq;
   alter sequence cron.jobid_seq owner to supabase_admin;alter sequence cron.runid_seq owner to supabase_admin;
   grant select on sequence cron.jobid_seq,cron.runid_seq to public;`);
 // Registry-only fixtures reproduce metadata verified independently on hosted
 // Supabase. Real SQL privileges/RLS and wrapper execution are not mocked.
 await db.exec(`insert into pg_extension(oid,extname,extowner,extnamespace,extrelocatable,extversion)
   values(800001,'pg_cron',(select oid from pg_roles where rolname='postgres'),'cron'::regnamespace,false,'test'),
   (800002,'pg_stat_statements',(select oid from pg_roles where rolname='postgres'),'extensions'::regnamespace,false,'test');
   insert into pg_depend(classid,objid,objsubid,refclassid,refobjid,refobjsubid,deptype)
   select 'pg_class'::regclass,c.oid,0,'pg_extension'::regclass,case when n.nspname='cron' then 800001 else 800002 end,0,'e'
   from pg_class c join pg_namespace n on n.oid=c.relnamespace
   where (n.nspname='cron' and c.relname in('job','job_run_details','jobid_seq','runid_seq'))
      or (n.nspname='extensions' and c.relname in('pg_stat_statements','pg_stat_statements_info'));`);
 const safe=async()=>{await db.exec('set role planning_queue_worker');const r=(await db.query(audit)).rows[0];await db.exec('reset role');return JSON.parse(Object.values(r)[0]).safe;};
 if(!await safe())throw Error('Exact reviewed platform metadata unexpectedly denied');
 await db.exec('grant usage on schema extensions to planning_queue_worker');if(await safe())throw Error('Reachable metadata accepted');
 await db.exec('revoke usage on schema extensions from planning_queue_worker');
 const oid=(await db.query("select 'cron.jobid_seq'::regclass::oid as oid")).rows[0].oid;
 await db.exec('set role planning_queue_worker');let denied=false;
 try{await db.query(`select nextval(${oid}::oid::regclass)`);}catch(e){denied=String(e).includes('permission denied');}
 if(!denied)throw Error('SELECT-only sequence unexpectedly mutable');await db.exec('reset role');
 await db.exec('grant usage on sequence cron.jobid_seq to planning_queue_worker');if(await safe())throw Error('OID mutation privilege accepted');
 await db.exec('revoke usage on sequence cron.jobid_seq from planning_queue_worker');
 await db.exec('create policy unsafe_extra on cron.job using(true)');if(await safe())throw Error('Broader RLS accepted');
 await db.exec('drop policy unsafe_extra on cron.job');
 await db.exec('grant insert on cron.job to planning_queue_worker');if(await safe())throw Error('Platform write privilege accepted');
 await db.exec('revoke insert on cron.job from planning_queue_worker');
 await db.exec(`create function public.wrapper() returns integer language sql begin atomic select n from extensions.pg_stat_statements;end;`);
 if(await safe())throw Error('Prebound reachable invoker wrapper accepted');
 await db.exec('revoke execute on function public.wrapper() from public');if(!await safe())throw Error('Wrapper revoke failed');
 await db.exec("delete from pg_depend where objid='extensions.pg_stat_statements'::regclass and deptype='e'");
 if(await safe())throw Error('Non-extension lookalike accepted');
 console.log('PASS exact platform metadata compatibility');
}finally{await db.close()}
'''
    result=subprocess.run(['node','--input-type=module','-e',script,str(module),ROLE_AUDIT],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert 'PASS exact platform metadata compatibility' in result.stdout
