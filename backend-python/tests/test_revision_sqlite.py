import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.grounded_sqlite_upgrade import upgrade_grounded_schema
from app.revision_sqlite import RevisionSQLiteGateway
from app.revision_repository import RevisionRepository,public_revision
from app.revision_worker import RevisionWorker
from app.section_repository import SectionCheckpointRepository
from app.planning_repository import JobRepositoryError
from app.adaptive_planning import SectionSpec,SectionContract
from test_adaptive_planning import section_wire
from test_adaptive_revision import wire
from test_itineraries import generated


def uid():return str(uuid4())
def run(c):return asyncio.run(c)
def mutate(path,table,id,**values):
    with sqlite3.connect(path) as c:
        data=json.loads(c.execute('SELECT data FROM '+table+' WHERE id=?',(id,)).fetchone()[0]);data.update(values)
        c.execute('UPDATE '+table+' SET data=? WHERE id=?',(json.dumps(data),id))

@pytest.fixture
def store(tmp_path,payload,generated):
    path=tmp_path/'queue.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    upgrade_grounded_schema(path,approved=True)
    g=RevisionSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);r=SectionCheckpointRepository(g,enabled=True);rr=RevisionRepository(g,enabled=True)
    prefs={**payload,'budget':10000};owner=uid();p=run(r.create_plan(owner,uid(),prefs))
    for i in range(2):
        s=run(r.claim_next(uid()));s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'submitting'))
        s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_base'+str(i)))
        s=run(r.claim(owner,s['id'],uid()));p=run(r.get_plan(owner,p['id']))
        spec=SectionSpec.from_manifest(prefs,next_date=s['start_date'],spent_cents=p['spent_cents'],previous_boundary=p['previous_boundary'] if i else None,journey_strategy=p['journey_strategy'])
        cp=SectionContract(spec).decode(section_wire(prefs,generated,spec))
        run(r.transition(owner,s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=cp))
    p=run(r.get_plan(owner,p['id']))
    return path,clock,g,r,rr,p

def reserve(store):
    _,_,_,_,rr,p=store
    target=(datetime.fromisoformat(p['start_date'])+timedelta(days=1)).date().isoformat()
    return run(rr.reserve(p['user_id'],p['id'],{'requestId':uid(),'targetDate':target,'instruction':'Prefer a quiet garden.'}))

def submit(rr,j):
    claimed=run(rr.claim_next(uid()));assert claimed['id']==j['id']
    return run(rr.transition(j['user_id'],j['id'],claimed['lease_token'],claimed['version'],'submitting'))

def running(rr,j):
    j=submit(rr,j)
    return run(rr.transition(j['user_id'],j['id'],j['lease_token'],j['version'],'running',provider_response_id='resp_revision'))

def candidate(store,generated):
    _,_,_,_,rr,p=store;j=running(rr,reserve(store));j=run(rr.claim_next(uid()))
    ctx=run(rr.context(p['user_id'],j['id']))
    return run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'candidate',output_text=json.dumps(wire(ctx,generated))))


def test_explicit_schema_upgrade_only(tmp_path):
    path=tmp_path/'q.sqlite'
    with pytest.raises(JobRepositoryError):upgrade_grounded_schema(path,approved=True)
    assert not path.exists()
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    with pytest.raises(JobRepositoryError):upgrade_grounded_schema(path)
    with pytest.raises(JobRepositoryError):RevisionSQLiteGateway(path,enabled=True)
    upgrade_grounded_schema(path,approved=True);upgrade_grounded_schema(path,approved=True)
    RevisionSQLiteGateway(path,enabled=True)


