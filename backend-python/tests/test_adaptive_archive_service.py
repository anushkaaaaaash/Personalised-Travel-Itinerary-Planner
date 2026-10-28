import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from app.adaptive_archive_service import ArchiveService
from app.adaptive_archive_snapshot import digest
from app.adaptive_archive_views import page
from app.supabase_clients import DatabaseError
from test_adaptive_expenses import completed,Repo
from test_adaptive_integration import OWNER


def run(c):return asyncio.run(c)

class Archive:
    owner_id=OWNER
    def __init__(self):self.row=None;self.chunks=[];self.sources={};self.writes=[];self.fail_append=False
    async def cleanup(self):return {'removed':0}
    async def delete(self,sid,version):
        self.writes.append('delete');self.row=None;self.chunks=[]
        return {'id':sid,'owner':self.owner_id,'deleted':True,'version':version}
    async def lookup(self,rid):return deepcopy(self.row) if self.row and self.row['requestId']==rid else None
    async def begin(self,rid,title,m):
        self.writes.append('begin');now=datetime.now(timezone.utc).isoformat()
        self.row={'id':str(uuid4()),'owner':OWNER,'requestId':rid,'title':title,'status':'staging','version':1,
            'createdAt':now,'updatedAt':now,'stagingExpiresAt':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            'manifest':deepcopy(m),'savedSections':0,'lastSourceSequence':0,'coveredDays':0,'spentCents':0,'endLocation':m['preferences']['departureCity']}
        return deepcopy(self.row)
    async def append_sources(self,sid,sources):
        self.writes.append('sources');self.sources.update({s['hash']:deepcopy(s) for s in sources});return deepcopy(self.row)
    async def append_sections(self,sid,chunks):
        self.writes.append('sections')
        for c in chunks:
            self.chunks.append({**deepcopy(c),'hash':digest(c)})
            self.row.update(savedSections=c['sequence'],lastSourceSequence=c['sourceSequence'],
                coveredDays=self.row['coveredDays']+len(c['checkpoint']['itinerary']['days']),
                spentCents=self.row['spentCents']+c['checkpoint']['spentCents'],endLocation=c['checkpoint']['endLocation'])
        if self.fail_append:raise DatabaseError()
        return deepcopy(self.row)
    async def finalize(self,sid):self.writes.append('finalize');self.row['status']='complete';return deepcopy(self.row)
    async def get(self,sid,after_sequence=0):
        if self.row is None or self.row['id']!=sid:raise DatabaseError(404,'SAVED_ADAPTIVE_NOT_FOUND')
        chunks=self.chunks[after_sequence:after_sequence+3];needed={h for c in chunks for h in c['sourceHashes']}
        return {**deepcopy(self.row),'sections':deepcopy(chunks),'sources':[deepcopy(self.sources[h]) for h in needed],
            'nextCursor':after_sequence+len(chunks) if after_sequence+len(chunks)<len(self.chunks) else None}
    async def list(self,offset=0):return {'items':[deepcopy(self.row)] if self.row['status']=='complete' and offset==0 else [],'hasMore':False,'offset':offset}


def test_bounded_steps_then_reopen_all_days_after_source_gone(completed):
    _,repo,provider,p,_=completed;archive=Archive();svc=ArchiveService(archive,repo);rid=str(uuid4())
    first=run(svc.save(p['id'],rid,p['version'],'My trip'))
    assert first['status']=='staging' and first['savedSections']==3 and first['savedId'] is None
    final=run(svc.save(p['id'],rid,p['version'],'My trip'))
    assert final['status']=='complete' and final['persisted'] and final['stagingExpiresAt'] is None
    assert archive.writes==['begin','sections','sections','finalize'] and provider.calls==4
    detached=ArchiveService(archive)
    one=run(detached.get(final['savedId']));two=run(detached.get(final['savedId'],one['nextCursor']))
    assert len(one['sections'])==3 and len(two['sections'])==1 and two['nextCursor'] is None
    assert sum(len(s['checkpoint']['itinerary']['days']) for s in one['sections']+two['sections'])==12
    assert run(detached.save(p['id'],rid,p['version'],'My trip'))==final
    assert len(run(detached.list())['items'])==1 and provider.calls==4


def test_unknown_append_reconciles_without_new_begin_or_replay(completed):
    _,repo,_,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4());a.fail_append=True
    with pytest.raises(DatabaseError):run(s.save(p['id'],rid,p['version'],'Trip'))
    assert run(s.lookup(rid))['savedSections']==3 and a.writes==['begin','sections']
    a.fail_append=False
    assert run(s.save(p['id'],rid,p['version'],'Trip'))['persisted']
    assert a.writes==['begin','sections','sections','finalize']


def test_request_binding_and_absence_fail_without_writes(completed):
    _,repo,_,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4())
    with pytest.raises(DatabaseError,match='REQUEST_NOT_FOUND'):run(s.lookup(rid))
    run(s.save(p['id'],rid,p['version'],'Trip'));before=list(a.writes)
    for pid,v,t in [(str(uuid4()),p['version'],'Trip'),(p['id'],p['version']+1,'Trip'),(p['id'],p['version'],'Other')]:
        with pytest.raises(DatabaseError,match='REQUEST_CONFLICT'):run(s.save(pid,rid,v,t))
    assert a.writes==before


