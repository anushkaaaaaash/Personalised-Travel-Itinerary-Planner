import asyncio
import pytest
from app.planning_activation import build_production_planning,activation_approved,REQUIRED_APPROVALS
from app.planning_repository import DurablePlanningRepository,JobRepositoryError


def config():
    return {'PLANNING_JOBS_ENABLED':'true',**{name:'true' for name in REQUIRED_APPROVALS},
            'PLANNING_PURGE_JOB_NAME':'purge-planning-jobs','PLANNING_WORKER_TRANSPORT':'postgres',
            'PLANNING_DATABASE_URL':'postgresql://planning_queue_worker.fakeprojectref:fakepassword@aws-0-test.pooler.supabase.com:5432/postgres','OPENAI_API_KEY':'fake-not-real-key'}

def test_default_off_and_partial_approval_never_construct_clients():
    def forbidden(*a,**k):pytest.fail('Incomplete gate constructed provider')
    assert build_production_planning({},gateway_factory=forbidden,client_factory=forbidden) is None
    for flag in REQUIRED_APPROVALS:
        values=config();values.pop(flag)
        assert not activation_approved(values)
        with pytest.raises(RuntimeError,match='gates are incomplete'):
            build_production_planning(values,gateway_factory=forbidden,client_factory=forbidden)

def test_approved_factory_is_durable_and_health_required():
    calls=[]
    class Gateway:
        elevated=True
        def __init__(self,*a,**k):calls.append('gateway')
        async def request(self,*a,**k):return [{'schema_version':1,'rpc_version':1,'cron_installed':True,'cleanup_fresh':True}]
    def client(*a,**kwargs):
        calls.append('provider');assert kwargs['activation'].temporary_retention_approved
        return object()
    coordinator=build_production_planning(config(),gateway_factory=Gateway,client_factory=client)
    assert coordinator.require_health and calls==['gateway','provider']
    asyncio.run(coordinator.verify_ready())

def test_health_missing_cron_or_rpc_version_fails_closed():
    class Gateway:
        elevated=True
        async def request(self,*a,**k):return [{'schema_version':1,'rpc_version':1,'cron_installed':False,'cleanup_fresh':False}]
    repo=DurablePlanningRepository(Gateway(),enabled=True)
    with pytest.raises(JobRepositoryError,match='JOB_SCHEMA_NOT_READY'):asyncio.run(repo.verify_ready())
