import asyncio
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import json
import sqlite3
from uuid import uuid4
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.research_sqlite import ResearchSQLiteGateway,upgrade_research_schema
from app.research_repository import ResearchCheckpointRepository
from app.section_repository import SectionCheckpointRepository
from app.adaptive_research import build_public_query
from app.planning_repository import JobRepositoryError


def uid():return str(uuid4())
def run(c):return asyncio.run(c)
def query(p):return asdict(build_public_query(p))
def change(path,table,id,**values):
    with sqlite3.connect(path) as c:
        d=json.loads(c.execute('SELECT data FROM '+table+' WHERE id=?',(id,)).fetchone()[0]);d.update(values)
        c.execute('UPDATE '+table+' SET data=? WHERE id=?',(json.dumps(d),id))

@pytest.fixture
def store(tmp_path):
    path=tmp_path/'queue.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,research_enabled=True,clock=lambda:clock[0])
    return path,clock,g,SectionCheckpointRepository(g,enabled=True),ResearchCheckpointRepository(g,enabled=True)

def create(store,payload):
    _,_,_,r,rr=store;p=run(r.create_plan(uid(),uid(),payload))
    section=run(r.next_section(p['user_id'],p['id'],uid()));section=run(r.claim(p['user_id'],section['id'],uid()))
    section=run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'submitting'))
    section=run(r.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'running',provider_response_id='resp_trigger'))
    section=run(r.claim(p['user_id'],section['id'],uid()))
    run(rr.request_research(p['user_id'],section['id'],section['lease_token'],section['version'],'places'))
    p=run(r.get_plan(p['user_id'],p['id']));j=run(rr.get(p['user_id'],p['active_research']));return p,j

def submit(rr,j):
    c=run(rr.claim_next(uid()));assert c['id']==j['id']
    return run(rr.transition(c['user_id'],c['id'],c['lease_token'],c['version'],'submitting'))

def running(rr,j):
    j=submit(rr,j)
    return run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'running',provider_response_id='resp_'+j['id']))

def fail(rr,j):
    j=running(rr,j);j=run(rr.claim_next(uid()))
    return run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'failed',error_code='RESEARCH_PROVIDER_FAILED'))


def test_explicit_migration_preserves_legacy_and_refuses_active_or_missing(tmp_path,payload):
    path=tmp_path/'queue.sqlite'
    with pytest.raises(JobRepositoryError):upgrade_research_schema(path,approved=True)
    assert not path.exists()
    g=AdaptiveSQLiteGateway(path,enabled=True,initialize=True);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload))
    with pytest.raises(JobRepositoryError,match='PLANNING_IN_PROGRESS'):upgrade_research_schema(path,approved=True)
    change(path,'plans',p['id'],status='paused',pause_reason='SECTION_FAILED')
    before=run(r.get_plan(p['user_id'],p['id']))
    with pytest.raises(JobRepositoryError):upgrade_research_schema(path)
    upgrade_research_schema(path,approved=True);upgrade_research_schema(path,approved=True)
    new=ResearchSQLiteGateway(path,enabled=True,research_enabled=True);nr=SectionCheckpointRepository(new,enabled=True)
    assert run(nr.get_plan(p['user_id'],p['id']))==before
    assert 'research_required' not in before
    with pytest.raises(JobRepositoryError):AdaptiveSQLiteGateway(path,enabled=True)


def test_owner_dedup_public_scope_and_research_blocks_sections(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload)
    assert p['remaining_creates']==11
    assert run(rr.reserve(p['user_id'],p['id'],j['request_id'],query(payload)))==j
    with pytest.raises(JobRepositoryError):run(rr.get(uid(),j['id']))
    assert run(rr.latest(uid(),p['id'])) is None
    assert run(r.claim_next(uid())) is None
    with pytest.raises(JobRepositoryError):run(r.next_section(p['user_id'],p['id'],uid()))
    for bad in ({**query(payload),'dietaryNeeds':'private'}, {**query(payload),'destination':'Elsewhere'}):
        with pytest.raises(JobRepositoryError):run(rr.reserve(p['user_id'],p['id'],uid(),bad,phase='refresh'))
    j=submit(rr,j);p=run(r.get_plan(p['user_id'],p['id']))
    assert p['remaining_creates']==10 and p['tool_calls_reserved']==4
    with pytest.raises(JobRepositoryError):run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version']-1,'running',provider_response_id='resp_bad'))


