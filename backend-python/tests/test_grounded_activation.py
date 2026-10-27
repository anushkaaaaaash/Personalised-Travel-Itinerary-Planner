import asyncio
import pytest
from app.adaptive_activation import SQLITE_APPROVALS,build_production_adaptive
from app.grounded_activation import RESEARCH_APPROVALS,research_approved,build_grounded
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.grounded_sqlite_upgrade import upgrade_grounded_schema as upgrade_research_schema
from app import adaptive_sqlite_runtime


def config():
    return {**dict.fromkeys(SQLITE_APPROVALS,'true'),**dict.fromkeys(RESEARCH_APPROVALS,'true'),
        'ADAPTIVE_PLANNING_ENABLED':'true','PLANNING_WORKER_TRANSPORT':'sqlite',
        'ADAPTIVE_RESEARCH_ENABLED':'true','ADAPTIVE_STREAMING_ENABLED':'true','OPENAI_API_KEY':'SYNTHETIC_NO_CALL'}

@pytest.mark.parametrize('flag',RESEARCH_APPROVALS)
def test_all_research_permissions_fail_closed_before_mount(flag,monkeypatch):
    def forbidden():raise AssertionError('Mount should not be opened')
    monkeypatch.setattr(adaptive_sqlite_runtime,'verify_volume',forbidden)
    c=config();c[flag]='false';assert not research_approved(c)
    with pytest.raises(RuntimeError):build_grounded(c)


def test_budget_cannot_be_silently_increased():
    for limit in ['7','12','0','six']:
        assert not research_approved({**config(),'ADAPTIVE_RESEARCH_MAX_TOOLS':limit})
    assert not research_approved({**config(),'PLANNING_WORKER_TRANSPORT':'postgres'})


def test_actual_schema2_runtime_ready_without_provider_calls(tmp_path,monkeypatch):
    path=tmp_path/'queue';AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    monkeypatch.setattr(adaptive_sqlite_runtime,'verify_volume',lambda:str(path))
    with pytest.raises(Exception):build_production_adaptive(config())  # no implicit schema mutation
    upgrade_research_schema(path,approved=True)
    engine=build_production_adaptive(config())
    asyncio.run(engine.verify_ready())
    assert engine.capability_ready()
    assert engine.public_policy()['maxWebSearchCalls']==6
    assert engine.public_policy()['provisionalDayPreviews'] is True
    assert engine.worker.sections.client.reasoning_effort=='high'
    assert engine.worker.sections.preview_store is not None
    assert asyncio.run(engine.repository.gateway.request('POST','rpc/adaptive_find_current',payload={'owner':'12345678-1234-1234-1234-123456789abc'}))==[]
    asyncio.run(engine.close())


def test_capability_stays_false_until_both_health_contracts_pass(tmp_path,monkeypatch):
    path=tmp_path/'queue';AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    monkeypatch.setattr(adaptive_sqlite_runtime,'verify_volume',lambda:str(path))
    engine=build_production_adaptive(config())
    async def health():
        assert engine.capability_ready() is False
        raise RuntimeError('synthetic health failure')
    monkeypatch.setattr(engine.research_repository,'verify_ready',health)
    with pytest.raises(RuntimeError):asyncio.run(engine.verify_ready())
    assert engine.capability_ready() is False
    asyncio.run(engine.close())
