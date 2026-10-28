from copy import deepcopy
from datetime import date,timedelta
from io import BytesIO
import pytest
from app.itinerary_pdf import render_pdf,pdf_response,archived_pdf_response
from app.planning_repository import JobRepositoryError

@pytest.fixture
def anyio_backend():return 'asyncio'

def fixture(n=1):
    preferences={'destination':'Paris & Kyoto 東京','startDate':'2028-01-01','endDate':(date(2028,1,1)+timedelta(days=n-1)).isoformat(),'currency':'EUR','budget':n*1000,'travelers':2}
    sections=[]
    for i in range(n):
        stamp=(date(2028,1,1)+timedelta(days=i)).isoformat()
        day={'date':stamp,'costs':dict(accommodation=50,meals=20,localTransport=10,activities=15,departureTravel=5),'activities':[dict(startTime='09:00',title='Café <b>literal title</b>',durationMinutes=120,notes=('Long travel notes & details. '*40)+f'LAST-NOTE-{i}')],**{k:'A relaxed café stop and walk.' for k in ['morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest']}}
        sections.append({'startDate':stamp,'endDate':stamp,'checkpoint':{'spentCents':10000,'itinerary':{'days':[day],'warnings':['Verify opening hours.']}}})
    return preferences,{'status':'completed','completedDays':n,'totalDays':n,'spentCents':n*10000},sections

class Engine:
    def __init__(self,n=1):self.preferences,self.plan,self.sections=fixture(n);self.calls=[]
    async def context(self,owner,plan_id,cursor=0):
        self.calls.append((owner,plan_id,cursor));end=min(cursor+3,len(self.sections))
        return deepcopy({'preferences':self.preferences,'plan':self.plan,'sections':self.sections[cursor:end],'nextCursor':end if end<len(self.sections) else None})

@pytest.mark.anyio
async def test_pdf_owner_scoped_paginated_and_complete():
    engine=Engine(24);response=await pdf_response(engine,'owner','plan')
    assert response.body.startswith(b'%PDF-') and response.body.endswith(b'%%EOF\n')
    assert response.headers['content-type']=='application/pdf' and response.headers['cache-control']=='no-store'
    assert len(engine.calls)==8 and all(x[:2]==('owner','plan') for x in engine.calls)
    # Poppler extraction in visual QA additionally checks every date and terminal note.

@pytest.mark.anyio
async def test_missing_day_or_wrong_spend_fails_before_response():
    for mode in ('date','spend','truncated'):
        engine=Engine(4)
        if mode=='date':engine.sections[3]['checkpoint']['itinerary']['days'][0]['date']='2028-01-05'
        if mode=='spend':engine.plan['spentCents']+=1
        if mode=='truncated':engine.sections=engine.sections[:3]
        with pytest.raises(JobRepositoryError):await pdf_response(engine,'owner','plan')

@pytest.mark.anyio
async def test_partial_pdf_and_expired_plan():
    engine=Engine();engine.plan['totalDays']=2;engine.plan['status']='paused'
    assert (await pdf_response(engine,'owner','plan')).status_code==200
    engine.preferences=None
    with pytest.raises(JobRepositoryError):await pdf_response(engine,'owner','plan')

@pytest.mark.anyio
async def test_saved_export_uses_only_archive_not_expiring_source():
    engine=Engine(4)
    class Service:
        async def get(self,identity,cursor=0):
            value=await engine.context(None,identity,cursor)
            return {**value,'saved':{**value['plan'],'id':identity}}
    response=await archived_pdf_response(Service(),'saved')
    assert response.body.startswith(b'%PDF-') and len(engine.calls)==2


def test_visible_snapshot_pdf_has_no_provider_or_storage_calls(payload):
    from tests.test_itineraries import generated,NoStorage,Provider
    from app.main import create_app
    from app.itineraries import ItineraryService
    from fastapi.testclient import TestClient
    provider=Provider()
    itinerary=generated.__wrapped__(payload)
    client=TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(provider)))
    response=client.post('/api/itineraries/export-pdf',json={'preferences':payload,'itinerary':itinerary})
    assert response.status_code==200,response.text[:100]
    assert response.content.startswith(b'%PDF-') and not provider.calls
    itinerary['days'][0]['date']='2028-12-31'
    response=client.post('/api/itineraries/export-pdf',json={'preferences':payload,'itinerary':itinerary})
    assert response.status_code==400 and not provider.calls


def test_renderer_resource_bounds(monkeypatch):
    import app.itinerary_pdf as module
    p,plan,sections=fixture()
    assert module._RENDER_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(JobRepositoryError):module.render_pdf(p,plan,sections)
    finally:module._RENDER_SLOT.release()
    monkeypatch.setattr(module,'MAX_RENDER_SECONDS',-1)
    with pytest.raises(JobRepositoryError):module.render_pdf(p,plan,sections)
    monkeypatch.setattr(module,'MAX_RENDER_SECONDS',30)
    monkeypatch.setattr(module,'MAX_BYTES',128)
    with pytest.raises(JobRepositoryError):module.render_pdf(p,plan,sections)


def test_valid_snapshot_over_16k_uses_bounded_export_body_allowance(payload):
    import json
    from tests.test_itineraries import generated,NoStorage
    from app.main import create_app
    from fastapi.testclient import TestClient
    itinerary=generated.__wrapped__(payload)
    for day in itinerary['days']:
        for key in ('morning','afternoon','evening','dining'):day[key]='A pleasant walk. '*35
    body={'preferences':payload,'itinerary':itinerary}
    assert 16384<len(json.dumps(body))<65536
    response=TestClient(create_app(NoStorage())).post('/api/itineraries/export-pdf',json=body)
    assert response.status_code==200,response.text[:100]


def test_production_snapshot_requires_auth_before_render(monkeypatch,payload):
    from tests.test_production_readiness import configure,Auth
    from tests.test_itineraries import generated,NoStorage
    from app.main import create_app
    from fastapi.testclient import TestClient
    configure(monkeypatch)
    monkeypatch.setattr('app.itinerary_pdf.render_pdf',lambda *args:pytest.fail('Unauthorized request must not render'))
    client=TestClient(create_app(NoStorage(),auth_service=Auth()),base_url='https://api.example.test')
    response=client.post('/api/itineraries/export-pdf',json={'preferences':payload,'itinerary':generated.__wrapped__(payload)})
    assert response.status_code==401


@pytest.mark.anyio
async def test_admission_is_fail_fast_and_held_after_request_cancel():
    import asyncio
    from app.itinerary_pdf import pdf_admission
    started=asyncio.Event();finish=asyncio.Event()
    @pdf_admission
    async def work():started.set();await finish.wait();return 'done'
    first=asyncio.create_task(work());await started.wait();first.cancel()
    with pytest.raises(asyncio.CancelledError):await first
    assert (await work()).status_code==429
    finish.set();await asyncio.sleep(0);await asyncio.sleep(0)
    assert await work()=='done'