def test_restart_unknown_quarantine_keeps_reservation_and_no_retry(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);j=submit(rr,j);clock[0]+=61
    fresh=ResearchSQLiteGateway(path,enabled=True,research_enabled=True,clock=lambda:clock[0]);fr=ResearchCheckpointRepository(fresh,enabled=True)
    assert run(fr.claim_next(uid())) is None
    assert run(fr.get(p['user_id'],j['id']))['status']=='submission_unknown'
    p=run(r.get_plan(p['user_id'],p['id']));assert p['remaining_creates']==10 and p['tool_calls_reserved']==4
    with pytest.raises(JobRepositoryError):run(fr.reserve(p['user_id'],p['id'],uid(),query(payload),phase='refresh'))
    with pytest.raises(JobRepositoryError):run(r.continue_run(p['user_id'],p['id'],uid()))
    run(r.cancel_plan(p['user_id'],p['id']));assert run(fr.get(p['user_id'],j['id']))['status']=='cancelled'


def test_retry_budget_continue_is_explicit_and_idempotent(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);fail(rr,j)
    p=run(r.get_plan(p['user_id'],p['id']));assert p['pause_reason']=='RESEARCH_FAILED'
    j=run(rr.reserve(p['user_id'],p['id'],uid(),query(payload),phase='refresh'));fail(rr,j)
    p=run(r.get_plan(p['user_id'],p['id']));assert p['tool_calls_reserved']==6 and p['remaining_creates']==9 and p['pause_reason']=='RESEARCH_ALLOWANCE_REACHED'
    with pytest.raises(JobRepositoryError):run(rr.reserve(p['user_id'],p['id'],uid(),query(payload),phase='initial'))
    request=uid();resumed=run(r.continue_run(p['user_id'],p['id'],request))
    assert resumed['run_index']==2 and resumed['tool_calls_reserved']==0 and resumed['remaining_creates']==12
    assert resumed['storage_used_bytes']==p['storage_used_bytes']+512
    assert run(r.continue_run(p['user_id'],p['id'],request))==resumed
    nextjob=run(rr.reserve(p['user_id'],p['id'],uid(),query(payload)))
    assert nextjob['run_index']==2


def test_shared_paid_work_limit_in_both_directions(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);p2,j2=create(store,payload)
    g.research_enabled=False
    legacy=run(r.create_plan(uid(),uid(),payload));section=run(r.next_section(legacy['user_id'],legacy['id'],uid()))
    run(r.claim(legacy['user_id'],section['id'],uid()));run(rr.claim_next(uid()))
    g.research_enabled=True
    assert run(rr.claim_next(uid())) is None
    g.research_enabled=False
    legacy2=run(r.create_plan(uid(),uid(),payload));section2=run(r.next_section(legacy2['user_id'],legacy2['id'],uid()))
    with pytest.raises(JobRepositoryError):run(r.claim(legacy2['user_id'],section2['id'],uid()))


def test_cleanup_cascades_research_and_health_freshness(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload)
    run(g.purge_expired());run(rr.verify_ready())
    clock[0]+=86401
    with pytest.raises(JobRepositoryError):run(rr.get(p['user_id'],j['id']))
    assert run(g.purge_expired())==1
    with sqlite3.connect(path) as c:assert c.execute('SELECT COUNT(*) FROM research_jobs').fetchone()[0]==0
    run(rr.verify_ready())


def pack_for(j,clock):
    stamp=datetime.fromtimestamp(clock[0],timezone.utc)
    return {'query':j['query'],'checked_at':stamp.isoformat(),'expires_at':(stamp+timedelta(hours=24)).isoformat(),
        'tool_calls':1,'text':'Published destination guidance; date applicability unknown.',
        'sources':[{'url':'https://example.org/official','title':'Official visitor page','consulted':True,'cited':True}],
        'citations':[{'start':0,'end':9,'url':'https://example.org/official','title':'Official visitor page'}],
        'applicability':'unknown','evidence_status':'model_observations_and_inference_unverified'}


