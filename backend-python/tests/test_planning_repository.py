import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from app.planning_repository import DurablePlanningRepository, JobRepositoryError

OWNER, OTHER, REQUEST = (str(uuid4()) for _ in range(3))
class Gateway:
    elevated = True
    def __init__(self):
        self.rows=[]; self.calls=[]; self.lose_response=False
    async def request(self,method,resource,params=None,payload=None):
        self.calls.append((method,resource,params,payload))
        if method=='GET':
            return [deepcopy(row) for row in self.rows if all(row.get(k)==v[3:] for k,v in params.items() if k!='limit')]
        if method=='POST' and resource=='rpc/enqueue_planning_job':
            payload=payload['request_row']
            self.rows.append(deepcopy(payload))
            if self.lose_response: raise RuntimeError('secret')
            return [deepcopy(payload)]
        return []

def test_disabled_and_no_elevated_default():
    with pytest.raises(JobRepositoryError,match='DISABLED'): DurablePlanningRepository(Gateway())
    gateway=Gateway();gateway.elevated=False
    with pytest.raises(JobRepositoryError,match='CONTEXT_REQUIRED'): DurablePlanningRepository(gateway,enabled=True)

def test_dedup_and_owner_isolation(payload):
    async def run():
        gateway=Gateway();repo=DurablePlanningRepository(gateway,enabled=True)
        first=await repo.enqueue(OWNER,REQUEST,payload)
        assert await repo.enqueue(OWNER,REQUEST,payload)==first
        assert sum(method=='POST' for method,*_ in gateway.calls)==1
        with pytest.raises(JobRepositoryError,match='CONFLICT'):
            await repo.enqueue(OWNER,REQUEST,{**payload,'destination':'Paris'})
        with pytest.raises(JobRepositoryError,match='NOT_FOUND'):
            await repo.get(OTHER,first['id'])
        assert (await repo.enqueue(OTHER,REQUEST,payload))['id']!=first['id']
    asyncio.run(run())

def test_ambiguous_insert_reconciles_without_second_write(payload):
    async def run():
        gateway=Gateway();gateway.lose_response=True
        repo=DurablePlanningRepository(gateway,enabled=True)
        row=await repo.enqueue(OWNER,REQUEST,payload)
        assert row['status']=='queued'
        assert [c[0] for c in gateway.calls]==['GET','POST','GET']
    asyncio.run(run())

def test_unconfirmed_insert_never_blind_retry(payload):
    class Broken(Gateway):
        async def request(self,method,resource,params=None,payload=None):
            self.calls.append(method)
            if method=='POST':raise RuntimeError('SECRET')
            return []
    async def run():
        gateway=Broken();repo=DurablePlanningRepository(gateway,enabled=True)
        with pytest.raises(JobRepositoryError,match='JOB_START_UNCONFIRMED') as error:
            await repo.enqueue(OWNER,REQUEST,payload)
        assert 'SECRET' not in str(error.value)
        assert gateway.calls==['GET','POST','GET']
    asyncio.run(run())

def test_cas_loss_and_injection_fail_closed():
    async def run():
        gateway=Gateway();repo=DurablePlanningRepository(gateway,enabled=True)
        with pytest.raises(JobRepositoryError,match='LEASE_LOST'):
            await repo.transition(str(uuid4()),str(uuid4()),1,'running',provider_response_id='resp_test')
        with pytest.raises(JobRepositoryError,match='INVALID_JOB_ID'):
            await repo.get('x&select=*',str(uuid4()))
    asyncio.run(run())

def test_public_snapshot_hides_private_fields_and_expired_results(payload):
    from app.planning_repository import public_job_snapshot
    from datetime import datetime, timezone, timedelta
    now=datetime.now(timezone.utc)
    row={'id':str(uuid4()),'request_id':REQUEST,'user_id':OWNER,'status':'running',
         'preferences':payload,'provider_response_id':'secret','lease_token':'secret',
         'created_at':(now-timedelta(hours=1)).isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat()}
    result=public_job_snapshot(row,OWNER,now=now)
    assert not {'preferences','provider_response_id','lease_token','user_id'} & result.keys()
    assert result['status']=='running'
    row.update(status='succeeded',result={'SECRET':'bad'})
    assert public_job_snapshot(row,OWNER,now=now+timedelta(hours=2))['status']=='expired'
    with pytest.raises(JobRepositoryError):public_job_snapshot(row,OTHER,now=now)

def test_gateway_fixed_paths_and_transport_privacy():
    import httpx
    from app.planning_repository import PlanningGateway
    async def run():
        seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,json=[])
        gateway=PlanningGateway('https://testproject.supabase.co','sb_secret_fake_test_key',enabled=True,transport=httpx.MockTransport(respond))
        await gateway.request('GET','planning_jobs',params={'limit':'1'})
        assert seen[0].headers['apikey']=='sb_secret_fake_test_key'
        assert 'authorization' not in seen[0].headers
        with pytest.raises(JobRepositoryError,match='INVALID_JOB_OPERATION'):
            await gateway.request('GET','saved_itineraries')
        with pytest.raises(JobRepositoryError):PlanningGateway('http://evil.test','secret',enabled=True)
    asyncio.run(run())

def test_gateway_accepts_bounded_evidence_rich_row_and_rejects_oversize():
    import httpx
    from app.planning_repository import PlanningGateway
    async def run():
        for size, accepted in ((350000,True),(525000,False)):
            gateway=PlanningGateway('https://testproject.supabase.co','sb_secret_fake_test_key',enabled=True,
                transport=httpx.MockTransport(lambda request:httpx.Response(200,json=[{'evidence':{'padding':'x'*size}}])))
            if accepted:assert len((await gateway.request('GET','planning_jobs'))[0]['evidence']['padding'])==size
            else:
                with pytest.raises(JobRepositoryError):await gateway.request('GET','planning_jobs')
    asyncio.run(run())

def test_concurrent_duplicate_rpc_hash_conflict_is_409(payload):
    class Raced(Gateway):
        async def request(self,method,resource,params=None,payload=None):
            if method=='GET':return []
            return [{**payload['request_row'],'input_hash':'b'*64}]
    async def run():
        with pytest.raises(JobRepositoryError) as error:
            await DurablePlanningRepository(Raced(),enabled=True).enqueue(OWNER,REQUEST,payload)
        assert error.value.status==409 and error.value.code=='JOB_REQUEST_CONFLICT'
    asyncio.run(run())

def test_exact_admission_rejection_is_definitive_but_arbitrary_errors_are_not(payload):
    import httpx
    from app.planning_repository import PlanningGateway
    async def run():
        calls=[]
        def handler(request):
            calls.append(request.method)
            if request.method=='GET':return httpx.Response(200,json=[])
            return httpx.Response(400,json={'code':'P0001','message':'Planning admission limit reached'})
        gateway=PlanningGateway('https://testproject.supabase.co','sb_secret_fake_test_key',enabled=True,transport=httpx.MockTransport(handler))
        with pytest.raises(JobRepositoryError) as error:
            await DurablePlanningRepository(gateway,enabled=True).enqueue(OWNER,REQUEST,payload)
        assert error.value.status==429 and error.value.code=='JOB_ADMISSION_REJECTED'
        assert calls==['GET','POST']
    asyncio.run(run())
