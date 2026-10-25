"""Prospective contract tests; no live requests or repaired provider output.

Observed failure mechanics below came from retained synthetic-trip response SHA256
0ef4daf3d3f9fff880e889a5139b08a8c6246aa2f1855d91859a49fcb8eea062.
Only times/durations/kinds/empty-field evidence are retained, not its prose.
"""
from copy import deepcopy
import json,subprocess
from pathlib import Path
import httpx,pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import create_app
from app.groq import GroqProvider,strict_schema
from app.itineraries import ItineraryDay,ItineraryPayload,ItineraryService,validate_itinerary
from app.models import TripPreferences
from app.generation_contract import GenerationContract,SCHEDULE_NOTICE
from app.recommendations import RecommendationError
from test_itineraries import generated,NoStorage
from generation_fixture import private_proposal

@pytest.fixture
def wire(payload,generated):
    data=deepcopy(generated);data['warnings']={'verificationWarning':'Synthetic estimates require verification.','additionalWarnings':[]}
    return private_proposal(data,payload)

@pytest.mark.parametrize('times',[(('08:00',60,'meal'),('08:30',120,'main')),
    (('07:30',60,'meal'),('08:00',30,'transfer')),
    (('12:00',120,'main'),('13:30',30,'transfer'))])
def test_observed_three_overlaps_still_rejected(generated,times):
    day=deepcopy(generated['days'][0]);template=day['activities'][0]
    day['activities']=[{**template,'id':f'observed-{i}','startTime':t,'durationMinutes':d,'kind':k} for i,(t,d,k) in enumerate(times)]
    with pytest.raises(ValidationError) as error:ItineraryDay.model_validate(day)
    assert any(e['type']=='itinerary_overlap' for e in error.value.errors())

def test_observed_empty_evening_still_rejected(generated):
    day=deepcopy(generated['days'][0]);day['evening']=''
    with pytest.raises(ValidationError) as error:ItineraryDay.model_validate(day)
    assert any(e['loc']==('evening',) and e['type']=='string_too_short' for e in error.value.errors())

def test_observed_final_day_count_one_with_no_main_cannot_satisfy_balanced(payload,generated):
    data=deepcopy(generated);day=data['days'][-1];template=day['activities'][0]
    day['mainActivityCount']=1
    day['activities']=[{**template,'id':f'observed-{i}','startTime':t,'durationMinutes':d,'kind':k,'fixedTime':fixed}
        for i,(t,d,k,fixed) in enumerate([('07:00',60,'meal',False),('08:30',30,'transfer',False),('10:00',240,'transfer',True)])]
    with pytest.raises(RecommendationError) as error:validate_itinerary(data,TripPreferences(**payload),'fixture','fixture')
    assert error.value.reason=='PACE'

@pytest.mark.parametrize('pace,minimum,maximum',[('relaxed',1,2),('balanced',2,3),('fast',3,4)])
def test_required_named_main_slots_and_optional_upper_bound(payload,pace,minimum,maximum):
    contract=GenerationContract(TripPreferences(**{**payload,'travelPace':pace}))
    slots=contract.schema['$defs']['GenerationDay']['properties']['entries']['properties']
    assert sum('$ref' in x for x in slots.values())==minimum
    assert sum('MainProposal' in json.dumps(x) for x in slots.values())==maximum
    assert 'arrival and departure' in contract.instructions
    assert 'return infeasible' in contract.instructions
    assert set(contract.schema['properties'])=={'status','explanation','warnings','days'}

@pytest.mark.parametrize('mutation',['blank_evening','missing_main','zero_main','negative_gap','midnight','absolute_time','fixed_time','extra_day','missing_day','duplicate_id','warning_blank','too_many_warnings'])
def test_private_contract_rejects_without_repair(payload,wire,mutation):
    contract=GenerationContract(TripPreferences(**payload));day=wire['days']['day_1']
    if mutation=='blank_evening':day['evening']=' '
    if mutation=='missing_main':day['entries'].pop('entry_2')
    if mutation=='zero_main':day['entries'].update(entry_2=None,entry_4=None)
    if mutation=='negative_gap':day['entries']['entry_4']['gapBeforeMinutes']=-30
    if mutation=='midnight':day['dayStart']='23:45'
    if mutation=='absolute_time':day['entries']['entry_2']['startTime']='08:00'
    if mutation=='fixed_time':day['entries']['entry_2']['fixedTime']=True
    if mutation=='extra_day':wire['days']['day_99']=deepcopy(day)
    if mutation=='missing_day':wire['days'].pop('day_1')
    if mutation=='duplicate_id':day['entries']['entry_4']['id']=day['entries']['entry_2']['id']
    if mutation=='warning_blank':wire['warnings']['verificationWarning']=''
    if mutation=='too_many_warnings':wire['warnings']['additionalWarnings']=['Extra']*7
    original=deepcopy(wire)
    with pytest.raises(RecommendationError):validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert wire==original

