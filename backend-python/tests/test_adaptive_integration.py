"""Real isolated SQL + repository + worker + HTTP, fake provider only.

PGlite is single-connection; separate PostgreSQL CI must cover concurrency.
"""
import asyncio
from copy import deepcopy
from datetime import date,timedelta
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.auth import AuthUser
from app.main import create_app
from app.adaptive_postgres import AdaptivePostgresGateway
from app.adaptive_worker import AdaptivePlanningWorker
from app.adaptive_coordinator import AdaptiveCoordinator
from app.section_repository import SectionCheckpointRepository
from app.planning_repository import JobRepositoryError

OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'

class Auth:
    def configured(self): return True
    async def verify(self,token): return AuthUser(id=OWNER if token=='owner' else OTHER)

class Bridge:
    elevated=True
    def __init__(self):
        self.process=subprocess.Popen(['node',str(Path(__file__).parent/'sql/adaptive_rpc_bridge.mjs')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ))
        line=self.process.stdout.readline()
        if not line: raise RuntimeError(self.process.stderr.read())
        assert json.loads(line)=={'ready':True}
        self.mapper=object.__new__(AdaptivePostgresGateway)
    async def request(self,method,resource,params=None,payload=None):
        query,values=self.mapper._query(method,resource,params,payload)
        self.process.stdin.write(json.dumps({'query':query,'values':values})+'\n');self.process.stdin.flush()
        result=json.loads(self.process.stdout.readline())
        if 'error' in result: raise AssertionError(result['error'])
        return result['rows']
    def close(self):
        self.process.stdin.close();self.process.wait(timeout=10)
        assert self.process.returncode==0,self.process.stderr.read()

class FakeProvider:
    def __init__(self,repository,prefs): self.repository=repository;self.prefs=prefs;self.outputs={};self.calls=0;self.mode='success'
    async def create(self,system_prompt,user_prompt,schema):
        self.calls+=1
        if self.mode=='ambiguous':
            error=RuntimeError('private fixture transport detail');error.ambiguous_create=True;raise error
        dates=schema['$defs']['GenerationDay']['properties']['date']['enum']
        strategy={'summary':'Synthetic full-trip regional stay, with outward and return travel.',
            'stays':[{'startDate':self.prefs['startDate'],'endDate':self.prefs['endDate'],'location':self.prefs['destination']}]}
        days=[]
        for value in dates:
            def activity(title,sequence,kind='main'):
                return dict(id='a'+str(sequence),title=title+' '+value,durationMinutes=60,notes='Synthetic fixture only.',
                    latitude=None,longitude=None,kind=kind,gapBeforeMinutes=30,sequence=sequence)
            days.append(dict(date=value,morning='Synthetic museum.',afternoon='Synthetic garden.',evening='Rest.',dining='Confirm menus.',
                dietaryNotes='Confirm needs.',mobilityNotes='Confirm access.',transitAndRest='Allow time and rest.',
                interestTags=['culture'],costs=dict(accommodation=10,meals=10,localTransport=10,activities=10,departureTravel=0),
                dayStart='08:00',requiredMainActivities={'main_1':activity('Museum',2),'main_2':activity('Garden',3)},
                activities=[activity('Transfer',1,'transfer')]))
        output={'journeyStrategy':strategy,'startLocation':self.prefs['departureCity'] if dates[0]==self.prefs['startDate'] else self.prefs['destination'],
            'endLocation':self.prefs['departureCity'] if dates[-1]==self.prefs['endDate'] else self.prefs['destination'],
            'recommendations':[],'proposal':{'status':'planned','days':days,'explanation':'Synthetic coherent section.',
                'warnings':{'verificationWarning':'Synthetic estimates; no live checks.','additionalWarnings':[]}}}
        response='resp_fixture'+str(self.calls);self.outputs[response]=json.dumps(output)
        return SimpleNamespace(response_id=response,status='queued',output_text=None,refused=False)
    async def retrieve(self,response): return SimpleNamespace(response_id=response,status='completed',output_text=self.outputs[response],refused=False)
    async def cancel(self,response): return None

