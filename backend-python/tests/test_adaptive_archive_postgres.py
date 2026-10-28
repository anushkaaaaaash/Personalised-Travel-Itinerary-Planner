"""Opt-in native concurrency tests. Disposable loopback planning_queue_test ONLY.
Run after tests/sql/planning_jobs_postgres.py; absent URL means no connection.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib,json,os
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse,unquote
from uuid import uuid4
import pytest

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def wire(value):
    text=canonical(value)
    return {'canonical':text,'hash':hashlib.sha256(text.encode()).hexdigest()}

class NativeArchive:
    def __init__(self,psycopg,parameters):self.psycopg,self.parameters=psycopg,parameters;self.owners=[]
    def connect(self):return self.psycopg.connect(**self.parameters)
    def owner(self):
        owner=str(uuid4())
        with self.connect() as conn:conn.execute('insert into auth.users(id) values (%s::uuid)',(owner,))
        self.owners.append(owner);return owner
    def rpc(self,owner,operation,payload,barrier=None):
        with self.connect() as conn:
            conn.execute("set local statement_timeout='10s'");conn.execute('set local role authenticated')
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(owner,))
            pid=conn.execute('select pg_backend_pid()').fetchone()[0]
            if barrier is not None:barrier.wait(timeout=10)
            result=conn.execute('select public.adaptive_saved_archive(%s,%s::jsonb)',(operation,json.dumps(payload))).fetchone()[0]
        return pid,result
    def race(self,owner,operation,payloads):
        barrier=Barrier(len(payloads))
        def run(payload):
            try:
                pid,result=self.rpc(owner,operation,payload,barrier);return {'pid':pid,'result':result}
            except self.psycopg.Error as error:
                if error.sqlstate=='P0001' and error.diag.message_primary=='SAVED_ADAPTIVE_QUOTA_EXCEEDED':return {'error':'SAVED_ADAPTIVE_QUOTA_EXCEEDED'}
                raise AssertionError('Unexpected disposable archive SQL result') from None
        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:return list(pool.map(run,payloads))

@pytest.fixture(scope='module')
def native_archive():
    raw=os.environ.get('PLANNING_SQL_TEST_DATABASE_URL','')
    if not raw:pytest.skip('Native archive concurrency requires explicit disposable PostgreSQL URL')
    try:
        parsed=urlparse(raw)
        allowed=(parsed.scheme in {'postgres','postgresql'} and parsed.hostname in {'127.0.0.1','localhost'} and parsed.path=='/planning_queue_test' and not parsed.query and not parsed.fragment and parsed.username=='postgres' and 1<=(parsed.port or 5432)<=65535)
        if not allowed:raise ValueError()
        parameters={'host':parsed.hostname,'hostaddr':'127.0.0.1','port':parsed.port or 5432,'dbname':'planning_queue_test','user':'postgres','password':unquote(parsed.password or ''),'connect_timeout':5}
    except Exception:pytest.fail('Refusing SQL QA: explicit disposable loopback planning_queue_test URL required',pytrace=False)
    import psycopg
    db=NativeArchive(psycopg,parameters);applied=False
    try:
        with db.connect() as conn:
            actual=conn.execute('select current_database(),host(inet_server_addr())').fetchone()
            if actual!=('planning_queue_test','127.0.0.1'):pytest.fail('Refusing SQL QA: connected database/address not disposable loopback',pytrace=False)
            occupied=conn.execute("select to_regnamespace('adaptive_archive') is not null or exists(select 1 from pg_roles where rolname='adaptive_archive_rpc') or to_regprocedure('public.adaptive_saved_archive(text,jsonb)') is not null").fetchone()[0]
            if occupied:pytest.fail('Disposable archive namespace already exists; refusing replacement',pytrace=False)
            conn.execute("do $$begin if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if; if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if; end$$")
            conn.execute('create schema if not exists auth');conn.execute('create table if not exists auth.users(id uuid primary key)')
            if conn.execute("select to_regprocedure('auth.uid()')").fetchone()[0] is None:
                conn.execute("create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$")
        proposal=Path(__file__).resolve().parents[2]/'docs/adaptive_saved_archive_REVIEW_ONLY.sql'
        with db.connect() as conn:
            conn.autocommit=True;conn.execute(proposal.read_text(),prepare=False)
        applied=True;yield db
    finally:
        if applied:
            with db.connect() as conn:
                for owner in db.owners:conn.execute('delete from auth.users where id=%s::uuid',(owner,))
                conn.execute('drop function public.adaptive_saved_archive(text,jsonb)')
                conn.execute('drop schema adaptive_archive cascade');conn.execute('drop owned by adaptive_archive_rpc');conn.execute('drop role adaptive_archive_rpc')

def example(content_bytes=None):
    route={'summary':'Synthetic route','stays':[{'startDate':'2028-01-01','endDate':'2028-01-01','location':'Paris'}]}
    chunk={'sequence':1,'sourceSequence':2,'startDate':'2028-01-01','endDate':'2028-01-01','sourceHashes':[],'sourceAssociation':'none_recorded',
        'checkpoint':{'journeyStrategy':route,'startLocation':'London','endLocation':'London','spentCents':100,'provenance':{'provider':'openai','model':'gpt-6-luna','validationVersion':'adaptive-section-v1'},'itinerary':{'currency':'GBP','days':[{'date':'2028-01-01'}]}}}
    manifest={'format':'adaptive-sections-v1','sourcePlanId':str(uuid4()),'sourceVersion':1,'sourceExpiresAt':'2099-01-01T00:00:00Z',
        'preferences':{'startDate':'2028-01-01','endDate':'2028-01-01','departureCity':'London','destination':'Paris'},'journeyStrategy':route,
        'totalDays':1,'sectionCount':1,'sourceCount':0,'spentCents':100,'totalBudgetCents':1000,'currency':'GBP',
        'contentBytes':len(canonical(chunk).encode()) if content_bytes is None else content_bytes,'sectionsDigest':hashlib.sha256(bytes.fromhex(wire(chunk)['hash'])).hexdigest()}
    before=canonical(manifest);manifest['sourceDigest']=hashlib.sha256(before.encode()).hexdigest()
    return {'requestId':str(uuid4()),'title':'Synthetic native PostgreSQL archive','sourceCanonical':before,**wire(manifest)},chunk

def test_native_concurrent_same_request_begin_is_one_archive(native_archive):
    db=native_archive;owner=db.owner();payload,_=example();outcomes=db.race(owner,'begin',[payload,deepcopy(payload)])
    assert len({o['pid'] for o in outcomes})==2 and len({o['result']['id'] for o in outcomes})==1
    with db.connect() as conn:assert conn.execute('select count(*) from adaptive_archive.manifests where owner=%s::uuid',(owner,)).fetchone()[0]==1

def test_native_concurrent_owner_quota_admission_serializes(native_archive):
    db=native_archive;owner=db.owner()
    for _ in range(3):db.rpc(owner,'begin',example(15*1024*1024)[0])
    outcomes=db.race(owner,'begin',[example(15*1024*1024)[0],example(15*1024*1024)[0]])
    assert sum('result' in o for o in outcomes)==1 and sum(o.get('error')=='SAVED_ADAPTIVE_QUOTA_EXCEEDED' for o in outcomes)==1
    with db.connect() as conn:
        count,total=conn.execute('select count(*),sum(reserved_bytes) from adaptive_archive.manifests where owner=%s::uuid',(owner,)).fetchone()
        assert count==4 and total<=64*1024*1024

def test_native_concurrent_finalize_owner_and_direct_dml_guards(native_archive):
    db=native_archive;owner=db.owner();other=db.owner();payload,chunk=example()
    _,staging=db.rpc(owner,'begin',payload);identity=staging['id'];db.rpc(owner,'append_sections',{'id':identity,'items':[wire(chunk)]})
    outcomes=db.race(owner,'finalize',[{'id':identity},{'id':identity}])
    assert len({o['pid'] for o in outcomes})==2 and all(o['result']['status']=='complete' and o['result']['id']==identity for o in outcomes)
    _,page=db.rpc(owner,'get',{'id':identity,'afterSequence':0});assert page['persisted'] is True and len(page['sections'])==1
    with pytest.raises(db.psycopg.Error) as wrong_owner:db.rpc(other,'delete',{'id':identity,'version':1})
    assert wrong_owner.value.sqlstate=='P0001' and wrong_owner.value.diag.message_primary=='SAVED_ADAPTIVE_NOT_FOUND'
    with pytest.raises(db.psycopg.Error) as direct:
        with db.connect() as conn:
            conn.execute('set local role authenticated');conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(owner,))
            conn.execute("insert into adaptive_archive.manifests(owner,request_id,title,manifest,manifest_hash,status,reserved_bytes) values(%s::uuid,%s::uuid,'Bypass','{}',%s,'complete',1)",(owner,str(uuid4()),'0'*64))
    assert direct.value.sqlstate=='42501'
    with db.connect() as conn:
        assert conn.execute("select rolcanlogin,rolsuper,rolbypassrls,rolcreaterole from pg_roles where rolname='adaptive_archive_rpc'").fetchone()==(False,False,False,False)
        assert conn.execute("select pg_has_role('authenticated','adaptive_archive_rpc','MEMBER')").fetchone()[0] is False
        assert conn.execute('select status from adaptive_archive.manifests where id=%s::uuid',(identity,)).fetchone()[0]=='complete'
