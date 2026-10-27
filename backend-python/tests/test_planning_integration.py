"""Full HTTP route -> REST repository -> background HTTP -> validated result.

Both remote services are fake transports; SQL behavior is verified separately.
"""
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import httpx
import pytest
from app.generation_contract import GenerationContract
from app.models import TripPreferences
from fastapi.testclient import TestClient
from app.auth import AuthUser
from app.main import create_app
from app.openai_background import OpenAIBackgroundClient, BackgroundActivation
from app.planning_coordinator import DurablePlanningCoordinator
from app.planning_repository import DurablePlanningRepository, PlanningGateway
from app.planning_worker import PlanningWorker

OWNER=str(uuid4());OTHER=str(uuid4())
class Auth:
    def configured(self):return True
    async def verify(self,token):return AuthUser(id=OWNER if token=='owner' else OTHER)


@pytest.mark.parametrize('planned,blocked',[(False,False),(True,False),(True,True),(True,'clear')])
def test_durable_route_provider_and_restart_recovery(monkeypatch,payload,planned,blocked):
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true');monkeypatch.setenv('APP_MODE','local')
    rows={};provider_calls=[];db_calls=[]
    def db(request):
        path=request.url.path.removeprefix('/rest/v1/')
        body=json.loads(request.content) if request.content else None
        db_calls.append((request.method,path))
        if path=='planning_jobs':
            found=[deepcopy(row) for row in rows.values() if all(row.get(k)==v[3:] for k,v in request.url.params.items() if k!='limit')]
            return httpx.Response(200,json=found)
        if path=='rpc/enqueue_planning_job':
            row={**body['request_row'],'version':1,'provider_response_id':None,'result':None,'lease_token':None}
            rows[row['id']]=row
            return httpx.Response(200,json=[deepcopy(row)])
        if path=='rpc/claim_planning_job':
            pending=[row for row in rows.values() if row['status'] in {'queued','running'}]
            if not pending:return httpx.Response(200,json=[])
            row=pending[0];row.update(lease_token=str(uuid4()),version=row['version']+1)
            return httpx.Response(200,json=[deepcopy(row)])
        if path=='rpc/transition_planning_job':
            row=rows[body['job']]
            if row['lease_token']!=body['lease'] or row['version']!=body['expected_version']:
                return httpx.Response(200,json=[])
            row.update(status=body['next_status'],version=row['version']+1,result=body['output'],error_code=body['failure_code'],evidence=body['evidence_payload'])
            if body['response_id']:row['provider_response_id']=body['response_id']
            if row['status']!='submitting':row['lease_token']=None
            return httpx.Response(200,json=[deepcopy(row)])
        raise AssertionError(path)
    proposal={'status':'infeasible','days':[],'explanation':'Travel cannot fit the supplied budget.',
              'warnings':{'verificationWarning':'Confirm transport prices before booking.','additionalWarnings':[]}}
    if planned:
        days=[]
        for day in GenerationContract(TripPreferences.model_validate(payload)).dates:
            entries={f'main_{i+1}':dict(id=f'activity-{i}',title='Museum' if i==0 else 'Cultural walk',
                durationMinutes=60,notes='Confirm access before visiting.',latitude=None,longitude=None,
                kind='main',gapBeforeMinutes=0 if i==0 else 60,sequence=i+1) for i in range(2)}
            days.append(dict(date=day,morning='Museum visit.',afternoon='Cultural walk.',evening='Rest.',
                dining='Confirm meal suitability.',dietaryNotes='No dietary needs supplied.',mobilityNotes='No mobility needs supplied.',
                transitAndRest='Allow travel and rest.',interestTags=['culture'],
                costs=dict(accommodation=100,meals=20,localTransport=10,activities=10,departureTravel=20),
                dayStart='09:00',requiredMainActivities=entries,activities=[]))
        proposal.update(status='planned',days=days,explanation='A cautious estimated plan.')
    def provider(request):
        provider_calls.append((request.method,request.url.path))
        status='queued' if request.method=='POST' else 'completed'
        value={'id':'resp_integrated','object':'response','status':status,'output':[],'error':None}
        if status=='completed':value['output']=[{'type':'message','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(proposal)}]}]
        return httpx.Response(200,json=value)
    gateway=PlanningGateway('https://fakeproject.supabase.co','sb_secret_fake_test_only',enabled=True,transport=httpx.MockTransport(db))
    repo=DurablePlanningRepository(gateway,enabled=True)
    provider_client=OpenAIBackgroundClient('fake-only-test-key',activation=BackgroundActivation(True,True),transport=httpx.MockTransport(provider))
    gate=None
    if blocked:
        from datetime import date
        from app.travel_evidence import EvidenceScope, TrustedEvidence
        from app.travel_feasibility import TravelConstraint, build_feasibility_gate
        now=datetime.now(timezone.utc)
        evidence=TrustedEvidence(providerId='official',scope=EvidenceScope(destinationId='goa-in',
            localDate=date.fromisoformat(payload['startDate']),timeZone='Asia/Kolkata',kind='closure',subjectId='activity-0'),
            sourceURL='https://official.example/closures',checkedAt=now-timedelta(minutes=1),expiresAt=now+timedelta(hours=1),
            validFrom=date.fromisoformat(payload['startDate']),validUntil=date.fromisoformat(payload['startDate']),
            outcome='blocked' if blocked is True else 'clear',summary='Venue notice checked for this date.',fallback='Choose another venue or date.')
        gate=build_feasibility_gate(constraints=(TravelConstraint(evidence=evidence,rule='closure'),),
            accepted_providers=frozenset({'official'}),now=lambda:now,destination_id='goa-in',time_zone='Asia/Kolkata')
    worker=PlanningWorker(repo,provider_client,enabled=True,feasibility_gate=gate)
    coordinator=DurablePlanningCoordinator(repo,worker,enabled=True)
    app=create_app(auth_service=Auth(),planning_engine=coordinator)
    with TestClient(app) as browser:
        headers={'Authorization':'Bearer owner'}
        body={'requestId':str(uuid4()),'preferences':payload}
        started=browser.post('/api/planning-jobs',json=body,headers=headers)
        assert started.status_code==200,started.text
        job=started.json();url='/api/planning-jobs/'+job['id']
        assert job['status']=='queued'
        # A browser that lost the POST response knows only requestId: read-only recovery.
        recovered=browser.get('/api/planning-jobs/requests/'+body['requestId'],headers=headers)
        assert recovered.json()['id']==job['id']
        context=browser.get('/api/planning-jobs/requests/'+body['requestId']+'/context',headers=headers)
        assert context.json()['preferences']['destination']==payload['destination']
        assert browser.get(url+'/context',headers={'Authorization':'Bearer other'}).status_code==404
        assert browser.get('/api/planning-jobs/requests/'+body['requestId'],headers={'Authorization':'Bearer other'}).status_code==404
        assert browser.post('/api/planning-jobs',json=body,headers=headers).json()['id']==job['id']
        browser.portal.call(worker.tick)
        assert rows[job['id']]['provider_response_id']=='resp_integrated'
        # Recreate the worker (simulated process restart); no new provider create.
        resumed=PlanningWorker(repo,provider_client,enabled=True,feasibility_gate=gate)
        browser.portal.call(resumed.tick)
        result=browser.get(url,headers=headers)
        assert result.status_code==200,result.text
        if blocked is True:
            assert result.json()['status']=='failed'
            assert result.json()['result'] is None
            assert rows[job['id']]['error_code']=='JOB_TRAVEL_CONFLICT'
            return
        assert result.json()['status']=='succeeded'
        assert result.json()['result']['status']==('planned' if planned else 'infeasible')
        if blocked=='clear':
            assert result.json()['evidence']['destinationId']=='goa-in'
            assert result.json()['evidence']['assessments'][0]['status']=='verified'
        if planned:
            assert result.json()['result']['estimatedTotalGroupCost']==960
            assert result.json()['result']['days'][0]['activities'][1]['startTime']=='11:00'
        assert browser.get(url,headers={'Authorization':'Bearer other'}).status_code==404
        assert 'provider_response_id' not in result.text and 'lease_token' not in result.text
        assert provider_calls==[('POST','/v1/responses'),('GET','/v1/responses/resp_integrated')]
        assert sum(path=='rpc/enqueue_planning_job' for _,path in db_calls)==1