@pytest.fixture
def bridge():
    if not os.getenv('PLANNING_SQL_TEST_MODULE') and not (Path(__file__).parent/'sql/node_modules/@electric-sql/pglite').exists():
        pytest.skip('Install pinned test-only PGlite dependency or set PLANNING_SQL_TEST_MODULE')
    value=Bridge()
    try: yield value
    finally:value.close()


def test_real_sql_24_day_http_and_restart_pipeline(monkeypatch,payload,bridge):
    monkeypatch.setenv('ADAPTIVE_PLANNING_PREVIEW','true');monkeypatch.setenv('APP_MODE','local')
    prefs={**payload,'startDate':'2028-01-01','endDate':'2028-01-24','budget':5000}
    repo=SectionCheckpointRepository(bridge,enabled=True);provider=FakeProvider(repo,prefs)
    worker=AdaptivePlanningWorker(repo,provider,enabled=True)
    engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False)
    app=create_app(auth_service=Auth(),adaptive_engine=engine)
    client=TestClient(app);headers={'Authorization':'Bearer owner'}
    request=str(uuid4());started=client.post('/api/adaptive-plans',headers=headers,json={'requestId':request,'preferences':prefs})
    assert started.status_code==200,started.text
    plan=started.json()['plan'];assert plan['totalDays']==24
    # Lost HTTP create response is resolved without another POST/provider call.
    assert client.get('/api/adaptive-plans/requests/'+request,headers=headers).json()['plan']['id']==plan['id']
    assert client.get('/api/adaptive-plans/'+plan['id'],headers={'Authorization':'Bearer other'}).status_code!=200
    asyncio.run(worker.tick())
    # Fresh process objects reuse the durable provider identity, not another create.
    worker=AdaptivePlanningWorker(repo,provider,enabled=True)
    for _ in range(15): asyncio.run(worker.tick())
    assert provider.calls==8
    result=client.get('/api/adaptive-plans/'+plan['id'],headers=headers).json()
    assert result['plan']['status']=='completed' and result['plan']['completedDays']==24
    assert result['plan']['spentCents']==24*4000
    dates=[];cursor=0
    while True:
        result=client.get('/api/adaptive-plans/'+plan['id'],headers=headers,params={'afterSequence':cursor}).json()
        assert len(result['sections'])<=3
        dates.extend(day['date'] for s in result['sections'] for day in s['checkpoint']['itinerary']['days'])
        if result['nextCursor'] is None:break
        cursor=result['nextCursor']
    assert dates==[(date(2028,1,1)+timedelta(days=i)).isoformat() for i in range(24)]
    assert 'provider_response_id' not in json.dumps(result) and 'lease_token' not in json.dumps(result)
    exported=client.get('/api/adaptive-plans/'+plan['id']+'/export',headers=headers)
    assert exported.status_code==200 and 'COMPLETE TRIP EXPORT' in exported.text
    assert exported.text.endswith('\nEND OF ROAMORA EXPORT\n')
    assert '2028-01-24' in exported.text and provider.calls==8
    assert client.get('/api/adaptive-plans/'+plan['id']+'/export',headers={'Authorization':'Bearer other'}).status_code!=200


def test_real_sql_ambiguous_create_never_replayed(monkeypatch,payload,bridge):
    repo=SectionCheckpointRepository(bridge,enabled=True);provider=FakeProvider(repo,payload);provider.mode='ambiguous'
    worker=AdaptivePlanningWorker(repo,provider,enabled=True)
    engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False)
    async def run():
        body=await engine.start(OWNER,str(uuid4()),payload);plan=body['plan']['id']
        await worker.tick();await worker.tick()
        value=await engine.context(OWNER,plan)
        assert value['plan']['activeSection']['status']=='submission_unknown' and provider.calls==1
        with pytest.raises(JobRepositoryError): await engine.retry(OWNER,plan,value['plan']['activeSection']['id'],str(uuid4()))
        cancelled=await engine.cancel(OWNER,plan)
        assert cancelled['plan']['status']=='cancelled'
    asyncio.run(run())


