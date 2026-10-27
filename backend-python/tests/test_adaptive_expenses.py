import asyncio
from copy import deepcopy
from datetime import date,timedelta
from uuid import uuid4
import pytest
from app.adaptive_expenses import accepted_expenses,CATEGORIES
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.section_repository import SectionCheckpointRepository
from app.adaptive_coordinator import AdaptiveCoordinator
from app.adaptive_worker import AdaptivePlanningWorker
from app.planning_repository import JobRepositoryError
from test_adaptive_integration import FakeProvider,OWNER


def run(coro):return asyncio.run(coro)

@pytest.fixture
def completed(tmp_path,payload):
    async def build():
        g=AdaptiveSQLiteGateway(tmp_path/'queue',enabled=True,initialize=True)
        await g.purge_expired();r=SectionCheckpointRepository(g,enabled=True)
        prefs={**payload,'startDate':'2028-01-01','endDate':'2028-01-12','budget':100000}
        provider=FakeProvider(r,prefs);worker=AdaptivePlanningWorker(r,provider,enabled=True)
        engine=AdaptiveCoordinator(r,worker,enabled=True,require_health=False)
        pid=(await engine.start(OWNER,str(uuid4()),prefs))['plan']['id']
        for _ in range(8):await worker.tick()
        plan=await r.get_plan(OWNER,pid);assert plan['completed_days']==12
        rows=await r.list_sections(OWNER,pid,limit=3)
        rows+=await r.list_sections(OWNER,pid,after_sequence=rows[-1]['sequence'],limit=3)
        return g,r,provider,plan,rows
    data=run(build());yield data;run(data[0].close())

class Repo:
    def __init__(self,plan,rows):self.plan=deepcopy(plan);self.rows=deepcopy(rows);self.calls=[]
    async def get_plan(self,owner,pid):return deepcopy(self.plan)
    async def list_sections(self,owner,pid,*,after_sequence,limit):
        self.calls.append((owner,pid,after_sequence,limit))
        return deepcopy([r for r in self.rows if r['sequence']>after_sequence][:limit])

def test_actual_whole_retained_plan_not_first_page(completed):
    _,r,provider,p,rows=completed
    result=run(accepted_expenses(r,OWNER,p['id']))
    expected={k:sum(round(d['costs'][k]*100) for row in rows for d in row['checkpoint']['itinerary']['days']) for k in CATEGORIES}
    assert result['categories']==expected and sum(expected.values())==result['totalSpentCents']==p['spent_cents']
    assert result['acceptedDays']==12 and result['isComplete'] and result['scope']=='whole_group'
    assert result['travelers']==p['preferences']['travelers'] and provider.calls==4
    assert result['suggestedBufferCents']==(p['spent_cents']+9)//10
    assert run(r.get_plan(OWNER,p['id']))==p
    with pytest.raises(JobRepositoryError):run(accepted_expenses(r,str(uuid4()),p['id']))

def test_frozen_partial_frontier_ignores_later_rows(completed):
    _,_,_,p,rows=completed
    p={**p,'status':'active','completed_days':9,'spent_cents':sum(row['checkpoint']['spentCents'] for row in rows[:3])}
    repo=Repo(p,rows);result=run(accepted_expenses(repo,OWNER,p['id']))
    assert result['acceptedDays']==9 and not result['isComplete'] and len(repo.calls)==1
    assert all(call[3]==3 for call in repo.calls)

def test_failed_attempts_are_not_counted_and_cursor_advances(completed):
    _,_,_,p,rows=completed
    failed={**deepcopy(rows[0]),'id':str(uuid4()),'status':'failed','checkpoint':None,'sequence':1}
    for row in rows:row['sequence']+=1
    repo=Repo(p,[failed,*rows]);result=run(accepted_expenses(repo,OWNER,p['id']))
    assert result['totalSpentCents']==p['spent_cents'] and len(repo.calls)==2 and repo.calls[1][2]==3

@pytest.mark.parametrize('kind',['missing','duplicate_date','wrong_owner','wrong_currency','checkpoint_total','plan_total','extra_cost','fraction','bool','huge_dates'])
def test_invalid_accounting_never_partial_success(completed,kind):
    _,_,_,p,rows=completed;p=deepcopy(p);rows=deepcopy(rows)
    day=rows[0]['checkpoint']['itinerary']['days'][0]
    if kind=='missing':rows.pop()
    elif kind=='duplicate_date':rows[1]['checkpoint']['itinerary']['days'][0]['date']=day['date']
    elif kind=='wrong_owner':rows[0]['user_id']=str(uuid4())
    elif kind=='wrong_currency':rows[0]['checkpoint']['itinerary']['currency']='USD' if p['preferences']['currency']!='USD' else 'INR'
    elif kind=='checkpoint_total':rows[0]['checkpoint']['spentCents']+=1
    elif kind=='plan_total':p['spent_cents']+=1
    elif kind=='extra_cost':day['costs']['invented']=1
    elif kind=='fraction':day['costs']['meals']=0.001
    elif kind=='bool':p['completed_days']=True
    elif kind=='huge_dates':rows[0]['end_date']='9999-12-31'
    with pytest.raises(JobRepositoryError):run(accepted_expenses(Repo(p,rows),OWNER,p['id']))

def test_zero_accepted_and_separate_buffer_gap(completed):
    _,_,_,p,rows=completed
    zero={**p,'status':'active','completed_days':0,'spent_cents':0}
    repo=Repo(zero,rows);result=run(accepted_expenses(repo,OWNER,p['id']))
    assert result['totalSpentCents']==result['suggestedBufferCents']==result['budgetGapCents']==0 and not repo.calls
    exact={**p,'total_budget_cents':p['spent_cents'],'preferences':{**p['preferences'],'budget':p['spent_cents']/100}}
    result=run(accepted_expenses(Repo(exact,rows),OWNER,p['id']))
    assert result['remainingBudgetCents']==0 and result['budgetGapCents']==result['suggestedBufferCents']>0
    assert result['totalSpentCents']==p['spent_cents']

def test_page_and_scan_bounds(completed,monkeypatch):
    _,_,_,p,rows=completed
    monkeypatch.setattr('app.adaptive_expenses.MAX_PAGES',1)
    with pytest.raises(JobRepositoryError):run(accepted_expenses(Repo(p,rows),OWNER,p['id']))
