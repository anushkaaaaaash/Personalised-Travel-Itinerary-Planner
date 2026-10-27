"""Explicit commentary stays out of draft validation and never recreates work."""
import json
from datetime import datetime,timezone
import pytest
from app.openai_output_stream import OutputStreamError
from app.research_sqlite import ResearchSQLiteGateway
from app.section_repository import SectionCheckpointRepository
from app.section_preview_store import SectionPreviewStore
from app.adaptive_worker import AdaptivePlanningWorker
from app.adaptive_planning import SectionSpec
from test_section_preview_store import setup,run,row
from test_adaptive_stream_worker import Client,event,worker
from test_adaptive_planning import section_wire
from test_itineraries import generated


def test_commentary_latch_survives_restart_inprogress_pollerror_then_final_validation(setup,payload,generated):
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    client=Client([event(0),OutputStreamError('STREAM_FINAL_ONLY',response_id='resp_private')])
    result=run(worker(r,g,client,clock).tick())
    assert result['status']=='running' and result['error_code']=='SECTION_STREAM_FINAL_ONLY'
    assert result['checkpoint'] is None and client.creates==0 and len(client.resumes)==1
    fresh=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);repo=SectionCheckpointRepository(fresh,enabled=True)
    w=AdaptivePlanningWorker(repo,client,enabled=True,preview_store=SectionPreviewStore(fresh,enabled=True),clock=lambda:datetime.fromtimestamp(clock[0],timezone.utc))
    for _ in range(2):
        running=run(w.tick())
        assert running['error_code']=='SECTION_STREAM_FINAL_ONLY' and not w.immediate_followup
    retrieve=client.retrieve
    async def unavailable(*args):raise TimeoutError('PRIVATE_TEXT')
    client.retrieve=unavailable
    assert run(w.tick())['error_code']=='SECTION_STREAM_FINAL_ONLY'
    assert len(client.resumes)==1 and client.cancelled==0 and client.creates==0
    client.retrieve=retrieve;client.status='completed';client.output=json.dumps(section_wire(payload,generated,SectionSpec.from_manifest(payload)))
    accepted=run(w.tick())
    assert accepted['status']=='succeeded' and accepted['checkpoint'] and accepted['error_code'] is None
    assert len(client.resumes)==1 and client.creates==0 and client.cancelled==0


def test_final_only_still_rejects_invalid_authoritative_result(setup):
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running',error_code='SECTION_STREAM_FINAL_ONLY'))
    client=Client([],status='completed',output='{}')
    result=run(worker(r,g,client,clock).tick())
    assert result['status']=='failed' and result['checkpoint'] is None
    assert client.resumes==[] and client.creates==0


def test_latched_section_hides_existing_provisional_days(setup,payload,generated):
    from app.grounded_coordinator import GroundedCoordinator
    from app.research_repository import ResearchCheckpointRepository
    path,clock,g,r,store,p,s=setup
    output=section_wire(payload,generated,SectionSpec.from_manifest(payload))
    text='{"proposal":{"days":['+json.dumps(output['proposal']['days'][0])
    state=run(store.append(p['user_id'],p['id'],s['id'],s['lease_token'],s['version'],response_id='resp_private',expected_cursor=-1,cursor=0,text_delta=text))
    w=worker(r,g,Client([]),clock)
    engine=GroundedCoordinator(r,w,research_repository=ResearchCheckpointRepository(g,enabled=True),enabled=True,require_health=False)
    assert len(run(engine.context(p['user_id'],p['id']))['draft']['days'])==1
    run(r.transition(p['user_id'],s['id'],s['lease_token'],state.version,'running',error_code='SECTION_STREAM_FINAL_ONLY'))
    public=run(engine.context(p['user_id'],p['id']))
    assert public['draft'] is None and public['plan']['completedDays']==0
    assert 'stream_output_text' not in json.dumps(public)


def test_commentary_during_initial_create_preserves_single_paid_identity(tmp_path,payload):
    from app.adaptive_sqlite import AdaptiveSQLiteGateway
    from app.research_sqlite import upgrade_research_schema
    from uuid import uuid4
    path=tmp_path/'q.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(str(uuid4()),str(uuid4()),payload))
    client=Client([event(0),OutputStreamError('STREAM_FINAL_ONLY',response_id='resp_private')]);w=worker(r,g,client,clock)
    first=run(w.tick())
    assert first['error_code']=='SECTION_STREAM_FINAL_ONLY' and first['status']=='running' and client.creates==1
    second=run(w.tick())
    assert second['error_code']=='SECTION_STREAM_FINAL_ONLY' and client.creates==1 and client.resumes==[]
    assert run(r.get_plan(p['user_id'],p['id']))['remaining_creates']==11