def test_sql_checkpoint_survives_later_failure_and_explicit_retry(monkeypatch,payload,bridge):
    prefs={**payload,'startDate':'2028-02-01','endDate':'2028-02-07','budget':5000}
    repo=SectionCheckpointRepository(bridge,enabled=True);provider=FakeProvider(repo,prefs)
    worker=AdaptivePlanningWorker(repo,provider,enabled=True);engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False)
    async def run():
        plan=(await engine.start(OWNER,str(uuid4()),prefs))['plan']['id']
        await worker.tick();await worker.tick()  # First immutable three-day checkpoint.
        await worker.tick()
        provider.outputs['resp_fixture2']='{"private":"malformed fixture"}'
        await worker.tick()
        failed=await engine.context(OWNER,plan)
        assert failed['plan']['completedDays']==3 and len(failed['sections'])==1
        original=deepcopy(failed['sections'][0])
        assert failed['plan']['activeSection']['errorCode']=='SECTION_INVALID_RESULT'
        await engine.retry(OWNER,plan,failed['plan']['activeSection']['id'],str(uuid4()))
        await worker.tick();await worker.tick()  # Explicit retry shrinks to one day, not a truncated trip.
        current=await engine.context(OWNER,plan)
        assert current['plan']['completedDays']==4 and current['sections'][0]==original
        assert current['preferences']['endDate']=='2028-02-07'
    asyncio.run(run())


def test_sql_cancellation_wins_late_completed_provider_response(monkeypatch,payload,bridge):
    repo=SectionCheckpointRepository(bridge,enabled=True);provider=FakeProvider(repo,payload)
    worker=AdaptivePlanningWorker(repo,provider,enabled=True);engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False)
    async def run():
        plan=(await engine.start(OWNER,str(uuid4()),payload))['plan']['id']
        await worker.tick()
        retrieve=provider.retrieve
        async def late(response):
            result=await retrieve(response)
            await repo.cancel_plan(OWNER,plan)
            return result
        provider.retrieve=late
        with pytest.raises(JobRepositoryError):await worker.tick()
        current=await engine.context(OWNER,plan)
        assert current['plan']['status']=='cancelled' and current['plan']['completedDays']==0 and not current['sections']
        assert provider.calls==1
    asyncio.run(run())


def test_actual_sql_constraint_failure_reaches_edit_recommendations_without_retry(bridge,payload):
    repo=SectionCheckpointRepository(bridge,enabled=True);provider=FakeProvider(repo,payload)
    worker=AdaptivePlanningWorker(repo,provider,enabled=True)
    engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False,run_allowance=1)
    async def run():
        plan=(await engine.start(OWNER,str(uuid4()),payload))['plan']['id']
        await worker.tick()
        output=json.loads(provider.outputs['resp_fixture1'])
        output['proposal'].update(status='infeasible',days=[],explanation='The proposed transfers leave too little time for this activity pace.')
        output['recommendations']=[{'field':'travelPace','reason':'The proposed travel and activity times conflict.',
            'suggestion':'Consider relaxed pace, then review the revised schedule.'}]
        provider.outputs['resp_fixture1']=json.dumps(output)
        await worker.tick()
        actual=await engine.context(OWNER,plan)
        assert actual['plan']['pauseReason']=='CONSTRAINT_CONFLICT'
        assert actual['plan']['remainingCreates']==0
        assert actual['plan']['activeSection']['failureDetails']['recommendations'][0]['field']=='travelPace'
        assert actual['plan']['activeSection']['failureDetails']['applicability']=='proposed'
        assert actual['plan']['completedDays']==0 and provider.calls==1
        # Actual SQL-derived HTTP contract must pass the real browser adapter,
        # not just idealized hand-authored frontend fixtures.
        script="import fs from 'node:fs'; import {validateAdaptivePage} from './frontend/src/services/adaptivePlanning.js'; const b=validateAdaptivePage(JSON.parse(fs.readFileSync(0,'utf8'))); if(b.plan.pauseReason!=='CONSTRAINT_CONFLICT'||b.plan.activeSection.failureDetails.recommendations[0].field!=='travelPace')process.exit(2);"
        checked=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(actual),text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
        assert checked.returncode==0,checked.stderr
        with pytest.raises(JobRepositoryError):await engine.continue_run(OWNER,plan,str(uuid4()))
        with pytest.raises(JobRepositoryError):await engine.retry(OWNER,plan,actual['plan']['activeSection']['id'],str(uuid4()))
        assert (await engine.cancel(OWNER,plan))['plan']['status']=='cancelled'
    asyncio.run(run())
