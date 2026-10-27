import asyncio
import os
import pytest
from app import adaptive_sqlite_runtime as runtime
from app import adaptive_sqlite_preflight as cli
from app.adaptive_activation import approved,SQLITE_APPROVALS
from app.adaptive_coordinator import AdaptiveCoordinator
from app.planning_repository import JobRepositoryError


def configure_path(monkeypatch,tmp_path):
    mount=tmp_path/'volume';mount.mkdir();directory=mount/'checkpoints';directory.mkdir(mode=0o700);database=directory/'planning.sqlite3'
    monkeypatch.setattr(runtime,'MOUNT',mount);monkeypatch.setattr(runtime,'DIRECTORY',directory);monkeypatch.setattr(runtime,'DATABASE',database)
    monkeypatch.setattr(runtime,'UID',os.getuid());monkeypatch.setattr(runtime,'GID',os.getgid());monkeypatch.setattr(runtime.os.path,'ismount',lambda p:p==mount)
    return mount,directory,database


def test_mount_private_directory_and_database_required(monkeypatch,tmp_path):
    _,_,database=configure_path(monkeypatch,tmp_path)
    with pytest.raises(JobRepositoryError):runtime.verify_volume()
    database.touch(mode=0o600);assert runtime.verify_volume()==str(database)
    database.chmod(0o644)
    with pytest.raises(JobRepositoryError):runtime.verify_volume()
    database.chmod(0o600);monkeypatch.setattr(runtime.os.path,'ismount',lambda p:False)
    with pytest.raises(JobRepositoryError):runtime.verify_volume()


def test_symlink_and_hardlink_refused(monkeypatch,tmp_path):
    _,_,database=configure_path(monkeypatch,tmp_path);external=tmp_path/'other';external.touch(mode=0o600);database.symlink_to(external)
    with pytest.raises(JobRepositoryError):runtime.verify_volume()
    database.unlink();os.link(external,database)
    with pytest.raises(JobRepositoryError):runtime.verify_volume()


def test_sqlite_approval_does_not_require_database_credential_flags():
    config={**dict.fromkeys(SQLITE_APPROVALS,'true'),'ADAPTIVE_PLANNING_ENABLED':'true','PLANNING_WORKER_TRANSPORT':'sqlite'}
    assert approved(config)
    for key in SQLITE_APPROVALS:assert not approved({**config,key:'false'})
    assert not approved({**config,'PLANNING_JOBS_ENABLED':'true'})


def test_preflight_denied_and_errors_private(monkeypatch):
    assert asyncio.run(cli.preflight({}))=={'ready':False,'code':'PREFLIGHT_DISABLED'}
    config={'ADAPTIVE_PREFLIGHT_APPROVED':'true'}
    assert asyncio.run(cli.preflight(config,initialize=True))['code']=='INITIALIZATION_DISABLED'
    def fail():raise RuntimeError('private fixture path and secret')
    monkeypatch.setattr(cli,'verify_volume',fail)
    assert asyncio.run(cli.preflight(config))=={'ready':False,'code':'PREFLIGHT_FAILED'}


def test_preflight_real_file_cleanup_and_health(monkeypatch,tmp_path):
    _,_,database=configure_path(monkeypatch,tmp_path)
    from app.adaptive_sqlite import AdaptiveSQLiteGateway
    AdaptiveSQLiteGateway(str(database),enabled=True,initialize=True)
    assert asyncio.run(cli.preflight({'ADAPTIVE_PREFLIGHT_APPROVED':'true'}))=={'ready':True,'code':'READY'}


def test_maintenance_precedes_health_and_failure_closes_readiness():
    calls=[]
    class Repo:
        async def verify_ready(self):calls.append('health')
    async def maintain():calls.append('purge')
    engine=AdaptiveCoordinator(Repo(),object(),enabled=True,maintenance=maintain)
    async def run():
        await engine.verify_ready();await engine.verify_ready();assert calls==['purge','health','health'] and engine.capability_ready()
        engine._maintained=None
        async def failed():raise RuntimeError('private')
        engine._maintenance=failed
        with pytest.raises(RuntimeError):await engine.verify_ready()
        assert not engine.capability_ready()
    asyncio.run(run())
