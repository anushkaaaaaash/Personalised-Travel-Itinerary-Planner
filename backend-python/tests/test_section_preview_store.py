import asyncio
import json
import sqlite3
from uuid import uuid4
import pytest
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.research_sqlite import ResearchSQLiteGateway,upgrade_research_schema
from app.section_repository import SectionCheckpointRepository
from app.section_preview_store import SectionPreviewStore
from app.planning_repository import JobRepositoryError
from test_adaptive_planning import spec_for,section_wire
from test_itineraries import generated


def uid(): return str(uuid4())
def run(c): return asyncio.run(c)

@pytest.fixture
def setup(tmp_path,payload):
    path=tmp_path/'queue.sqlite';clock=[1800000000.0]
    AdaptiveSQLiteGateway(path,enabled=True,initialize=True)
    upgrade_research_schema(path,approved=True)
    g=ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0])
    r=SectionCheckpointRepository(g,enabled=True);store=SectionPreviewStore(g,enabled=True)
    p=run(r.create_plan(uid(),uid(),payload));s=run(r.next_section(p['user_id'],p['id'],uid()))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'submitting'))
    s=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running',provider_response_id='resp_private'))
    s=run(r.claim(p['user_id'],s['id'],uid()))
    return path,clock,g,r,store,p,s


def args(p,s): return p['user_id'],p['id'],s['id'],s['lease_token'],s['version']
def append(store,p,s,text='',cursor=1,expected=-1):
    return run(store.append(*args(p,s),response_id='resp_private',expected_cursor=expected,cursor=cursor,text_delta=text))
def row(r,p,s): return run(r.get_section(p['user_id'],s['id']))
def change(path,table,id,**values):
    with sqlite3.connect(path) as c:
        data=json.loads(c.execute('SELECT data FROM '+table+' WHERE id=?',(id,)).fetchone()[0]);data.update(values)
        c.execute('UPDATE '+table+' SET data=? WHERE id=?',(json.dumps(data),id))


def test_restart_atomic_cursor_private_buffer_and_draft(setup,payload,generated):
    path,clock,g,r,store,p,s=setup
    initial=run(store.load(*args(p,s)));assert initial.cursor==-1
    wire=section_wire(payload,generated,spec_for(payload))
    text='{"proposal":{"days":['+json.dumps(wire['proposal']['days'][0])
    state=append(store,p,s,text)
    assert state.cursor==1 and state.version==s['version']+1 and len(state.preview['days'])==1
    assert state.preview['accepted'] is False and state.preview['status']=='draft'
    assert text not in repr(state) and 'resp_private' not in repr(state) and s['lease_token'] not in repr(state)
    p2=run(r.get_plan(p['user_id'],p['id']))
    assert p2['spent_cents']==p['spent_cents'] and p2['completed_days']==p['completed_days']
    fresh=SectionPreviewStore(ResearchSQLiteGateway(path,enabled=True,clock=lambda:clock[0]),enabled=True)
    restored=run(fresh.load(*args(p,row(r,p,s))))
    assert restored==state
    assert row(r,p,s)['reserved_preview_bytes']>len(text.encode())


@pytest.mark.parametrize('kind',['owner','plan','lease','version','expired_lease','expired_plan','provider','cursor','bool_cursor','bool_version','backward','duplicate','accepted'])
def test_stale_or_invalid_never_overwrites(setup,kind):
    path,clock,g,r,store,p,s=setup
    append(store,p,s,'{');s=row(r,p,s);before=dict(s)
    call=dict(response_id='resp_private',expected_cursor=1,cursor=2,text_delta=' ')
    ids=list(args(p,s))
    if kind=='owner':ids[0]=uid()
    if kind=='plan':ids[1]=uid()
    if kind=='lease':ids[3]=uid()
    if kind=='version':ids[4]-=1
    if kind=='expired_lease':clock[0]+=61
    if kind=='expired_plan':change(path,'plans',p['id'],expires_at='2000-01-01T00:00:00Z')
    if kind=='provider':call['response_id']='resp_other'
    if kind=='cursor':call['expected_cursor']=0
    if kind=='bool_cursor':call['cursor']=True
    if kind=='bool_version':ids[4]=True
    if kind=='backward':call['cursor']=0
    if kind=='duplicate':call['cursor']=1
    if kind=='accepted':change(path,'sections',s['id'],status='succeeded',checkpoint={})
    with pytest.raises(JobRepositoryError):run(store.append(*ids,**call))
    with sqlite3.connect(path) as c:
        after=json.loads(c.execute('SELECT data FROM sections WHERE id=?',(s['id'],)).fetchone()[0])
    for key in ('stream_cursor','stream_output_text','stream_preview','version'): assert after[key]==before[key]


