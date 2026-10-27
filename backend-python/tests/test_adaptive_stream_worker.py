import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace
import json
import pytest
from app.adaptive_worker import AdaptivePlanningWorker
from app.openai_output_stream import OutputStreamUpdate,OutputStreamError
from app.section_preview_store import SectionPreviewStore
from app.section_repository import SectionCheckpointRepository
from app.research_sqlite import ResearchSQLiteGateway,upgrade_research_schema
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.adaptive_planning import SectionSpec
from test_section_preview_store import run,uid,setup,row
from test_adaptive_planning import section_wire
from test_itineraries import generated


class Client:
    def __init__(self,events,*,status='in_progress',output=None):
        self.events=events;self.status=status;self.output=output
        self.creates=0;self.resumes=[];self.closed=0;self.cancelled=0;self.gets=0
    async def retrieve(self,id):
        self.gets+=1
        return SimpleNamespace(response_id=id,status=self.status,output_text=self.output,refused=False)
    async def cancel(self,id): self.cancelled+=1
    async def _stream(self):
        try:
            for event in self.events:
                if isinstance(event,Exception):raise event
                yield event
        finally:self.closed+=1
    def create_stream(self,*args):self.creates+=1;return self._stream()
    def resume_stream(self,id,**kw):self.resumes.append((id,kw));return self._stream()


def worker(r,g,client,clock):
    return AdaptivePlanningWorker(r,client,enabled=True,preview_store=SectionPreviewStore(g,enabled=True),
        clock=lambda:datetime.fromtimestamp(clock[0],timezone.utc))
def event(seq,text=None,kind=None):
    return OutputStreamUpdate('resp_private',seq,kind or ('text_delta' if text is not None else 'created'),text)


def test_create_persists_id_then_draft_before_acceptance(tmp_path,payload,generated):
    path=tmp_path/'q.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload));wire=section_wire(payload,generated,SectionSpec.from_manifest(payload))
    text='{"proposal":{"days":['+json.dumps(wire['proposal']['days'][0])
    client=Client([event(0),event(1,text),OutputStreamError('STREAM_INTERRUPTED',response_id='resp_private')])
    result=run(worker(r,g,client,clock).tick())
    assert result['status']=='running' and result['provider_response_id']=='resp_private'
    assert result['stream_cursor']==1 and result['stream_output_text']==text
    assert len(result['stream_preview']['days'])==1 and not result['stream_preview']['accepted']
    assert result['lease_token'] is None and client.creates==1 and client.closed==1
    assert run(r.get_plan(p['user_id'],p['id']))['completed_days']==0
    client.events=[event(2,']}}'),event(3,kind='terminal')]
    run(worker(r,g,client,clock).tick())
    assert client.creates==1 and client.resumes[0][1]=={'starting_after':1,'prior_text_bytes':len(text.encode())}


def test_running_always_retrieves_first_and_accepts_only_full_contract(setup,payload,generated):
    path,clock,g,r,store,p,s=setup
    # Release existing fixture lease; a worker restart then claims it.
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    wire=section_wire(payload,generated,SectionSpec.from_manifest(payload))
    client=Client([],status='completed',output=json.dumps(wire))
    done=run(worker(r,g,client,clock).tick())
    assert done['status']=='succeeded' and done['checkpoint']
    assert client.gets==1 and client.resumes==[] and client.creates==0
    assert 'stream_preview' not in done


@pytest.mark.parametrize('fault',['invalid','quota','interrupted','preid','knownid'])
def test_stream_faults_never_recreate_or_accept(tmp_path,payload,fault):
    path=tmp_path/'q.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload))
    events=[event(0),event(1,'{')]
    if fault=='invalid':events.append(OutputStreamError('STREAM_INVALID_RESPONSE',response_id='resp_private'))
    if fault=='quota':events.append(event(2,' '*131073))
    if fault=='interrupted':events.append(OutputStreamError('STREAM_INTERRUPTED',response_id='resp_private'))
    if fault=='preid':events=[OutputStreamError('STREAM_INTERRUPTED',creating=True)]
    if fault=='knownid':events=[OutputStreamError('STREAM_INTERRUPTED',response_id='resp_private',creating=True)]
    client=Client(events)
    result=run(worker(r,g,client,clock).tick())
    expected='failed' if fault in {'invalid','quota'} else 'submission_unknown' if fault=='preid' else 'running'
    assert result['status']==expected and result['checkpoint'] is None
    assert client.creates==1 and client.cancelled==0
    assert run(r.get_plan(p['user_id'],p['id']))['completed_days']==0
    if expected=='failed':assert 'stream_output_text' not in result


