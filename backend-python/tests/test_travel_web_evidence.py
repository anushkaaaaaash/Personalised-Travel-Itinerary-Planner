import json
from datetime import date, datetime, timezone
import httpx, pytest
from pydantic import ValidationError
from app.travel_web_evidence import PublicTravelQuery, WebEvidencePolicy, OpenAIWebEvidence, ENDPOINT
NOW=datetime(2026,10,27,5,tzinfo=timezone.utc)
URL='https://www.louvre.fr/en/visit/hours-admission'
QUERY=PublicTravelQuery(destinationId='paris-fr',destinationName='Paris',countryCode='FR',startDate=date(2026,10,27),endDate=date(2026,10,29),venueNames=('Louvre',))
def envelope(url=URL,source=URL,status='completed'):
    return {'status':status,'output':[{'type':'web_search_call','status':'completed','action':{'type':'search','sources':[{'type':'url','url':source}]}},
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':'Check the official dated notice.',
            'annotations':[{'type':'url_citation','url':url,'title':'Official venue','start_index':0,'end_index':5}]}]}]}
def policy(**kwargs):
    return WebEvidencePolicy(**dict(dict(enabled=True,costApproved=True,destinationId='paris-fr',officialDomains=('louvre.fr',)),**kwargs))
async def run(payload=None,p=None,status=200):
    requests=[]
    async def handler(request):
        requests.append(request)
        return httpx.Response(status,json=payload or envelope())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await OpenAIWebEvidence(client=client,api_key='synthetic-key',policy=p or policy(),clock=lambda:NOW).research(QUERY)
    return result,requests
@pytest.mark.anyio
async def test_disabled_defaults_make_zero_calls():
    r,requests=await run(p=WebEvidencePolicy()); assert r.status=='disabled' and requests==[]
@pytest.mark.anyio
@pytest.mark.parametrize('change',[dict(costApproved=False),dict(officialDomains=()),dict(destinationId='other')])
async def test_gate_before_network(change):
    r,requests=await run(p=policy(**change));assert r.status=='disabled' and not requests
@pytest.mark.anyio
async def test_real_request_contract_and_minimized_dto():
    r,requests=await run(); assert r.status=='available' and r.applicability=='unverified' and r.checkedAt==NOW
    body=json.loads(requests[0].content)
    assert str(requests[0].url)==ENDPOINT and body['model']=='gpt-6-luna' and body['reasoning']=={'effort':'max'}
    assert body['store'] is False and body['max_tool_calls']==2 and body['max_output_tokens']==16384
    assert body['include']==['web_search_call.action.sources'] and body['tools'][0]['external_web_access'] is True
    assert set(json.loads(body['input']))=={'destinationId','destinationName','countryCode','startDate','endDate','venueNames','mode'}
@pytest.mark.anyio
@pytest.mark.parametrize('url,source',[('https://invented.example/notice',URL),(URL,'https://other.example/notice'),('https://louvre.fr.evil.example/a','https://louvre.fr.evil.example/a')])
async def test_fake_or_unofficial_citations_fail_closed(url,source):
    r,_=await run(envelope(url,source));assert r.status=='unavailable' and not r.researchText
@pytest.mark.anyio
async def test_incomplete_max_reasoning_fails_closed():
    r,requests=await run(envelope(status='incomplete'));assert r.status=='unavailable' and r.reason=='INCOMPLETE_RESPONSE' and len(requests)==1
@pytest.mark.anyio
async def test_no_search_is_not_all_clear():
    e=envelope();e['output']=e['output'][1:]
    r,_=await run(e);assert r.status=='unavailable' and not r.sources
@pytest.mark.anyio
async def test_invalid_citation_offsets_rejected():
    e=envelope();e['output'][1]['content'][0]['annotations'][0]['end_index']=99999
    r,_=await run(e);assert r.status=='unavailable'
@pytest.mark.anyio
async def test_transport_failure_no_retry():
    r,requests=await run(status=429); assert r.status=='unavailable' and len(requests)==1
@pytest.mark.parametrize('extra',[dict(email='a@example.com'),dict(mobilityConcerns='private'),dict(budget=500)])
def test_sensitive_extra_input_rejected(extra):
    with pytest.raises(ValidationError):PublicTravelQuery(**dict(QUERY.model_dump(),**extra))
@pytest.mark.parametrize('name',['a@example.com','Paris\nprivate','https://example.com'])
def test_nonpublic_label_forms_rejected(name):
    with pytest.raises(ValidationError):PublicTravelQuery(**dict(QUERY.model_dump(),destinationName=name))