def test_nonempty_narratives_and_request_order_not_json_property_order(payload,wire):
    contract=GenerationContract(TripPreferences(**payload));wire['days']=dict(reversed(list(wire['days'].items())))
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [d.date for d in result.days]==contract.dates
    for day in result.days:
        assert all(getattr(day,n).strip() for n in contract.narratives)
        assert day.mainActivityCount==2
        assert [(a.startTime,a.durationMinutes) for a in day.activities]==[('09:00',90),('14:00',60)]
    assert result.warnings[-1]==SCHEDULE_NOTICE

def test_infeasible_never_fills_missing_activities(payload,wire):
    contract=GenerationContract(TripPreferences(**payload))
    wire.update(status='infeasible',days={key:None for key in wire['days']})
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert result.days==[] and result.status=='infeasible'
    assert SCHEDULE_NOTICE not in result.warnings

def test_mixed_support_sequence_and_reversed_entry_keys(payload,wire):
    contract=GenerationContract(TripPreferences(**payload));day=wire['days']['day_1']
    template=deepcopy(day['entries']['entry_2']);day['dayStart']='08:00'
    day['entries']['entry_1']={**template,'id':'meal','kind':'meal','durationMinutes':30,'gapBeforeMinutes':0}
    day['entries']['entry_2']['gapBeforeMinutes']=30
    day['entries']['entry_3']={**template,'id':'transfer','kind':'transfer','durationMinutes':30,'gapBeforeMinutes':15}
    day['entries']['entry_4']['gapBeforeMinutes']=45
    day['entries']['entry_5']={**template,'id':'rest','kind':'rest','durationMinutes':30,'gapBeforeMinutes':0}
    day['entries']=dict(reversed(list(day['entries'].items())))
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [(a.kind,a.startTime) for a in result.days[0].activities]==[('meal','08:00'),('main','09:00'),('transfer','10:45'),('main','12:00'),('rest','13:00')]

@pytest.mark.parametrize('pace',['relaxed','fast'])
def test_other_paces_accept_complete_proposals(payload,wire,pace):
    p=TripPreferences(**{**payload,'travelPace':pace});contract=GenerationContract(p)
    if pace=='fast':
        for day in wire['days'].values():day['entries']['entry_6']={**day['entries']['entry_4'],'id':'third','gapBeforeMinutes':0}
    result=validate_itinerary(contract.decode(wire),p,'fixture','fixture')
    assert all(d.mainActivityCount==(3 if pace=='fast' else 2) for d in result.days)

def test_zero_gaps_and_exact_midnight_end(payload,wire):
    for day in wire['days'].values():
        day['dayStart']='21:30';day['entries']['entry_2']['gapBeforeMinutes']=0;day['entries']['entry_4']['gapBeforeMinutes']=0
    result=validate_itinerary(GenerationContract(TripPreferences(**payload)).decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [(a.startTime,a.durationMinutes) for a in result.days[0].activities]==[('21:30',90),('23:00',60)]

@pytest.mark.parametrize('mutation',['duration14','duration241','duration_bool','coordinate_pair'])
def test_original_activity_boundaries_preserved(payload,wire,mutation):
    entry=wire['days']['day_1']['entries']['entry_2']
    if mutation=='coordinate_pair':entry['latitude']=12.0;entry['longitude']=None
    else:entry['durationMinutes']={'duration14':14,'duration241':241,'duration_bool':True}[mutation]
    with pytest.raises(RecommendationError):validate_itinerary(GenerationContract(TripPreferences(**payload)).decode(wire),TripPreferences(**payload),'fixture','fixture')

def test_representative_real_fastapi_serialization_and_mounted_component(payload,wire):
    calls=[]
    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(wire)}}]})
    provider=GroqProvider('synthetic-offline-key',transport=httpx.MockTransport(transport))
    with TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(provider))) as client:
        response=client.post('/api/itineraries/generate',json=payload)
    assert response.status_code==200 and len(calls)==1
    assert calls[0]['response_format']['json_schema']['strict'] is True
    assert calls[0]['model']=='openai/gpt-oss-20b' and calls[0]['max_completion_tokens']==4096
    assert 'previous end + gapBeforeMinutes' in calls[0]['messages'][0]['content']
    run=subprocess.run(['node','frontend/test/renderGeneratedPlan.mjs'],input=json.dumps({'result':response.json(),'preferences':payload}),text=True,capture_output=True,timeout=30,cwd=Path(__file__).resolve().parents[2])
    assert run.returncode==0,'Mounted render failed'
    assert json.loads(run.stdout)['days']==len(wire['days'])