def test_storage_quota_stops_connection_preserves_known_id_and_cursor(setup,monkeypatch):
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    monkeypatch.setattr('app.section_preview_store.GLOBAL_STORAGE_BYTES',1)
    client=Client([event(0),event(1,'{'),OutputStreamError('STREAM_INTERRUPTED',response_id='resp_private')])
    result=run(worker(r,g,client,clock).tick())
    assert result['status']=='running' and result['error_code']=='SECTION_RESOURCE_LIMIT'
    assert result.get('stream_cursor',-1)==-1 and result['provider_response_id']=='resp_private'
    assert client.closed==1 and client.creates==0 and client.cancelled==0


def test_append_conflict_does_not_cancel_or_transition_after_lease_loss(setup):
    from app.planning_repository import JobRepositoryError
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    client=Client([event(0),event(1,'{'+' '*4096)])
    w=worker(r,g,client,clock)
    real_append=w.preview_store.append
    async def lost(*args,**kwargs):
        current=await r.get_section(p['user_id'],s['id'])
        await r.transition(p['user_id'],s['id'],current['lease_token'],current['version'],'running')
        return await real_append(*args,**kwargs)
    w.preview_store.append=lost
    with pytest.raises(JobRepositoryError,match='SECTION_PREVIEW_CONFLICT'):run(w.tick())
    saved=row(r,p,s)
    assert saved['status']=='running' and saved['lease_token'] is None and saved.get('stream_cursor',-1)==-1
    assert client.closed==1 and client.cancelled==0 and client.creates==0


def test_sparse_stream_flushes_while_network_waits_not_each_token(setup):
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    class Sparse(Client):
        async def _stream(self):
            try:
                yield event(0)
                for seq in range(1,20):yield event(seq,' ')
                await asyncio.sleep(0.6)
                saved=await r.get_section(p['user_id'],s['id'])
                assert saved['stream_cursor']==19 and saved['stream_output_text']==' '*19
                assert saved['version']<s['version']+10
                yield event(20,kind='terminal')
            finally:self.closed+=1
    client=Sparse([])
    result=run(worker(r,g,client,clock).tick())
    assert result['stream_cursor']==20 and result['status']=='running' and client.closed==1


def test_bounded_idle_tick_closes_pending_network_without_cancelling_job(setup):
    from time import monotonic
    path,clock,g,r,store,p,s=setup
    class Idle(Client):
        async def _stream(self):
            try:
                await asyncio.sleep(100)
                yield event(0)
            finally:self.closed+=1
    client=Idle([]);w=worker(r,g,client,clock)
    async def exercise():
        state=await store.load(p['user_id'],p['id'],s['id'],s['lease_token'],s['version'])
        return await asyncio.wait_for(w._consume_stream(s,client._stream(),state,stop=monotonic()+0.02),1)
    result=run(exercise())
    assert result['status']=='running' and client.closed==1 and client.cancelled==0
    assert result.get('stream_cursor',-1)==-1


def test_slow_retrieve_shortens_stream_to_fresh_lease_window(setup):
    from time import monotonic
    path,clock,g,r,store,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    class Slow(Client):
        async def retrieve(self,id):
            clock[0]+=31
            return await super().retrieve(id)
    client=Slow([]);w=worker(r,g,client,clock)
    real_consume=w._consume_stream
    async def bounded(section,stream,state,**kw):
        remaining=kw['stop']-monotonic()
        assert 23<=remaining<=24
        # Quiet network cannot be allowed27s after that31s retrieve. Model
        # hitting its24s stop, leaving5s for release CAS rather than stalelease.
        clock[0]+=24
        return await real_consume(section,stream,state,stop=monotonic()-1)
    w._consume_stream=bounded
    result=run(w.tick())
    assert result['status']=='running' and result['lease_token'] is None
    assert client.cancelled==0 and client.creates==0


def test_early_id_reclaim_loss_closes_without_second_create(tmp_path,payload):
    from app.planning_repository import JobRepositoryError
    path=tmp_path/'q.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True);upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]);r=SectionCheckpointRepository(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload));client=Client([event(0),event(1,'{')])
    async def lost(*args):raise JobRepositoryError('SECTION_NOT_FOUND_OR_CONFLICT',409)
    r.claim=lost
    with pytest.raises(JobRepositoryError):run(worker(r,g,client,clock).tick())
    plan=run(r.get_plan(p['user_id'],p['id']))
    saved=run(r.get_section(p['user_id'],plan['active_section']))
    assert saved['status']=='running' and saved['provider_response_id']=='resp_private'
    assert saved.get('stream_cursor',-1)==-1 and client.creates==1 and client.closed==1 and client.cancelled==0