def test_sourcepack_unlocks_sections_and_remains_immutable(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);j=running(rr,j)
    restarted=ResearchCheckpointRepository(ResearchSQLiteGateway(path,enabled=True,research_enabled=True,clock=lambda:clock[0]),enabled=True)
    j=run(restarted.claim_next(uid()));assert j['provider_response_id'].startswith('resp_')
    pack=pack_for(j,clock)
    for bad in ({**pack,'applicability':'verified'}, {**pack,'query':{**pack['query'],'destination':'Wrong'}}, {**pack,'tool_calls':5}):
        with pytest.raises(JobRepositoryError):run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'succeeded',sourcepack=bad))
    succeeded=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'succeeded',sourcepack=pack))
    assert run(rr.latest(p['user_id'],p['id']))==succeeded
    section=run(rr.continue_researched(p['user_id'],p['id']))
    assert section['research_source_id']==j['id']
    assert run(rr.get(p['user_id'],j['id']))==succeeded
    with pytest.raises(JobRepositoryError):run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'succeeded',sourcepack=pack))
    assert run(r.get_plan(p['user_id'],p['id']))['remaining_creates']==10


def test_cancel_blocks_stale_lease_and_keeps_paid_reservation(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);j=submit(rr,j)
    cancelled=run(r.cancel_plan(p['user_id'],p['id']))
    assert cancelled['remaining_creates']==10 and cancelled['tool_calls_reserved']==4
    with pytest.raises(JobRepositoryError):run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'running',provider_response_id='resp_stale'))
    assert run(rr.get(p['user_id'],j['id']))['status']=='cancelled'
    assert g._paid_work_count(g._connect(),clock[0])==2 # cancelled completed trigger is conservatively retained


def test_storage_checks_do_not_append_unbounded_control_rows(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);fail(rr,j)
    j=run(rr.reserve(p['user_id'],p['id'],uid(),query(payload),phase='refresh'));fail(rr,j)
    p=run(r.get_plan(p['user_id'],p['id']))
    change(path,'plans',p['id'],storage_used_bytes=p['storage_limit_bytes']-100)
    for _ in range(20):
        result=run(r.continue_run(p['user_id'],p['id'],uid()))
        assert result['pause_reason']=='RESEARCH_ALLOWANCE_REACHED' and result['remaining_creates']==9
    with sqlite3.connect(path) as c:assert c.execute('SELECT COUNT(*) FROM controls').fetchone()[0]==0


def research_process_claim(path):
    gateway=ResearchSQLiteGateway(path,enabled=True,research_enabled=True)
    return run(ResearchCheckpointRepository(gateway,enabled=True).claim_next(uid()))


def test_research_claims_are_serialized_across_processes(tmp_path,payload):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    path=tmp_path/'race.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    gateway=ResearchSQLiteGateway(path,enabled=True,research_enabled=True)
    r=SectionCheckpointRepository(gateway,enabled=True);rr=ResearchCheckpointRepository(gateway,enabled=True)
    p,j=create((path,None,gateway,r,rr),payload)
    with ProcessPoolExecutor(3,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=[future.result(timeout=30) for future in [pool.submit(research_process_claim,str(path)) for _ in range(3)]]
    assert sum(result is not None for result in results)==1
    assert next(result for result in results if result)['id']==j['id']


def test_initial_reservation_requires_explicit_trigger(store,payload):
    path,clock,g,r,rr=store;p=run(r.create_plan(uid(),uid(),payload))
    assert p['active_research'] is None
    assert run(rr.claim_next(uid())) is None
    with sqlite3.connect(path) as c:assert c.execute('SELECT COUNT(*) FROM research_jobs').fetchone()[0]==0
    assert run(r.get_plan(p['user_id'],p['id']))['remaining_creates']==12


def test_continue_crash_recovery_creates_new_run_intent_only_after_confirmation(store,payload):
    path,clock,g,r,rr=store;p,j=create(store,payload);fail(rr,j)
    assert run(rr.claim_next(uid())) is None
    j=run(rr.reserve(p['user_id'],p['id'],uid(),query(payload),phase='refresh'));fail(rr,j)
    assert run(rr.claim_next(uid())) is None
    run(r.continue_run(p['user_id'],p['id'],uid()))
    clock[0]+=601 # conservative recently submitted failure reservations expire
    j=run(rr.claim_next(uid()))
    assert j['phase']=='initial' and j['run_index']==2
    assert run(r.get_plan(p['user_id'],p['id']))['remaining_creates']==12


@pytest.mark.parametrize('status',[None,1,'unexpected'])
def test_migration_rejects_unknown_status_without_schema_mutation(tmp_path,payload,status):
    path=tmp_path/'queue.sqlite';g=AdaptiveSQLiteGateway(path,enabled=True,initialize=True);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload));change(path,'plans',p['id'],status=status)
    with pytest.raises(JobRepositoryError):upgrade_research_schema(path,approved=True)
    with sqlite3.connect(path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==1
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='research_jobs'").fetchone()
