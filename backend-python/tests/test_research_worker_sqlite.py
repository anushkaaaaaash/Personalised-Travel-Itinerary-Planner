"""Actual durable queue and worker with fake Responses only."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from uuid import uuid4
import asyncio
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.research_sqlite import ResearchSQLiteGateway,upgrade_research_schema
from app.research_repository import ResearchCheckpointRepository
from app.section_repository import SectionCheckpointRepository
from app.adaptive_research_worker import AdaptiveResearchWorker
from app.adaptive_research import ResearchResponse,ResearchResult,ResearchSource,ResearchCitation
from app.openai_background import BackgroundError


def uid():return str(uuid4())
def run(c):return asyncio.run(c)
class FakeResearch:
    def __init__(self,clock,*,failure=None):self.clock=clock;self.failure=failure;self.creates=[];self.retrieves=[];self.cancelled=[]
    async def create(self,query,*,phase):
        self.creates.append((query,phase))
        if self.failure:raise self.failure
        return ResearchResponse('resp_research_one','queued')
    async def retrieve(self,id,*,query,phase):
        self.retrieves.append(id);stamp=self.clock()
        result=ResearchResult(query,stamp.isoformat(),(stamp+timedelta(hours=24)).isoformat(),1,
            'Published transport guidance; applicability unknown.',
            (ResearchSource('https://example.org/official','Visitor guide',True,True),),
            (ResearchCitation(0,9,'https://example.org/official','Visitor guide'),))
        return ResearchResponse(id,'completed',result)
    async def cancel(self,id):self.cancelled.append(id)

@pytest.fixture
def setup(tmp_path):
    path=tmp_path/'queue.sqlite';clock=[datetime(2026,10,27,tzinfo=timezone.utc)]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,research_enabled=True,clock=lambda:clock[0].timestamp())
    plans=SectionCheckpointRepository(g,enabled=True);research=ResearchCheckpointRepository(g,enabled=True)
    return path,clock,g,plans,research


def triggered(plans,research,payload):
    p=run(plans.create_plan(uid(),uid(),payload));section=run(plans.next_section(p['user_id'],p['id'],uid()))
    section=run(plans.claim(p['user_id'],section['id'],uid()))
    section=run(plans.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'submitting'))
    section=run(plans.transition(p['user_id'],section['id'],section['lease_token'],section['version'],'running',provider_response_id='resp_trigger'))
    section=run(plans.claim(p['user_id'],section['id'],uid()))
    run(research.request_research(p['user_id'],section['id'],section['lease_token'],section['version'],'transport'))
    return run(plans.get_plan(p['user_id'],p['id']))


def test_triggered_research_paid_once_restart_same_id_unlocks_sections(setup,payload):
    path,clock,g,plans,research=setup
    p=triggered(plans,research,payload);provider=FakeResearch(lambda:clock[0])
    worker=AdaptiveResearchWorker(research,plans,provider,enabled=True,clock=lambda:clock[0])
    running=run(worker.tick());assert running['status']=='running'
    current=run(plans.get_plan(p['user_id'],p['id']))
    assert current['remaining_creates']==10 and current['tool_calls_reserved']==4
    assert len(provider.creates)==1
    g2=ResearchSQLiteGateway(path,enabled=True,research_enabled=True,clock=lambda:clock[0].timestamp())
    r2=ResearchCheckpointRepository(g2,enabled=True);p2=SectionCheckpointRepository(g2,enabled=True)
    provider2=FakeResearch(lambda:clock[0]);fresh=AdaptiveResearchWorker(r2,p2,provider2,enabled=True,clock=lambda:clock[0])
    success=run(fresh.tick());assert success['status']=='succeeded'
    assert provider2.creates==[] and provider2.retrieves==['resp_research_one']
    current=run(p2.get_plan(p['user_id'],p['id']));assert current['remaining_creates']==10
    section=next(row for row in run(p2.list_sections(p['user_id'],p['id'])) if row['status']=='queued')
    assert section['research_source_id']==success['id']
    assert success['sourcepack']['query']['destination']==payload['destination']
    assert success['sourcepack']['applicability']=='unknown'


@pytest.mark.parametrize('ambiguous',[True,False])
def test_create_failure_never_automatically_replays_or_unlocks(setup,payload,ambiguous):
    _,clock,g,plans,research=setup;p=triggered(plans,research,payload)
    provider=FakeResearch(lambda:clock[0],failure=BackgroundError('BACKGROUND_TRANSPORT_FAILED',ambiguous_create=ambiguous))
    worker=AdaptiveResearchWorker(research,plans,provider,enabled=True,clock=lambda:clock[0])
    result=run(worker.tick());assert result['status']==('submission_unknown' if ambiguous else 'failed')
    assert run(worker.tick()) is None
    assert len(provider.creates)==1 and provider.retrieves==[]
    assert run(research.latest(p['user_id'],p['id'])) is None
    assert run(plans.claim_next(uid())) is None
    current=run(plans.get_plan(p['user_id'],p['id']))
    assert current['remaining_creates']==10 and current['tool_calls_reserved']==4


def test_invalid_sourcepack_is_not_accepted(setup,payload):
    _,clock,g,plans,research=setup;p=triggered(plans,research,payload)
    provider=FakeResearch(lambda:clock[0]);worker=AdaptiveResearchWorker(research,plans,provider,enabled=True,clock=lambda:clock[0])
    run(worker.tick())
    async def corrupt(id,**kwargs):return ResearchResponse(id,'completed',SimpleNamespace(private='never log'))
    provider.retrieve=corrupt
    result=run(worker.tick());assert result['status']=='failed' and result['error_code']=='RESEARCH_SOURCES_UNCONFIRMED'
    assert run(research.latest(p['user_id'],p['id'])) is None
    assert run(plans.claim_next(uid())) is None


class FakeGeneration:
    def __init__(self):self.creates=[]
    async def create(self,system,user,schema):
        self.creates.append((system,user,schema))
        return SimpleNamespace(response_id='resp_generation_one',status='queued')


def test_generation_gets_bound_cited_context_only_as_untrusted_user_data(setup,payload):
    from app.adaptive_worker import AdaptivePlanningWorker
    from app.adaptive_research_worker import GroundedPlanningWorker
    _,clock,g,plans,research=setup;p=triggered(plans,research,payload)
    researcher=AdaptiveResearchWorker(research,plans,FakeResearch(lambda:clock[0]),enabled=True,clock=lambda:clock[0])
    run(researcher.tick());run(researcher.tick())
    generator=FakeGeneration();sections=AdaptivePlanningWorker(plans,generator,enabled=True,clock=lambda:clock[0])
    combined=GroundedPlanningWorker(sections,researcher)
    result=run(sections.tick());assert result['status']=='running' and len(generator.creates)==1
    system,user,schema=generator.creates[0]
    assert 'https://example.org/official' in user and 'untrusted source/model text' in user
    assert 'https://example.org/official' not in system
    assert 'applicability' in user and 'unknown' in user
    assert run(plans.get_plan(p['user_id'],p['id']))['remaining_creates']==9


def test_expired_context_pauses_before_generation_submission(setup,payload):
    from dataclasses import replace
    from app.adaptive_worker import AdaptivePlanningWorker
    _,clock,g,plans,research=setup;p=triggered(plans,research,payload)
    provider=FakeResearch(lambda:clock[0]);original=provider.retrieve
    async def short_lived(id,**kwargs):
        result=await original(id,**kwargs)
        return replace(result,result=replace(result.result,expires_at=(clock[0]+timedelta(seconds=1)).isoformat()))
    provider.retrieve=short_lived
    researcher=AdaptiveResearchWorker(research,plans,provider,enabled=True,clock=lambda:clock[0])
    run(researcher.tick());run(researcher.tick());clock[0]+=timedelta(seconds=2)
    generator=FakeGeneration();worker=AdaptivePlanningWorker(plans,generator,enabled=True,clock=lambda:clock[0],research_context=researcher.context_for_section)
    result=run(worker.tick());assert result['status']=='failed' and result['error_code']=='SECTION_RESEARCH_UNAVAILABLE'
    assert generator.creates==[] and run(plans.get_plan(p['user_id'],p['id']))['remaining_creates']==10


def test_existing_legacy_plan_needs_no_source_context(setup,payload):
    from app.adaptive_worker import AdaptivePlanningWorker
    _,clock,g,plans,research=setup;g.research_enabled=False
    p=run(plans.create_plan(uid(),uid(),payload));generator=FakeGeneration()
    worker=AdaptivePlanningWorker(plans,generator,enabled=True,clock=lambda:clock[0])
    result=run(worker.tick());assert result['status']=='running'
    assert len(generator.creates)==1 and 'PUBLIC RESEARCH DATA' not in generator.creates[0][1]


def test_required_research_missing_section_binding_fails_before_paid_create(setup,payload):
    import json,sqlite3
    from app.adaptive_worker import AdaptivePlanningWorker
    path,clock,g,plans,research=setup;p=triggered(plans,research,payload)
    researcher=AdaptiveResearchWorker(research,plans,FakeResearch(lambda:clock[0]),enabled=True,clock=lambda:clock[0])
    run(researcher.tick());run(researcher.tick())
    section=next(row for row in run(plans.list_sections(p['user_id'],p['id'])) if row['status']=='queued')
    with sqlite3.connect(path) as connection:
        section.pop('research_source_id');connection.execute('UPDATE sections SET data=? WHERE id=?',(json.dumps(section),section['id']))
    generator=FakeGeneration();worker=AdaptivePlanningWorker(plans,generator,enabled=True,clock=lambda:clock[0],research_context=researcher.context_for_section)
    result=run(worker.tick());assert result['status']=='failed' and result['error_code']=='SECTION_RESEARCH_UNAVAILABLE'
    assert generator.creates==[]