def test_reservation_dedup_owner_and_no_baseline_copy(store):
    path,clock,g,r,rr,p=store;j=reserve(store)
    same=run(rr.reserve(p['user_id'],p['id'],{'requestId':j['request_id'],'targetDate':j['target_date'],'instruction':j['instruction']}))
    assert same['id']==j['id'] and same['remaining_creates']==10
    assert run(r.get_plan(p['user_id'],p['id']))==p
    with g._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM plans').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM sections').fetchone()[0]==2
    with pytest.raises(JobRepositoryError):run(rr.get(uid(),j['id']))
    with pytest.raises(JobRepositoryError,match='REVISION_OWNER_BUSY'):reserve(store)
    with pytest.raises(JobRepositoryError,match='SECTION_OWNER_PLAN_EXISTS'):run(r.create_plan(p['user_id'],uid(),p['preferences']))
    with pytest.raises(JobRepositoryError,match='REVISION_REQUEST_CONFLICT'):
        run(rr.reserve(p['user_id'],p['id'],{'requestId':j['request_id'],'targetDate':j['target_date'],'instruction':'different'}))


def test_candidate_private_and_accept_clones_without_mutating_base(store,generated):
    path,clock,g,r,rr,p=store
    before=run(r.list_sections(p['user_id'],p['id']))
    j=candidate(store,generated);public=public_revision(j)
    assert public['status']=='candidate' and public['accepted'] is False
    assert public['candidate']['accepted'] is False and j['remaining_creates']==9
    text=json.dumps(public)
    for secret in (j['instruction'],'resp_revision','sourceDigest','baseVersion','lease_token'):assert secret not in text
    accepted=run(rr.accept(p['user_id'],j['id']));again=run(rr.accept(p['user_id'],j['id']))
    assert accepted['accepted_plan_id']==again['accepted_plan_id']
    new=run(r.get_plan(p['user_id'],accepted['accepted_plan_id']))
    assert new['status']=='completed' and new['expires_at']==p['expires_at'] and new['remaining_creates']==9
    assert new['revision_budget_root']==p['id'] and new['spent_cents']==j['candidate']['totalSpentCents']
    assert run(r.get_plan(p['user_id'],p['id']))==p and run(r.list_sections(p['user_id'],p['id']))==before
    copied=run(r.list_sections(p['user_id'],new['id']))
    for old,fresh in zip(before,copied):
        for a,b in zip(old['checkpoint']['itinerary']['days'],fresh['checkpoint']['itinerary']['days']):
            if a['date']!=j['target_date']:assert a==b


@pytest.mark.parametrize('kind',['lease','version','provider','boolversion'])
def test_transition_stale_cas_or_provider_never_advances(store,kind):
    *_,rr,p=store;j=running(rr,reserve(store));j=run(rr.claim_next(uid()))
    lease=j['lease_token'];version=j['version'];provider='resp_revision'
    if kind=='lease':lease=uid()
    if kind=='version':version-=1
    if kind=='boolversion':version=True
    if kind=='provider':provider='resp_other'
    with pytest.raises(JobRepositoryError):run(rr.transition(p['user_id'],j['id'],lease,version,'running',provider_response_id=provider))
    saved=run(rr.get(p['user_id'],j['id']));assert saved['version']==j['version'] and saved['status']=='running'


def test_unknown_create_quarantine_restart_no_retry_and_base_expiry(store):
    path,clock,g,r,rr,p=store;j=submit(rr,reserve(store));clock[0]+=61
    fresh=RevisionRepository(RevisionSQLiteGateway(path,enabled=True,clock=lambda:clock[0]),enabled=True)
    assert run(fresh.claim_next(uid())) is None
    j=run(fresh.get(p['user_id'],j['id']));assert j['status']=='submission_unknown' and j['remaining_creates']==9
    with pytest.raises(JobRepositoryError):run(fresh.retry(p['user_id'],j['id'],uid()))
    with pytest.raises(JobRepositoryError):reserve(store)
    run(fresh.reject(p['user_id'],j['id']))
    with pytest.raises(JobRepositoryError):reserve(store)
    clock[0]+=86400;run(g.purge_expired())
    with g._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM revision_jobs').fetchone()[0]==0


