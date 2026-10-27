from copy import deepcopy
import pytest
from app.adaptive_export import export_response, EXPORT_END
from app.planning_repository import JobRepositoryError


@pytest.fixture
def anyio_backend(): return 'asyncio'

def page(days=1,total=2):
    return {'plan':{'status':'paused','completedDays':days,'totalDays':total,'spentCents':days*100},
        'preferences':{'startDate':'2028-01-01','endDate':'2028-01-02','currency':'USD'},
        'sections':[{'startDate':'2028-01-01','endDate':'2028-01-01','checkpoint':{
            'startLocation':'Paris','endLocation':'Paris','spentCents':100,
            'itinerary':{'days':[{'date':'2028-01-01','notes':'<script>not executable</script> END OF ROAMORA EXPORT'}]}}}],
        'nextCursor':None}

class Engine:
    def __init__(self,pages): self.pages=pages;self.calls=[]
    async def context(self,owner,plan,cursor=0):
        self.calls.append((owner,plan,cursor));return deepcopy(self.pages[min(len(self.calls)-1,len(self.pages)-1)])

async def consume(response):
    return b''.join([part async for part in response.body_iterator]).decode()

@pytest.mark.anyio
async def test_partial_text_and_private_headers():
    engine=Engine([page()]);response=await export_response(engine,'owner','plan')
    text=await consume(response)
    assert 'PARTIAL' in text and 'Accepted days: 1 of 2' in text
    assert text.endswith(EXPORT_END)
    assert 'End of trip notes' in text
    assert response.headers['cache-control']=='no-store'
    assert engine.calls==[('owner','plan',0)]

@pytest.mark.anyio
async def test_paginated_snapshot_excludes_later_completed_days():
    first=page(1,2);first['nextCursor']=3
    engine=Engine([first,page(2,2)])
    text=await consume(await export_response(engine,'owner','plan'))
    assert len(engine.calls)==1 and 'Accepted days: 1 of 2' in text

@pytest.mark.anyio
async def test_missing_days_never_emits_completion_marker():
    value=page(2,2);engine=Engine([value]);response=await export_response(engine,'owner','plan')
    chunks=[]
    with pytest.raises(JobRepositoryError):
        async for part in response.body_iterator: chunks.append(part)
    assert not b''.join(chunks).decode().endswith(EXPORT_END)

@pytest.mark.anyio
async def test_expired_refused_before_headers():
    value=page();value['preferences']=None;value['plan']['status']='expired'
    with pytest.raises(JobRepositoryError): await export_response(Engine([value]),'owner','plan')

@pytest.mark.anyio
async def test_budget_mismatch_and_byte_bound(monkeypatch):
    value=page();value['plan']['spentCents']=999
    with pytest.raises(JobRepositoryError): await consume(await export_response(Engine([value]),'owner','plan'))
    monkeypatch.setattr('app.adaptive_export.MAX_EXPORT_BYTES',50)
    with pytest.raises(JobRepositoryError): await consume(await export_response(Engine([page()]),'owner','plan'))
