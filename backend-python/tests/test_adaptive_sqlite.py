"""Real disposable SQLite files and independent processes; never provider/network."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import json
import multiprocessing
import sqlite3
from uuid import uuid4
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.section_repository import SectionCheckpointRepository
from app.planning_repository import JobRepositoryError
from app.adaptive_planning import SectionSpec, SectionContract
from test_adaptive_planning import section_wire
from test_itineraries import generated


def uid():return str(uuid4())
def run(coro):return asyncio.run(coro)
def make(path,**kw):
    g=AdaptiveSQLiteGateway(path,enabled=True,**kw)
    return g,SectionCheckpointRepository(g,enabled=True)
def mutate(path,table,id,**values):
    with sqlite3.connect(path) as c:
        row=json.loads(c.execute('select data from '+table+' where id=?',(id,)).fetchone()[0]);row.update(values)
        c.execute('update '+table+' set data=? where id=?',(json.dumps(row),id))

def process_claim(path,owner,section):
    g,r=make(path)
    try:return run(r.claim(owner,section,uid()))['id']
    except JobRepositoryError:return None

def process_create(path,owner,request,prefs):
    g,r=make(path)
    return run(r.create_plan(owner,request,prefs))['id']

@pytest.fixture
def store(tmp_path):
    path=tmp_path/'queue.sqlite';clock=[1800000000.0]
    g,r=make(path,initialize=True,clock=lambda:clock[0])
    return path,clock,g,r

def test_provision_fail_closed(tmp_path):
    path=tmp_path/'missing.sqlite'
    with pytest.raises(JobRepositoryError):make(path)
    assert not path.exists()
    g,r=make(path,initialize=True)
    with pytest.raises(JobRepositoryError):make(path,initialize=True)
    with g._connect() as c:
        assert c.execute('pragma journal_mode').fetchone()[0]=='wal'
        assert c.execute('pragma synchronous').fetchone()[0]==2
        assert c.execute('pragma foreign_keys').fetchone()[0]==1
        assert c.execute('pragma secure_delete').fetchone()[0]==1
    path.unlink()
    with pytest.raises(JobRepositoryError):run(g.purge_expired())
    assert not path.exists()

def test_owner_idempotency_expiry_and_cleanup(store,payload):
    path,clock,g,r=store;owner=uid();request=uid()
    p=run(r.create_plan(owner,request,payload));assert run(r.create_plan(owner,request,payload))==p
    with pytest.raises(JobRepositoryError):run(r.create_plan(owner,request,{**payload,'budget':payload['budget']+1}))
    with pytest.raises(JobRepositoryError):run(r.get_plan(uid(),p['id']))
    s=run(r.next_section(owner,p['id'],uid()));assert s['sequence']==1
    clock[0]+=86401
    with pytest.raises(JobRepositoryError):run(r.get_plan(owner,p['id']))
    assert run(r.claim_next(uid())) is None
    assert run(g.purge_expired())==1
    run(r.verify_ready())
    with sqlite3.connect(path) as c:
        assert c.execute('select count(*) from sections').fetchone()[0]==0
        assert c.execute('select count(*) from controls').fetchone()[0]==0

def test_no_caller_sql_or_unbounded_pages(store,payload):
    _,_,g,r=store
    for resource,args in [('rpc/adaptive_get_plan;drop table plans',{}),('plans',{}),('rpc/adaptive_claim_next',{'worker':uid(),'sql':'select 1'})]:
        with pytest.raises(JobRepositoryError):run(g.request('POST',resource,payload=args))
    p=run(r.create_plan(uid(),uid(),payload))
    with pytest.raises(JobRepositoryError):run(r.list_sections(p['user_id'],p['id'],limit=4))

def test_restart_quarantines_submitting_and_recovers_running(store,payload):
    path,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload));s=run(r.next_section(owner,p['id'],uid()))
    s=run(r.claim(owner,s['id'],uid()));s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'submitting'))
    clock[0]+=61;g2,r2=make(path,clock=lambda:clock[0]);assert run(r2.claim_next(uid())) is None
    assert run(r2.get_section(owner,s['id']))['status']=='submission_unknown'
    with pytest.raises(JobRepositoryError):run(r2.retry_failed(owner,s['id'],uid()))
    run(r2.cancel_plan(owner,p['id']));clock[0]+=601
    p=run(r2.create_plan(owner,uid(),payload));s=run(r2.next_section(owner,p['id'],uid()));s=run(r2.claim(owner,s['id'],uid()))
    s=run(r2.transition(owner,s['id'],s['lease_token'],s['version'],'submitting'))
    s=run(r2.transition(owner,s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_existing'))
    _,r3=make(path,clock=lambda:clock[0]);recovered=run(r3.claim_next(uid()))
    assert recovered['id']==s['id'] and recovered['provider_response_id']=='resp_existing'
    run(r3.cancel_plan(owner,p['id']))
    with pytest.raises(JobRepositoryError):run(r3.transition(owner,s['id'],recovered['lease_token'],recovered['version'],'running',provider_response_id='resp_existing'))

def test_process_claim_and_create_races(tmp_path,payload):
    path=tmp_path/'race.sqlite';g,r=make(path,initialize=True);owner=uid();request=uid()
    with ProcessPoolExecutor(4,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(process_create,str(path),owner,request,payload) for _ in range(4)]
        ids=[f.result(timeout=30) for f in futures]
        assert len(set(ids))==1
        s=run(r.next_section(owner,ids[0],uid()))
        claims=[pool.submit(process_claim,str(path),owner,s['id']) for _ in range(4)]
        assert sum(f.result(timeout=30) is not None for f in claims)==1
        # Existing live lease consumes one of two global slots; different-owner
        # claims in different processes must admit exactly one more, not three.
        candidates=[]
        for _ in range(3):
            account=uid();plan=run(r.create_plan(account,uid(),payload))
            section=run(r.next_section(account,plan['id'],uid()))
            candidates.append((account,section['id']))
        claims=[pool.submit(process_claim,str(path),account,section) for account,section in candidates]
        assert sum(f.result(timeout=30) is not None for f in claims)==1


def test_global_claim_admission_across_connections(store,payload):
    path,clock,g,r=store;sections=[]
    for _ in range(3):
        owner=uid();p=run(r.create_plan(owner,uid(),payload));sections.append(run(r.next_section(owner,p['id'],uid())))
    async def race():
        async def attempt(s):
            _,repo=make(path,clock=lambda:clock[0])
            try:return await repo.claim(s['user_id'],s['id'],uid())
            except JobRepositoryError:return None
        return await asyncio.gather(*(attempt(s) for s in sections))
    assert sum(s is not None for s in run(race()))==2

def test_checkpoint_integrity_and_24_day_run(store,payload,generated):
    path,clock,g,r=store;owner=uid();prefs={**payload,'budget':100000,'endDate':(date.fromisoformat(payload['startDate'])+timedelta(days=23)).isoformat()}
    p=run(r.create_plan(owner,uid(),prefs));first=None
    for i in range(8):
        s=run(r.claim_next(uid()));assert s
        s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'submitting'))
        s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_'+str(i)))
        s=run(r.claim(owner,s['id'],uid()))
        p=run(r.get_plan(owner,p['id']))
        spec=SectionSpec.from_manifest(prefs,next_date=s['start_date'],spent_cents=p['spent_cents'],previous_boundary=p['previous_boundary'] if i else None,journey_strategy=p['journey_strategy'])
        cp=SectionContract(spec).decode(section_wire(prefs,generated,spec))
        bad=deepcopy(cp);bad['spentCents']+=1
        with pytest.raises(JobRepositoryError):run(r.transition(owner,s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=bad))
        accepted=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=cp))
        if first is None:first=accepted
        with pytest.raises(JobRepositoryError):run(r.transition(owner,s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=cp))
    p=run(r.get_plan(owner,p['id']));assert p['status']=='completed' and p['completed_days']==24 and p['remaining_creates']==4
    assert run(r.get_section(owner,first['id']))==first
    assert len(run(r.recent_checkpoints(owner,p['id'])))==3

def test_storage_probes_charged_once_and_resume_zero(store,payload):
    path,clock,g,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload))
    for reason,remaining in [('STORAGE_LIMIT',2),('RESOURCE_ALLOWANCE_REACHED',0),('STORAGE_LIMIT',0)]:
        mutate(path,'plans',p['id'],status='paused',pause_reason=reason,storage_pause_scope='global' if reason=='STORAGE_LIMIT' else None,remaining_creates=remaining)
        blocker=run(r.create_plan(uid(),uid(),payload))
        current=run(r.get_plan(owner,p['id']))
        mutate(path,'plans',blocker['id'],storage_used_bytes=67108864-current['storage_used_bytes']-100,storage_limit_bytes=67108864)
        request=uid()
        for i in range(10):assert run(r.continue_run(owner,p['id'],request if i==0 else uid()))==current
        with sqlite3.connect(path) as c:before=c.execute('select count(*) from controls').fetchone()[0]
        mutate(path,'plans',blocker['id'],expires_at='2000-01-01T00:00:00+00:00')
        run(g.purge_expired());resumed=run(r.continue_run(owner,p['id'],request))
        assert resumed['remaining_creates']==(remaining or 12)
        assert resumed['storage_used_bytes']==current['storage_used_bytes']+512
        assert run(r.continue_run(owner,p['id'],request))==resumed
        with sqlite3.connect(path) as c:assert c.execute('select count(*) from controls').fetchone()[0]==before+1

def test_busy_cleanup_is_not_healthy(store,payload):
    path,clock,g,r=store;p=run(r.create_plan(uid(),uid(),payload))
    run(g.purge_expired())
    reader=sqlite3.connect(path,isolation_level=None)
    try:
        reader.execute('BEGIN');reader.execute('select data from plans').fetchall()
        clock[0]+=86401
        with pytest.raises(JobRepositoryError):run(g.purge_expired())
        with pytest.raises(JobRepositoryError):run(r.verify_ready())
    finally:reader.close()
    run(g.purge_expired());run(r.verify_ready())

def test_calendar_max_no_overflow(store,payload):
    _,_,_,r=store;owner=uid()
    p=run(r.create_plan(owner,uid(),{**payload,'startDate':'9999-12-31','endDate':'9999-12-31'}))
    s=run(r.next_section(owner,p['id'],uid()))
    assert s['start_date']==s['end_date']=='9999-12-31' and s['final_section']

def test_known_failure_retry_and_unknown_never_replayed(store,payload):
    _,clock,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload))
    s=run(r.claim_next(uid()));s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'failed',error_code='OUTPUT_LIMIT'))
    request=uid();replacement=run(r.retry_failed(owner,s['id'],request,section_days=1))
    assert replacement['retry_of']==s['id'] and replacement['start_date']==s['start_date']
    assert run(r.retry_failed(owner,s['id'],request,section_days=1))==replacement
    with pytest.raises(JobRepositoryError):run(r.retry_failed(owner,s['id'],request,section_days=2))
    replacement=run(r.claim(owner,replacement['id'],uid()))
    proposal={'applicability':'proposed','explanation':'Budget cannot cover transfer.','recommendations':[{'field':'budget','reason':'Insufficient.','suggestion':'Review budget.'}]}
    run(r.transition(owner,replacement['id'],replacement['lease_token'],replacement['version'],'failed',error_code='SECTION_CONSTRAINT_CONFLICT',failure_details=proposal))
    with pytest.raises(JobRepositoryError):run(r.continue_run(owner,p['id'],uid()))
    retried=run(r.retry_failed(owner,replacement['id'],uid()))
    assert retried['retry_of']==replacement['id']
    assert run(r.get_section(owner,replacement['id']))['failure_details']==proposal

def test_http_worker_pipeline_on_sqlite(monkeypatch,payload,store):
    from test_adaptive_integration import test_real_sql_24_day_http_and_restart_pipeline
    run(store[2].purge_expired())
    test_real_sql_24_day_http_and_restart_pipeline(monkeypatch,payload,store[2])


def test_worker_ambiguous_create_on_sqlite(monkeypatch,payload,store):
    from test_adaptive_integration import test_real_sql_ambiguous_create_never_replayed
    run(store[2].purge_expired())
    test_real_sql_ambiguous_create_never_replayed(monkeypatch,payload,store[2])


def test_future_cleanup_heartbeat_is_not_fresh(store):
    _,clock,g,r=store
    run(g.purge_expired());clock[0]-=1
    with pytest.raises(JobRepositoryError):run(r.verify_ready())


def test_explicit_proposed_retry_preserves_six_accepted_days(store,payload):
    from app.adaptive_coordinator import AdaptiveCoordinator
    from app.adaptive_worker import AdaptivePlanningWorker
    from test_adaptive_integration import FakeProvider,OWNER
    path,clock,g,r=store
    prefs={**payload,'startDate':'2028-01-01','endDate':'2028-01-09','budget':5000}
    class Provider(FakeProvider):
        async def create(self,*args):
            result=await super().create(*args)
            if self.calls==3:
                value=json.loads(self.outputs[result.response_id])
                value['proposal'].update(status='infeasible',days=[],explanation='Model proposes reviewing the return day pace.')
                value['recommendations']=[{'field':'travelPace','reason':'Return travel needs time.','suggestion':'Review pace.'}]
                self.outputs[result.response_id]=json.dumps(value)
            return result
    async def scenario():
        await g.purge_expired()
        provider=Provider(r,prefs);worker=AdaptivePlanningWorker(r,provider,enabled=True)
        engine=AdaptiveCoordinator(r,worker,enabled=True)
        plan=(await engine.start(OWNER,uid(),prefs))['plan']['id']
        for _ in range(6):await worker.tick()
        before=await r.get_plan(OWNER,plan);assert before['completed_days']==6 and before['status']=='paused'
        accepted=await r.recent_checkpoints(OWNER,plan);failed=await r.get_section(OWNER,before['active_section'])
        assert failed['error_code']=='SECTION_CONSTRAINT_CONFLICT' and failed['failure_details']['applicability']=='proposed'
        await worker.tick();assert provider.calls==3 # never automatic
        request=uid();await engine.retry(OWNER,plan,failed['id'],request)
        await engine.retry(OWNER,plan,failed['id'],request)
        assert provider.calls==3
        for _ in range(2):await worker.tick()
        complete=await r.get_plan(OWNER,plan)
        assert complete['status']=='completed' and complete['completed_days']==9 and complete['remaining_creates']==8 and provider.calls==4
        assert complete['journey_strategy']==before['journey_strategy']
        for row in accepted:assert await r.get_section(OWNER,row['id'])==row
        await engine.retry(OWNER,plan,failed['id'],request)
        await worker.tick();assert provider.calls==4
    run(scenario())

@pytest.mark.parametrize('code,details',[
 ('SECTION_BUDGET_EXHAUSTED',{'applicability':'proposed','explanation':'Budget.','recommendations':[{'field':'budget','reason':'Cost.','suggestion':'Review.'}]}),
 ('SECTION_CONSTRAINT_CONFLICT',None),
 ('SECTION_CONSTRAINT_CONFLICT',{'applicability':'proposed','explanation':'Constraint.','recommendations':[{'field':'arbitrary','reason':'Reason.','suggestion':'Suggestion.'}]}),
 ('SECTION_CONSTRAINT_CONFLICT',{'applicability':'proposed','explanation':'  ','recommendations':[{'field':'budget','reason':'Reason.','suggestion':'Suggestion.'}]}),
 ('SECTION_CONSTRAINT_CONFLICT',{'applicability':'proposed','explanation':'Constraint.','recommendations':[{'field':'budget','reason':'Reason.','suggestion':'Bad\u0001control'}]}),
 ('SECTION_CONSTRAINT_CONFLICT',{'applicability':'verified','explanation':'Constraint.','recommendations':[]}),
 ('SECTION_CONSTRAINT_CONFLICT',{'applicability':'proposed','explanation':'Constraint.','recommendations':[]}),
])
def test_retry_rejects_unverified_proposal_shape_and_actual_budget(store,payload,code,details):
    path,_,_,r=store;owner=uid();p=run(r.create_plan(owner,uid(),payload))
    s=run(r.claim_next(uid()));s=run(r.transition(owner,s['id'],s['lease_token'],s['version'],'failed',error_code='OUTPUT_LIMIT'))
    mutate(path,'sections',s['id'],error_code=code,failure_details=details)
    with pytest.raises(JobRepositoryError):run(r.retry_failed(owner,s['id'],uid()))
    assert run(r.get_plan(owner,p['id']))['remaining_creates']==12