@pytest.mark.parametrize('kind',['ttl','expired','planquota','globalquota'])
def test_admission_reason_before_any_paid_intent(store,kind,monkeypatch):
    path,clock,g,r,rr,p=store
    if kind=='ttl':clock[0]+=86400-479
    if kind=='expired':clock[0]+=86401
    if kind=='planquota':mutate(path,'plans',p['id'],storage_limit_bytes=p['storage_used_bytes'])
    if kind=='globalquota':monkeypatch.setattr('app.revision_sqlite.GLOBAL_STORAGE_BYTES',1)
    with pytest.raises(JobRepositoryError):reserve(store)
    with g._connect() as c:assert c.execute('SELECT COUNT(*) FROM revision_jobs').fetchone()[0]==0


def test_reject_candidate_keeps_original_and_no_retention_extension(store,generated):
    path,clock,g,r,rr,p=store;j=candidate(store,generated)
    rejected=run(rr.reject(p['user_id'],j['id']))
    assert rejected['candidate'] is None and rejected['expires_at']==p['expires_at']
    assert run(r.get_plan(p['user_id'],p['id']))==p
    with pytest.raises(JobRepositoryError):run(rr.accept(p['user_id'],j['id']))


def test_allowance_shared_root_never_silently_increases_and_continue_explicit(store):
    path,clock,g,r,rr,p=store
    for i in range(10):
        j=submit(rr,reserve(store))
        run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'failed',error_code='REVISION_PROVIDER_REJECTED'))
        clock[0]+=601
    with pytest.raises(JobRepositoryError,match='REVISION_ALLOWANCE_REACHED'):reserve(store)
    request=uid();continued=run(rr.continue_run(p['user_id'],p['id'],request))
    assert continued['remaining_creates']==12
    assert run(rr.continue_run(p['user_id'],p['id'],request))==continued
    with pytest.raises(JobRepositoryError):run(rr.continue_run(p['user_id'],p['id'],uid()))
    assert reserve(store)['remaining_creates']==12
    assert run(r.get_plan(p['user_id'],p['id']))==p


def test_failed_explicit_retry_is_new_deduplicated_intent(store):
    path,clock,g,r,rr,p=store;j=submit(rr,reserve(store))
    j=run(rr.transition(p['user_id'],j['id'],j['lease_token'],j['version'],'failed',error_code='REVISION_PROVIDER_REJECTED'))
    request=uid();retry=run(rr.retry(p['user_id'],j['id'],request))
    assert retry['id']!=j['id'] and retry['retry_of']==j['id'] and retry['remaining_creates']==9
    assert run(rr.retry(p['user_id'],j['id'],request))['id']==retry['id']
    with pytest.raises(JobRepositoryError):run(rr.retry(p['user_id'],retry['id'],uid()))


def test_concurrent_claim_and_reserve_are_single_winner(store):
    path,clock,g,r,rr,p=store
    request={'requestId':uid(),'targetDate':p['start_date'],'instruction':'A calmer arrival.'}
    async def reserve_race():return await asyncio.gather(*(rr.reserve(p['user_id'],p['id'],request) for _ in range(4)))
    assert len({row['id'] for row in run(reserve_race())})==1
    async def claim_race():return await asyncio.gather(*(rr.claim_next(uid()) for _ in range(4)))
    assert sum(j is not None for j in run(claim_race()))==1


@pytest.mark.parametrize('kind',['baseversion','checkpoint','quota'])
def test_accept_is_atomic_and_revalidates_current_base(store,generated,kind,monkeypatch):
    path,clock,g,r,rr,p=store;j=candidate(store,generated)
    if kind=='baseversion':mutate(path,'plans',p['id'],version=p['version']+1)
    if kind=='checkpoint':
        section=run(r.list_sections(p['user_id'],p['id']))[1];cp=deepcopy(section['checkpoint']);cp['itinerary']['days'][0]['morning']='changed'
        mutate(path,'sections',section['id'],checkpoint=cp)
    if kind=='quota':monkeypatch.setattr('app.revision_sqlite.GLOBAL_STORAGE_BYTES',1)
    with pytest.raises(JobRepositoryError):run(rr.accept(p['user_id'],j['id']))
    with g._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM plans').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM sections').fetchone()[0]==2
    assert run(rr.get(p['user_id'],j['id']))['status']=='candidate'