@pytest.mark.parametrize('kind',['failed','cancel','purge'])
def test_terminal_cleanup_releases_all_preview_state(setup,kind):
    path,clock,g,r,store,p,s=setup
    append(store,p,s,'{');s=row(r,p,s)
    with g._connect() as c: allocated=g._allocated(c)
    if kind=='failed':run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'failed',error_code='SECTION_PROVIDER_FAILED'))
    if kind=='cancel':run(r.cancel_plan(p['user_id'],p['id']))
    if kind=='purge':clock[0]+=86401;run(g.purge_expired())
    with g._connect() as c:
        assert g._allocated(c)<allocated
        rows=c.execute('SELECT data FROM sections WHERE id=?',(s['id'],)).fetchall()
    if kind=='purge': assert rows==[]
    else:
        cleaned=json.loads(rows[0][0]);assert not any(k in cleaned for k in ('stream_output_text','stream_preview','stream_cursor','reserved_preview_bytes'))


@pytest.mark.parametrize('kind',['invalid','oversize','plan_quota','global_quota'])
def test_bad_preview_or_quota_rolls_back(setup,kind,monkeypatch):
    path,clock,g,r,store,p,s=setup
    before=row(r,p,s)
    text='{"proposal":{"days":[{"date":"2000-01-01"}]}}' if kind=='invalid' else ' '*131073 if kind=='oversize' else '{'
    if kind=='plan_quota':change(path,'plans',p['id'],storage_limit_bytes=p['storage_used_bytes'])
    if kind=='global_quota':monkeypatch.setattr('app.section_preview_store.GLOBAL_STORAGE_BYTES',1)
    with pytest.raises(JobRepositoryError):append(store,p,s,text)
    assert row(r,p,s)==before


def test_monotonic_commit_renews_lease_and_empty_delta_keeps_buffer(setup):
    path,clock,g,r,store,p,s=setup
    append(store,p,s,'{');s=row(r,p,s);clock[0]+=30
    state=append(store,p,s,'',cursor=8,expected=1)
    assert state.output_text=='{' and state.cursor==8 and state.lease_until>s['lease_until']
    with pytest.raises(JobRepositoryError):append(store,p,s,'',cursor=8,expected=1)


def test_disabled_and_gateway_failure_are_safe(setup):
    _,_,g,_,_,p,s=setup
    with pytest.raises(JobRepositoryError,match='SECTION_PREVIEW_DISABLED'):SectionPreviewStore(g)
    class Broken:
        supports_section_preview=True;elevated=True
        async def preview_request(self,*args):raise RuntimeError('private payload')
    with pytest.raises(JobRepositoryError,match='SECTION_PREVIEW_STORAGE_UNCONFIRMED') as error:
        run(SectionPreviewStore(Broken(),enabled=True).load(*args(p,s)))
    assert 'private' not in str(error.value)


def test_success_clears_preview_without_changing_checkpoint(setup,payload,generated):
    from app.adaptive_planning import SectionSpec,SectionContract
    path,clock,g,r,store,p,s=setup
    spec=SectionSpec.from_manifest(payload)
    checkpoint=SectionContract(spec).decode(section_wire(payload,generated,spec))
    append(store,p,s,'{');s=row(r,p,s)
    done=run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'succeeded',checkpoint=checkpoint))
    assert done['checkpoint']==checkpoint and done['status']=='succeeded'
    assert not any(key.startswith('stream_') for key in done)
    assert 'reserved_preview_bytes' not in done
    with pytest.raises(JobRepositoryError):append(store,p,done,' ',cursor=2,expected=1)
    assert row(r,p,done)['checkpoint']==checkpoint


def test_duplicate_concurrent_cas_only_one_commit(setup):
    path,clock,g,r,store,p,s=setup
    async def race():
        async def attempt():
            try:
                return await store.append(*args(p,s),response_id='resp_private',expected_cursor=-1,cursor=1,text_delta='{')
            except JobRepositoryError:return None
        return await asyncio.gather(attempt(),attempt())
    assert sum(result is not None for result in run(race()))==1
    saved=row(r,p,s)
    assert saved['stream_output_text']=='{' and saved['stream_cursor']==1 and saved['version']==s['version']+1


def test_128k_total_cap_applies_across_multiple_commits(setup):
    path,clock,g,r,store,p,s=setup
    append(store,p,s,' '*65536);s=row(r,p,s)
    second=append(store,p,s,' '*65536,cursor=2,expected=1)
    assert len(second.output_text.encode())==131072
    s=row(r,p,s)
    with pytest.raises(JobRepositoryError,match='SECTION_RESOURCE_LIMIT'):
        append(store,p,s,' ',cursor=3,expected=2)
    assert row(r,p,s)==s
