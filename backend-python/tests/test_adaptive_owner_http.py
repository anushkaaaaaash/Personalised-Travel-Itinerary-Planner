"""Real SQLite and authenticated HTTP recovery; no live provider or saved data."""
import asyncio
import logging
from copy import deepcopy
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import create_app
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from app.section_repository import SectionCheckpointRepository
from app.adaptive_worker import AdaptivePlanningWorker
from app.adaptive_coordinator import AdaptiveCoordinator
from test_adaptive_integration import Auth, FakeProvider, OWNER
from test_adaptive_sqlite import mutate


def test_current_owner_lookup_and_explicit_stop_preserve_checkpoints(monkeypatch,tmp_path,payload,caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    monkeypatch.setenv('ADAPTIVE_PLANNING_PREVIEW','true')
    monkeypatch.setenv('APP_MODE','local')
    gateway=AdaptiveSQLiteGateway(tmp_path/'db.sqlite3',enabled=True,initialize=True)
    asyncio.run(gateway.purge_expired())
    repo=SectionCheckpointRepository(gateway,enabled=True)
    provider=FakeProvider(repo,payload)
    worker=AdaptivePlanningWorker(repo,provider,enabled=True)
    engine=AdaptiveCoordinator(repo,worker,enabled=True,require_health=False)
    client=TestClient(create_app(auth_service=Auth(),adaptive_engine=engine))
    headers={'Authorization':'Bearer owner'}
    assert client.get('/api/adaptive-plans/current').status_code==401
    absent=client.get('/api/adaptive-plans/current',headers=headers)
    assert absent.status_code==404 and absent.json()['error']['code']=='SECTION_CURRENT_NOT_FOUND'
    start=client.post('/api/adaptive-plans',headers=headers,json={'requestId':str(uuid4()),'preferences':payload})
    assert start.status_code==200
    plan=start.json()['plan']['id']
    mutate(gateway.path,'plans',plan,status='paused',pause_reason='SECTION_FAILED')
    before=deepcopy(asyncio.run(repo.get_plan(OWNER,plan)))
    attempted={**payload,'destination':'Kyoto, Japan'}
    rejected=client.post('/api/adaptive-plans',headers=headers,json={'requestId':str(uuid4()),'preferences':attempted})
    assert rejected.status_code==429 and rejected.json()['error']['code']=='SECTION_OWNER_PLAN_EXISTS'
    assert 'Adaptive admission rejected: SECTION_OWNER_PLAN_EXISTS' in caplog.text
    assert 'Kyoto' not in caplog.text and OWNER not in caplog.text
    current=client.get('/api/adaptive-plans/current',headers=headers)
    assert current.status_code==200 and current.json()['plan']['id']==plan
    assert current.json()['preferences']['destination']==payload['destination']
    assert asyncio.run(repo.get_plan(OWNER,plan))==before
    assert client.get('/api/adaptive-plans/current',headers={'Authorization':'Bearer other'}).status_code==404
    assert provider.calls==0
    stopped=client.post('/api/adaptive-plans/'+plan+'/cancel',headers=headers,json={})
    assert stopped.status_code==200 and stopped.json()['plan']['status']=='cancelled'
    assert client.get('/api/adaptive-plans/current',headers=headers).status_code==404
    assert provider.calls==0
    new=client.post('/api/adaptive-plans',headers=headers,json={'requestId':str(uuid4()),'preferences':attempted})
    assert new.status_code==200 and new.json()['plan']['id']!=plan
    assert provider.calls==0
    asyncio.run(gateway.close())


def test_high_structured_planner_keeps_decision_useful_descriptions(payload):
    from app.adaptive_planning import SectionContract,SectionSpec
    from app.openai_background import OpenAIBackgroundClient
    contract=SectionContract(SectionSpec.from_manifest(payload))
    assert OpenAIBackgroundClient.reasoning_effort=='high'
    assert 'Preserve meaningful detail; remove only repetition.' in contract.instructions
    assert 'Do not invent current opening hours' in contract.instructions
    assert 'one short sentence' not in contract.instructions