def test_lookup_current_and_health_are_read_only_owner_scoped(store):
    path,clock,g,r,rr,p=store;j=reserve(store)
    assert run(rr.lookup(p['user_id'],j['request_id']))['id']==j['id']
    assert run(rr.lookup(uid(),j['request_id'])) is None
    assert run(rr.lookup(p['user_id'],uid())) is None
    assert run(rr.current(p['user_id'],p['id']))['id']==j['id']
    assert run(rr.current(uid(),p['id'])) is None
    assert public_revision(j)['requestId']==j['request_id']
    assert public_revision({**j,'error_code':'PRIVATE_STRING'})['errorCode']=='REVISION_REQUEST_FAILED'
    assert public_revision({**j,'error_code':[]})['errorCode']=='REVISION_REQUEST_FAILED'
    with pytest.raises(JobRepositoryError):run(rr.verify_ready())
    run(g.purge_expired());run(rr.verify_ready())
    run(rr.reject(p['user_id'],j['id']))
    assert run(rr.current(p['user_id'],p['id'])) is None


def test_cli_readiness_explicit_upgrade_and_no_expiry_rewrite(tmp_path,capsys,monkeypatch):
    from app.grounded_sqlite_upgrade import main
    from app.research_sqlite import upgrade_research_schema
    path=tmp_path/'q.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    import app.grounded_sqlite_upgrade as cli
    monkeypatch.setattr(cli,'DATABASE',path);monkeypatch.setattr(cli,'verify_volume',lambda:str(path))
    monkeypatch.setattr(cli,'prepare_existing_storage_user',lambda:str(path))
    config={k:'false' for k in ('ADAPTIVE_PLANNING_ENABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_STREAMING_ENABLED')}
    assert main(['--path',str(path),'--check'])==1
    assert json.loads(capsys.readouterr().out)['code']=='GROUNDED_SCHEMA_NOT_READY'
    upgrade_research_schema(path,approved=True)
    with pytest.raises(JobRepositoryError):RevisionSQLiteGateway(path,enabled=True)
    assert main(['--path',str(path),'--approve'],configuration=config)==0
    assert json.loads(capsys.readouterr().out)=={'ready':True,'code':'READY'}
    assert main(['--path',str(path),'--check'])==0
    assert json.loads(capsys.readouterr().out)['ready'] is True


def test_migration_checks_quiescence_inside_transaction(tmp_path,payload):
    path=tmp_path/'q.sqlite';g=AdaptiveSQLiteGateway(path,enabled=True,initialize=True);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload))
    with pytest.raises(JobRepositoryError,match='PLANNING_IN_PROGRESS'):upgrade_grounded_schema(path,approved=True)
    with sqlite3.connect(path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==1
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='revision_jobs'").fetchone()
    run(r.cancel_plan(p['user_id'],p['id']))
    before=run(r.get_plan(p['user_id'],p['id']))
    upgrade_grounded_schema(path,approved=True)
    revised=SectionCheckpointRepository(RevisionSQLiteGateway(path,enabled=True),enabled=True)
    assert run(revised.get_plan(p['user_id'],p['id']))==before


def test_actual_global_two_paid_slots_shared_with_normal_sections(store):
    path,clock,g,r,rr,p=store
    # Owner-isolated completed fixtures, no provider or remote/database service.
    originals=run(r.list_sections(p['user_id'],p['id']))
    plans=[p]
    with g._connect() as c:
        for i in range(2):
            cloned={**p,'id':uid(),'user_id':uid(),'request_id':uid()};plans.append(cloned)
            c.execute('INSERT INTO plans VALUES(?,?,?,?)',(cloned['id'],cloned['user_id'],cloned['request_id'],json.dumps(cloned)))
            for old in originals:
                s={**old,'id':uid(),'plan_id':cloned['id'],'user_id':cloned['user_id'],'request_id':uid()}
                c.execute('INSERT INTO sections VALUES(?,?,?,?,?,?)',(s['id'],s['plan_id'],s['user_id'],s['request_id'],s['sequence'],json.dumps(s)))
    for base in plans:run(rr.reserve(base['user_id'],base['id'],{'requestId':uid(),'targetDate':base['start_date'],'instruction':'A gentle arrival.'}))
    assert run(rr.claim_next(uid())) is not None
    assert run(rr.claim_next(uid())) is not None
    assert run(rr.claim_next(uid())) is None
    normal=run(r.create_plan(uid(),uid(),p['preferences']))
    section=run(r.next_section(normal['user_id'],normal['id'],uid()))
    with pytest.raises(JobRepositoryError):run(r.claim(normal['user_id'],section['id'],uid()))


def test_accept_failure_halfway_rolls_back_all_copied_rows(store,generated,monkeypatch):
    import app.revision_sqlite as module
    path,clock,g,r,rr,p=store;j=candidate(store,generated)
    actual=module.validate_checkpoint;calls=[0]
    def broken(*args):
        calls[0]+=1
        if calls[0]==2:raise JobRepositoryError('REVISION_INVALID_RESULT',400)
        return actual(*args)
    monkeypatch.setattr(module,'validate_checkpoint',broken)
    with pytest.raises(JobRepositoryError):run(rr.accept(p['user_id'],j['id']))
    with g._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM plans').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM sections').fetchone()[0]==2
    assert run(rr.get(p['user_id'],j['id']))['status']=='candidate'


