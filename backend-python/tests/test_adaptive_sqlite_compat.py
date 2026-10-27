import asyncio
import sqlite3
from uuid import uuid4
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.adaptive_sqlite_compat import build_legacy_sqlite_gateway
from app.grounded_sqlite_upgrade import upgrade_grounded_schema
from app.research_sqlite import upgrade_research_schema
from app.section_repository import SectionCheckpointRepository
from app.planning_repository import JobRepositoryError


def run(c):return asyncio.run(c)
def uid():return str(uuid4())


@pytest.mark.parametrize('version',[1,2])
def test_flags_off_works_before_and_after_explicit_upgrade(tmp_path,payload,version):
    path=tmp_path/'queue.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    if version==2:upgrade_grounded_schema(path,approved=True)
    g=build_legacy_sqlite_gateway(path,enabled=True);r=SectionCheckpointRepository(g,enabled=True)
    run(g.purge_expired());run(r.verify_ready())
    assert g.schema_version==version and getattr(g,'research_enabled',False) is False
    p=run(r.create_plan(uid(),uid(),payload));assert not p.get('research_on_demand')
    section=run(r.claim_next(uid()));assert section['status']=='queued'
    with sqlite3.connect(path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==version
        if version==2:assert c.execute('SELECT COUNT(*) FROM research_jobs').fetchone()[0]==0


def test_no_missing_store_recreation_or_partial_v2_acceptance(tmp_path):
    path=tmp_path/'queue.sqlite'
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(path,enabled=True)
    assert not path.exists()
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(path,enabled=True)
    with sqlite3.connect(path) as c:assert not c.execute("SELECT name FROM sqlite_master WHERE name='revision_jobs'").fetchone()


def test_unknown_schema_and_runtime_mismatch_fail_closed(tmp_path):
    path=tmp_path/'queue.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    with sqlite3.connect(path) as c:c.execute('PRAGMA user_version=3')
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(path,enabled=True)
    with sqlite3.connect(path) as c:c.execute('PRAGMA user_version=1');c.execute('UPDATE runtime SET version=2')
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(path,enabled=True)


def test_symlink_disabled_and_base_gateway_version_still_fail_closed(tmp_path):
    path=tmp_path/'queue.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True);link=tmp_path/'link.sqlite';link.symlink_to(path)
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(link,enabled=True)
    with pytest.raises(JobRepositoryError):build_legacy_sqlite_gateway(path)
    upgrade_grounded_schema(path,approved=True)
    with pytest.raises(JobRepositoryError):AdaptiveSQLiteGateway(path,enabled=True)


def test_v2_keeps_research_shared_paid_capacity_flags_off(tmp_path,payload):
    import json
    path=tmp_path/'queue.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_grounded_schema(path,approved=True)
    g=build_legacy_sqlite_gateway(path,enabled=True);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload))
    with sqlite3.connect(path) as c:
        for phase in ('initial','refresh'):
            job=uid();c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?)',(job,p['id'],p['user_id'],uid(),1,phase,json.dumps({'status':'running','reserved_sourcepack_bytes':65536})))
    assert run(r.claim_next(uid())) is None
    with g._connect() as c:
        assert g._paid_work_count(c,g.clock())==2
        assert g._allocated(c)>=131072


@pytest.mark.parametrize('version',[1,2])
def test_production_flags_off_factory_and_preflight_schema_compatibility(tmp_path,monkeypatch,version):
    from app import adaptive_sqlite_runtime as runtime,adaptive_sqlite_preflight as cli
    from app.adaptive_activation import build_production_adaptive,SQLITE_APPROVALS
    path=tmp_path/'queue.sqlite';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    if version==2:upgrade_grounded_schema(path,approved=True)
    monkeypatch.setattr(runtime,'verify_volume',lambda:str(path));monkeypatch.setattr(cli,'verify_volume',lambda:str(path))
    monkeypatch.setattr(cli,'prepare_existing_storage_user',lambda:str(path))
    assert run(cli.preflight({'ADAPTIVE_PREFLIGHT_APPROVED':'true'}))=={'ready':True,'code':'READY'}
    class Client:
        def __init__(self,*args,**kwargs):pass
    config={**dict.fromkeys(SQLITE_APPROVALS,'true'),'ADAPTIVE_PLANNING_ENABLED':'true','PLANNING_WORKER_TRANSPORT':'sqlite','ADAPTIVE_RESEARCH_ENABLED':'false'}
    engine=build_production_adaptive(config,client_factory=Client)
    run(engine.verify_ready());assert engine.capability_ready()
    assert not hasattr(engine,'public_policy') and engine.run_allowance==12