def test_source_expiry_rechecked_at_finalize(completed):
    _,repo,_,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4())
    run(s.save(p['id'],rid,p['version'],'Trip'))
    now=datetime.now(timezone.utc);calls=0
    def clock():
        nonlocal calls
        calls+=1
        return now if calls<3 else datetime.fromisoformat(p['expires_at'])+timedelta(seconds=1)
    s.clock=clock
    with pytest.raises(DatabaseError,match='SOURCE_EXPIRED'):run(s.save(p['id'],rid,p['version'],'Trip'))
    assert 'finalize' not in a.writes and a.row['status']=='staging'


@pytest.mark.parametrize('kind',['hash','route','date','cost','sources','extra','cursor'])
def test_reopen_revalidates_untrusted_owner_archive(completed,kind):
    _,repo,_,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4())
    run(s.save(p['id'],rid,p['version'],'Trip'));run(s.save(p['id'],rid,p['version'],'Trip'))
    row=run(a.get(a.row['id']));c=row['sections'][0]
    if kind=='hash':c['hash']='0'*64
    elif kind=='route':c['checkpoint']['journeyStrategy']['summary']='changed'
    elif kind=='date':c['startDate']='2028-02-01'
    elif kind=='cost':c['checkpoint']['spentCents']+=1
    elif kind=='sources':c['sourceHashes']=['f'*64]
    elif kind=='extra':c['private']='bad'
    else:row['nextCursor']=99
    if kind!='hash':c['hash']=digest({k:v for k,v in c.items() if k!='hash'})
    with pytest.raises(DatabaseError):page(row,a.row['id'])


def test_twenty_four_day_archive_reopens_all_eight_sections(tmp_path,payload):
    from app.adaptive_sqlite import AdaptiveSQLiteGateway
    from app.section_repository import SectionCheckpointRepository
    from app.adaptive_worker import AdaptivePlanningWorker
    from app.adaptive_coordinator import AdaptiveCoordinator
    from test_adaptive_integration import FakeProvider
    async def scenario():
        gateway=AdaptiveSQLiteGateway(tmp_path/'save24',enabled=True,initialize=True);await gateway.purge_expired()
        repo=SectionCheckpointRepository(gateway,enabled=True)
        prefs={**payload,'startDate':'2028-01-01','endDate':'2028-01-24','budget':100000}
        provider=FakeProvider(repo,prefs);engine=AdaptiveCoordinator(repo,AdaptivePlanningWorker(repo,provider,enabled=True),enabled=True,require_health=False)
        pid=(await engine.start(OWNER,str(uuid4()),prefs))['plan']['id']
        for _ in range(16):await engine.worker.tick()
        plan=await repo.get_plan(OWNER,pid);a=Archive();s=ArchiveService(a,repo);rid=str(uuid4())
        states=[await s.save(pid,rid,plan['version'],'Long trip') for _ in range(3)]
        assert [r['savedSections'] for r in states]==[3,6,8] and states[-1]['persisted']
        await gateway.close()
        detached=ArchiveService(a);cursor=0;days=[]
        while cursor is not None:
            result=await detached.get(a.row['id'],cursor)
            days.extend(d['date'] for section in result['sections'] for d in section['checkpoint']['itinerary']['days'])
            cursor=result['nextCursor']
        assert len(days)==24 and len(set(days))==24 and days[-1]=='2028-01-24' and provider.calls==8
    run(scenario())


def test_explicit_delete_copy_preserves_source_and_version(completed):
    _,repo,provider,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4())
    run(s.save(p['id'],rid,p['version'],'Trip'));saved=run(s.save(p['id'],rid,p['version'],'Trip'))
    with pytest.raises(DatabaseError,match='VERSION_CONFLICT'):run(s.delete(saved['savedId'],2))
    assert a.row is not None
    assert run(s.delete(saved['savedId'],1))=={'id':saved['savedId'],'deleted':True,'version':1}
    assert run(repo.get_plan(OWNER,p['id']))==p and provider.calls==4


def test_cleanup_only_on_confirmed_new_operation_not_lookup_or_resume(completed):
    _,repo,_,p,_=completed;a=Archive();s=ArchiveService(a,repo);rid=str(uuid4());calls=[]
    async def cleanup():calls.append('cleanup');return {'removed':0}
    a.cleanup=cleanup
    run(s.save(p['id'],rid,p['version'],'Trip'));assert calls==['cleanup']
    run(s.lookup(rid));run(s.save(p['id'],rid,p['version'],'Trip'));assert calls==['cleanup']
    async def uncertain():raise DatabaseError()
    a.cleanup=uncertain
    with pytest.raises(DatabaseError):run(s.save(p['id'],str(uuid4()),p['version'],'New'))
    assert a.writes.count('begin')==1