def test_accepted_clone_revisions_share_original_allowance(store,generated):
    path,clock,g,r,rr,p=store;j=candidate(store,generated);accepted=run(rr.accept(p['user_id'],j['id']))
    clone=run(r.get_plan(p['user_id'],accepted['accepted_plan_id']))
    nextjob=run(rr.reserve(p['user_id'],clone['id'],{'requestId':uid(),'targetDate':j['target_date'],'instruction':'Adjust again.'}))
    assert nextjob['remaining_creates']==9 and nextjob['root_id']==p['id']
    nextjob=submit(rr,nextjob)
    run(rr.transition(p['user_id'],nextjob['id'],nextjob['lease_token'],nextjob['version'],'failed',error_code='REVISION_PROVIDER_REJECTED'))
    assert reserve(store)['remaining_creates']==8


@pytest.mark.parametrize('kind',['path','volume','stage'])
def test_cli_guards_never_mutate_wrong_path_volume_or_live_stage(tmp_path,capsys,monkeypatch,kind):
    import app.grounded_sqlite_upgrade as cli
    path=tmp_path/'q.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    monkeypatch.setattr(cli,'DATABASE',path)
    monkeypatch.setattr(cli,'verify_volume',lambda:str(path) if kind!='volume' else '/wrong-volume/private')
    config={k:'false' for k in ('ADAPTIVE_PLANNING_ENABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_STREAMING_ENABLED')}
    if kind=='stage':config['ADAPTIVE_PLANNING_ENABLED']='true'
    requested=str(path) if kind!='path' else str(tmp_path/'other.sqlite')
    assert cli.main(['--path',requested,'--approve'],configuration=config)==1
    result=json.loads(capsys.readouterr().out)
    assert result['ready'] is False and result['code'] in {'SQLITE_STORAGE_UNVERIFIED','GROUNDED_STAGE_REQUIRED'}
    assert str(path) not in json.dumps(result) and '/private' not in json.dumps(result)
    with sqlite3.connect(path) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==1


def test_schema_signature_mismatch_fails_closed_without_auto_repair(store):
    path,clock,g,r,rr,p=store
    with g._connect() as c:c.execute('ALTER TABLE revision_controls ADD COLUMN unexpected TEXT')
    with pytest.raises(JobRepositoryError,match='REVISION_SCHEMA_NOT_READY'):RevisionSQLiteGateway(path,enabled=True)
    with pytest.raises(JobRepositoryError):upgrade_grounded_schema(path,approved=True)
