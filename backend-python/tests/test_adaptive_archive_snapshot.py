import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from app.adaptive_archive_snapshot import prepare_archive,archive_chunks
from app.supabase_clients import DatabaseError
from test_adaptive_expenses import completed,Repo
from test_adaptive_integration import OWNER,FakeProvider
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.section_repository import SectionCheckpointRepository
from app.adaptive_worker import AdaptivePlanningWorker
from app.adaptive_coordinator import AdaptiveCoordinator


def run(c):return asyncio.run(c)


def test_complete_snapshot_all_pages_readonly(completed):
    _,repo,provider,p,rows=completed
    snapshot=run(prepare_archive(repo,None,OWNER,p['id'],p['version']))
    assert snapshot.manifest['totalDays']==12 and snapshot.manifest['sectionCount']==4
    assert snapshot.manifest['spentCents']==sum(r['checkpoint']['spentCents'] for r in rows)
    assert snapshot.manifest['sourceCount']==0 and provider.calls==4
    assert run(repo.get_plan(OWNER,p['id']))==p
    assert 'preferences' not in repr(snapshot) and OWNER not in repr(snapshot)
    async def collect():return [item async for item in archive_chunks(repo,None,OWNER,p)]
    chunks=run(collect());assert len(chunks)==4
    assert all(c['sourceAssociation']=='none_recorded' and not sources for c,sources in chunks)


def test_resume_reads_confirmed_prefix_only(completed):
    _,_,_,p,rows=completed;repo=Repo(p,rows)
    async def collect():return [item async for item in archive_chunks(repo,None,OWNER,p,
        after_sequence=rows[2]['sequence'],section_offset=3,covered_days=9,
        spent_cents=sum(r['checkpoint']['spentCents'] for r in rows[:3]),last_location=rows[2]['checkpoint']['endLocation'])]
    result=run(collect())
    assert len(result)==1 and result[0][0]['sequence']==4 and result[0][0]['sourceSequence']==4
    assert repo.calls==[(OWNER,p['id'],3,3)]


@pytest.mark.parametrize('kind',['partial','owner','version','expired','missing','duplicate','route','money','continuity','extra'])
def test_invalid_snapshot_rejected(completed,kind):
    _,_,_,p,rows=completed;p=deepcopy(p);rows=deepcopy(rows);version=p['version']
    if kind=='partial':p['status']='paused'
    elif kind=='owner':p['user_id']=str(uuid4())
    elif kind=='version':version+=1
    elif kind=='expired':p['expires_at']='2000-01-01T00:00:00+00:00'
    elif kind=='missing':rows.pop()
    elif kind=='duplicate':rows[1]['checkpoint']['itinerary']['days'][0]['date']=rows[0]['start_date']
    elif kind=='route':rows[1]['checkpoint']['journeyStrategy']['summary']='changed'
    elif kind=='money':p['spent_cents']+=1
    elif kind=='continuity':rows[1]['checkpoint']['startLocation']='Wrong'
    else:rows[0]['checkpoint']['unexpected']='private'
    with pytest.raises(DatabaseError):run(prepare_archive(Repo(p,rows),None,OWNER,p['id'],version))


def test_failed_rows_skipped_without_cost_or_date_duplication(completed):
    _,_,_,p,rows=completed;rows=deepcopy(rows)
    failed={**deepcopy(rows[0]),'id':str(uuid4()),'sequence':1,'status':'failed','checkpoint':None}
    for row in rows:row['sequence']+=1
    result=run(prepare_archive(Repo(p,[failed,*rows]),None,OWNER,p['id'],p['version']))
    assert result.manifest['sectionCount']==4 and result.manifest['spentCents']==p['spent_cents']


def test_missing_linked_research_not_replaced_by_latest(completed):
    _,_,_,p,rows=completed;rows=deepcopy(rows);rows[0]['research_source_id']=str(uuid4())
    with pytest.raises(DatabaseError,match='SOURCES_UNAVAILABLE'):run(prepare_archive(Repo(p,rows),None,OWNER,p['id'],p['version']))


def test_end_of_scan_version_change_rejected(completed):
    _,_,_,p,rows=completed
    class Changed(Repo):
        calls_to_plan=0
        async def get_plan(self,owner,pid):
            self.calls_to_plan+=1
            result=await super().get_plan(owner,pid)
            if self.calls_to_plan>1:result['version']+=1
            return result
    with pytest.raises(DatabaseError,match='VERSION_CONFLICT'):run(prepare_archive(Changed(p,rows),None,OWNER,p['id'],p['version']))
