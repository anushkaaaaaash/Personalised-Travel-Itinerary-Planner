from datetime import datetime,timezone
import json
from types import SimpleNamespace
import pytest
from app.revision_worker import RevisionWorker
from app.revision_repository import RevisionRepository
from app.revision_sqlite import RevisionSQLiteGateway
from app.planning_repository import JobRepositoryError
from test_revision_sqlite import store,reserve,run,uid
from test_adaptive_revision import wire
from test_itineraries import generated

class Client:
    def __init__(self,output=None):self.output=output;self.creates=0;self.gets=[];self.cancels=[];self.create_error=None;self.retrieve_error=None
    async def create(self,system,user,schema):
        self.creates+=1;self.prompt=(system,user,schema)
        if self.create_error:raise self.create_error
        return SimpleNamespace(response_id='resp_edit',status='queued')
    async def retrieve(self,id):
        self.gets.append(id)
        if self.retrieve_error:raise self.retrieve_error
        return SimpleNamespace(response_id=id,status='completed' if self.output else 'in_progress',output_text=self.output,refused=False)
    async def cancel(self,id):self.cancels.append(id)

def worker(rr,client,clock):return RevisionWorker(rr,client,enabled=True,clock=lambda:datetime.fromtimestamp(clock[0],timezone.utc))

def test_worker_create_then_restart_retrieves_same_id_candidate_only(store,generated):
    path,clock,g,r,rr,p=store;j=reserve(store);ctx=run(rr.context(p['user_id'],j['id']))
    client=Client(json.dumps(wire(ctx,generated)))
    first=run(worker(rr,client,clock).tick());assert first['status']=='running' and client.creates==1
    fresh=RevisionRepository(RevisionSQLiteGateway(path,enabled=True,clock=lambda:clock[0]),enabled=True)
    result=run(worker(fresh,client,clock).tick())
    assert result['status']=='candidate' and result['candidate']['accepted'] is False
    assert client.creates==1 and client.gets==['resp_edit'] and not client.cancels
    assert j['instruction'] in client.prompt[1] and j['instruction'] not in client.prompt[0]
    assert run(r.get_plan(p['user_id'],p['id']))==p


def test_uncertain_create_never_replays(store):
    path,clock,g,r,rr,p=store;j=reserve(store);client=Client();client.create_error=TimeoutError('PRIVATE ERROR')
    result=run(worker(rr,client,clock).tick());assert result['status']=='submission_unknown'
    assert run(worker(rr,client,clock).tick()) is None and client.creates==1
    with pytest.raises(JobRepositoryError):run(rr.retry(p['user_id'],j['id'],uid()))
    assert 'PRIVATE ERROR' not in json.dumps(result)


def test_poll_uncertain_keeps_known_id_and_never_creates_again(store):
    path,clock,g,r,rr,p=store;reserve(store);client=Client()
    run(worker(rr,client,clock).tick());client.retrieve_error=TimeoutError('private')
    result=run(worker(rr,client,clock).tick())
    assert result['status']=='running' and result['provider_response_id']=='resp_edit'
    assert client.creates==1 and client.gets==['resp_edit']


def test_deadline_fails_before_best_effort_cancel(store):
    path,clock,g,r,rr,p=store;reserve(store);client=Client()
    run(worker(rr,client,clock).tick());clock[0]+=481
    result=run(worker(rr,client,clock).tick())
    assert result['status']=='failed' and result['error_code']=='REVISION_DEADLINE_REACHED'
    assert client.cancels==['resp_edit'] and client.creates==1


def test_invalid_candidate_fails_without_changing_base(store):
    path,clock,g,r,rr,p=store;reserve(store);client=Client('{}')
    run(worker(rr,client,clock).tick());result=run(worker(rr,client,clock).tick())
    assert result['status']=='failed' and result['candidate'] is None
    assert run(r.get_plan(p['user_id'],p['id']))==p


def test_context_storage_uncertainty_is_not_misreported_known_failure(store):
    path,clock,g,r,rr,p=store;j=reserve(store);client=Client()
    run(worker(rr,client,clock).tick())
    async def unavailable(*args):raise JobRepositoryError('REVISION_STORAGE_UNCONFIRMED',503)
    rr.context=unavailable
    with pytest.raises(JobRepositoryError):run(worker(rr,client,clock).tick())
    saved=run(rr.get(p['user_id'],j['id']))
    assert saved['status']=='running' and saved['provider_response_id']=='resp_edit'
    assert client.creates==1 and client.gets==[] and not client.cancels
