import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from app.section_repository import SectionCheckpointRepository, validate_checkpoint
from app.planning_repository import JobRepositoryError
from app.adaptive_planning import SectionSpec, SectionContract
from test_adaptive_planning import section_wire
from test_itineraries import generated

OWNER=str(uuid4())


class Gateway:
    elevated=True
    def __init__(self): self.calls=[];self.rows=None;self.saved=None;self.ambiguous=False
    async def request(self,method,resource,*,payload):
        self.calls.append((method,resource,payload))
        if resource=='rpc/adaptive_create_plan':
            self.saved={'id':str(uuid4()),'user_id':payload['owner'],**payload}
            if self.ambiguous: raise RuntimeError('private upstream detail')
            return [self.saved]
        if resource=='rpc/adaptive_find_request': return [self.saved] if self.saved else []
        if self.rows is not None:return self.rows
        return [{'id':str(uuid4()),'user_id':payload.get('owner',OWNER)}]


def test_disabled_and_untrusted_gateway():
    with pytest.raises(JobRepositoryError): SectionCheckpointRepository(Gateway())
    with pytest.raises(JobRepositoryError): SectionCheckpointRepository(object(),enabled=True)


def test_plan_long_range_exact_money_and_ambiguous_create_reconciles(payload):
    async def scenario():
        gateway=Gateway();gateway.ambiguous=True;repo=SectionCheckpointRepository(gateway,enabled=True)
        p={**payload,'startDate':'2028-01-01','endDate':'9999-12-31'}
        row=await repo.create_plan(OWNER,str(uuid4()),p)
        assert row['preferences']['endDate']=='9999-12-31'
        assert row['budget_cents']==250000
        assert [r for _,r,_ in gateway.calls]==['rpc/adaptive_create_plan','rpc/adaptive_find_request']
    asyncio.run(scenario())


@pytest.mark.parametrize('budget',[1.001,92233720368547758.08,90071992547410.0])
def test_non_cent_money_or_bigint_resource_overflow_rejected_before_gateway(payload,budget):
    async def scenario():
        gateway=Gateway();repo=SectionCheckpointRepository(gateway,enabled=True)
        with pytest.raises(JobRepositoryError):await repo.create_plan(OWNER,str(uuid4()),{**payload,'budget':budget})
        assert gateway.calls==[]
    asyncio.run(scenario())


def test_bounds_and_owner_isolation():
    async def scenario():
        gateway=Gateway();repo=SectionCheckpointRepository(gateway,enabled=True);plan=str(uuid4())
        for size in (0,4,True):
            with pytest.raises(JobRepositoryError): await repo.list_sections(OWNER,plan,limit=size)
            with pytest.raises(JobRepositoryError): await repo.next_section(OWNER,plan,str(uuid4()),section_days=size)
        gateway.rows=[{'user_id':str(uuid4())}]
        with pytest.raises(JobRepositoryError):await repo.get_plan(OWNER,plan)
        gateway.rows=[{'user_id':OWNER}]*4
        with pytest.raises(JobRepositoryError):await repo.list_sections(OWNER,plan)
    asyncio.run(scenario())


def test_claim_next_and_health_fail_closed():
    async def scenario():
        gateway=Gateway();repo=SectionCheckpointRepository(gateway,enabled=True)
        gateway.rows=[];assert await repo.claim_next(str(uuid4())) is None
        gateway.rows=[{'schema_version':1,'rpc_version':1,'cleanup_fresh':True}];await repo.verify_ready()
        gateway.rows[0]['cleanup_fresh']=False
        with pytest.raises(JobRepositoryError): await repo.verify_ready()
    asyncio.run(scenario())


def test_checkpoint_matches_domain_and_rejects_mutated_cost_boundary_provenance(payload,generated):
    spec=SectionSpec.from_manifest(payload,section_days=2)
    checkpoint=SectionContract(spec).decode(section_wire(payload,generated,spec))
    section={'start_date':spec.start.isoformat(),'end_date':spec.end.isoformat(),
        'input_boundary':{'location':spec.start_location},'budget_limit_cents':250000,'final_section':False,'departure_city':payload['departureCity']}
    assert validate_checkpoint(checkpoint,section)==checkpoint
    for key,value in [('startLocation','Elsewhere'),('spentCents',1),('provenance',{'provider':'openai','model':'gpt-6-luna','validationVersion':'untrusted'})]:
        bad=deepcopy(checkpoint);bad[key]=value
        with pytest.raises(JobRepositoryError):validate_checkpoint(bad,section)


def test_failure_details_are_proposals_not_raw_errors():
    async def scenario():
        gateway=Gateway();repo=SectionCheckpointRepository(gateway,enabled=True)
        details={'applicability':'proposed','explanation':'Travel cannot fit this section.',
            'recommendations':[{'field':'travelPace','reason':'Too many activities.','suggestion':'Consider relaxed pace.'}]}
        await repo.transition(OWNER,str(uuid4()),str(uuid4()),1,'failed',error_code='SECTION_CONSTRAINT_CONFLICT',failure_details=details)
        assert gateway.calls[-1][2]['failure_details']==details
        for bad in ({**details,'exception':'raw provider error'}, {**details,'applicability':'applied'}, {**details,'recommendations':details['recommendations']*4}):
            with pytest.raises(JobRepositoryError):await repo.transition(OWNER,str(uuid4()),str(uuid4()),1,'failed',error_code='SECTION_CONSTRAINT_CONFLICT',failure_details=bad)
    asyncio.run(scenario())


@pytest.mark.parametrize('code,status',[('SECTION_ADMISSION_REJECTED',429),('SECTION_REQUEST_CONFLICT',409)])
def test_definite_admission_rejection_is_not_reclassified_as_ambiguous(payload,code,status):
    class Rejected(Gateway):
        async def request(self,*args,**kwargs):
            self.calls.append((args,kwargs))
            raise JobRepositoryError(code,status)
    async def scenario():
        gateway=Rejected();repo=SectionCheckpointRepository(gateway,enabled=True)
        with pytest.raises(JobRepositoryError) as caught:await repo.create_plan(OWNER,str(uuid4()),payload)
        assert caught.value.code==code and caught.value.status==status and len(gateway.calls)==1
    asyncio.run(scenario())


def test_recent_checkpoints_is_separate_bounded_owner_lookup():
    async def scenario():
        gateway=Gateway();gateway.rows=[{'user_id':OWNER,'sequence':9},{'user_id':OWNER,'sequence':4}]
        repo=SectionCheckpointRepository(gateway,enabled=True);plan=str(uuid4())
        assert [row['sequence'] for row in await repo.recent_checkpoints(OWNER,plan)]==[9,4]
        assert gateway.calls[-1][1]=='rpc/adaptive_recent_checkpoints'
        assert gateway.calls[-1][2]=={'owner':OWNER,'plan':plan}
    asyncio.run(scenario())
