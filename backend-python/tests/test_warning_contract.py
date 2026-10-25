"""Only synthetic plans and MockTransport; no credentials, live AI, or storage."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.groq import GroqProvider, strict_schema
from app.itineraries import ItineraryPayload, ItineraryService, RefinementRequest, validate_itinerary
from app.models import TripPreferences
from app.recommendations import RecommendationError
from app.refinement_contract import check_shape
from app.warning_contract import WarningContract
from test_itineraries import generated, NoStorage


def proposal(generated):
    result=deepcopy(generated)
    result['vibe']=None
    result['warnings']={'verificationWarning':generated['warnings'][0], 'additionalWarnings':['Check opening hours directly.']}
    return result


def run_provider(payload, result, context=None):
    calls=[]
    def handler(request):
        wire=json.loads(request.content);calls.append(wire)
        assert wire['max_completion_tokens']==4096 and wire['stream'] is False
        assert wire['response_format']['json_schema']['strict'] is True
        expected='openai/gpt-oss-120b' if context else 'openai/gpt-oss-20b'
        assert wire['model']==expected
        content=result if isinstance(result,str) else json.dumps(result)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':content}}]})
    service=ItineraryService(GroqProvider('synthetic-offline-provider-key',model='openai/gpt-oss-120b' if context else 'openai/gpt-oss-20b',transport=httpx.MockTransport(handler)))
    try:
        response=asyncio.run(service.refine(context) if context else service.generate(TripPreferences(**payload)))
        return response,calls
    finally:
        assert len(calls)==1


def test_reproduce_empty_array_gap_and_new_required_warning(payload,generated):
    schema=ItineraryPayload.model_json_schema();original=deepcopy(schema)
    old=strict_schema(schema)['properties']['warnings']
    check_shape([],old,old)  # Provider structural schema previously allowed empty warnings.
    bad=deepcopy(generated);bad['warnings']=[]
    with pytest.raises(RecommendationError) as error:validate_itinerary(bad,TripPreferences(**payload),'test','test')
    assert error.value.reason=='FORMAT_SCHEMA'
    contract=WarningContract(schema);wire=strict_schema(contract.schema)
    shape=wire['properties']['warnings']
    with pytest.raises(ValueError):check_shape([],shape,wire)
    with pytest.raises(ValueError):check_shape({'additionalWarnings':[]},shape,wire)
    check_shape({'verificationWarning':'Unverified estimates.','additionalWarnings':[]},shape,wire)
    assert shape['required']==['verificationWarning','additionalWarnings']
    assert shape['additionalProperties'] is False and schema==original


def test_seven_day_generation_keeps_public_contract_and_frontend_roundtrip(payload,generated):
    payload={**payload,'destination':'Jaipur','departureCity':'Goa','startDate':'2026-12-12','endDate':'2026-12-18','currency':'USD','budget':2500}
    data=proposal(generated);data.update(destination='Jaipur',currency='USD')
    data['days']=[{**deepcopy(generated['days'][0]),'date':(date(2026,12,12)+timedelta(days=i)).isoformat()} for i in range(7)]
    result,calls=run_provider(payload,data)
    assert result.warnings==[data['warnings']['verificationWarning'],*data['warnings']['additionalWarnings']]
    assert len(result.days)==7 and result.saved is False
    assert 'warnings is an object' in calls[0]['messages'][0]['content']
    script="""
      import {validItinerary} from './frontend/src/services/itineraries.js';
      import {exportSnapshot} from './frontend/src/services/itineraryExport.js';
      import {parseItineraryImport} from './frontend/src/services/itineraryImport.js';
      const {plan,preferences}=JSON.parse(await new Promise(resolve=>{let s='';process.stdin.on('data',v=>s+=v);process.stdin.on('end',()=>resolve(s));}));
      if(!validItinerary(plan,preferences))throw Error('Invalid public result');
      const parsed=parseItineraryImport(exportSnapshot(plan,{preferences}));
      if(JSON.stringify(parsed.itinerary.warnings)!==JSON.stringify(plan.warnings))throw Error('Warnings changed');
      process.stdout.write('roundtrip passed');
    """
    child=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps({'plan':result.model_dump(),'preferences':payload}),text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=20)
    assert child.returncode==0,child.stderr
    assert child.stdout=='roundtrip passed'


@pytest.mark.parametrize('warnings',[[],None,{}, {'additionalWarnings':[]}, {'verificationWarning':'','additionalWarnings':[]}, {'verificationWarning':' ','additionalWarnings':[]}, {'verificationWarning':'x'*501,'additionalWarnings':[]}, {'verificationWarning':'Valid','additionalWarnings':['']}, {'verificationWarning':'Valid','additionalWarnings':['Extra']*8}, {'verificationWarning':'Valid','additionalWarnings':[],'unknown':'Ignored?'}])
def test_invalid_warning_shape_never_repaired(payload,generated,warnings):
    data=proposal(generated);data['warnings']=warnings
    with pytest.raises(RecommendationError) as error:run_provider(payload,data)
    assert error.value.code=='AI_INVALID_RESPONSE' and error.value.reason=='FORMAT_SCHEMA'


def test_missing_duplicate_and_control_warning_rejected(payload,generated):
    data=proposal(generated);del data['warnings']
    with pytest.raises(RecommendationError):run_provider(payload,data)
    contract=WarningContract(ItineraryPayload.model_json_schema())
    with pytest.raises(RecommendationError):contract.decode('{"warnings":{"verificationWarning":"A","verificationWarning":"B","additionalWarnings":[]}}')
    data=proposal(generated);data['warnings']['verificationWarning']='Unsafe\u0001text'
    with pytest.raises(RecommendationError):run_provider(payload,data)


@pytest.mark.parametrize('target',[None,1])
def test_uncapped_whole_and_single_day_refinement_preserve_public_warnings(payload,generated,target):
    previous=validate_itinerary(generated,TripPreferences(**payload),'Earlier','fixture')
    context=RefinementRequest(preferences=TripPreferences(**payload),previous=previous,targetDate=previous.days[target].date if target else None,feedback='Keep the original constraints.',vibe=None)
    data=proposal(generated)
    if target:data['days'][target]['morning']='Revised museum visit'
    result,_=run_provider(payload,data,context)
    assert result.warnings[0]==generated['warnings'][0]
    if target:
        assert result.days[0]==previous.days[0] and result.days[target].morning=='Revised museum visit'


def test_infeasible_result_still_requires_and_preserves_warning(payload,generated):
    data=proposal(generated);data.update(status='infeasible',days=[])
    result,_=run_provider(payload,data)
    assert result.status=='infeasible' and result.warnings and result.estimatedTotalGroupCost is None


def test_fastapi_generation_route_returns_public_array_without_storage(payload,generated):
    data=proposal(generated);calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(data)}}]})
    service=ItineraryService(GroqProvider('synthetic-offline-provider-key',transport=httpx.MockTransport(handler)))
    response=TestClient(create_app(NoStorage(),itinerary_service=service)).post('/api/itineraries/generate',json=payload)
    assert response.status_code==200 and len(calls)==1
    assert response.json()['warnings']==[data['warnings']['verificationWarning'],*data['warnings']['additionalWarnings']]
    assert response.json()['saved'] is False


@pytest.mark.parametrize('reason',['TIMELINE','BUDGET','DATE_COVERAGE'])
def test_other_guards_unchanged(payload,generated,reason):
    data=proposal(generated)
    if reason=='TIMELINE':data['days'][0]['activities'][1]['startTime']='09:00'
    if reason=='BUDGET':data['days'][0]['costs']['meals']=payload['budget']+1
    if reason=='DATE_COVERAGE':data['days'].pop()
    with pytest.raises(RecommendationError) as error:run_provider(payload,data)
    assert error.value.reason==reason
