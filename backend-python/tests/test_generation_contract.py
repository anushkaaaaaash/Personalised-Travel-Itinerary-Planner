from test_openai import envelope
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
from app.openai import OpenAIProvider,strict_schema
from app.itineraries import ItineraryDay,ItineraryPayload,ItineraryService,validate_itinerary
from app.models import TripPreferences
from app.generation_contract import GenerationContract,SCHEDULE_NOTICE
from app.recommendations import RecommendationError
from app.refinement_contract import check_shape
from test_itineraries import generated,NoStorage
from generation_fixture import private_proposal

@pytest.fixture
def wire(payload,generated):
    data=deepcopy(generated);data['warnings']={'verificationWarning':'Synthetic estimates require verification.','additionalWarnings':[]}
    return private_proposal(data,payload)

def entries(day):
    return sorted([*day['requiredMainActivities'].values(),*day['activities']],key=lambda a:a['sequence'])

def regroup(day,ordered):
    for i,entry in enumerate(ordered):entry['sequence']=i+1
    required=[a for a in ordered if a['kind']=='main'][:2]
    day['requiredMainActivities']={f'main_{i+1}':a for i,a in enumerate(required)}
    day['activities']=[a for a in ordered if not any(a is main for main in required)]

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
def test_consistent_complete_array_contract_and_pace_policy(payload,pace,minimum,maximum):
    contract=GenerationContract(TripPreferences(**{**payload,'travelPace':pace}))
    assert (contract.minimum,contract.maximum)==(minimum,maximum)
    assert contract.schema['properties']['days']['type']=='array'
    assert contract.schema['$defs']['GenerationDay']['properties']['activities']['type']=='array'
    required=contract.schema['$defs']['GenerationDay']['properties']['requiredMainActivities']
    assert set(required['required'])=={f'main_{i+1}' for i in range(minimum)}
    assert contract.schema['$defs']['RequiredMainProposal']['properties']['kind']['enum']==['main']
    assert 'arrival and departure' in contract.instructions
    assert 'return status infeasible' in contract.instructions
    assert 'days: []' in contract.instructions and 'Never omit days' in contract.instructions
    assert list(contract.schema['properties'])[0]=='days'
    assert set(contract.schema['properties'])=={'status','explanation','warnings','days'}

@pytest.mark.parametrize('mutation',['blank_evening','missing_main','zero_main','negative_gap','midnight','absolute_time','fixed_time','extra_day','missing_day','duplicate_id','warning_blank','too_many_warnings'])
def test_private_contract_rejects_without_repair(payload,wire,mutation):
    contract=GenerationContract(TripPreferences(**payload));day=wire['days'][0]
    if mutation=='blank_evening':day['evening']=' '
    if mutation=='missing_main':day['requiredMainActivities'].pop('main_2')
    if mutation=='zero_main':
        for entry in entries(day):entry['kind']='rest'
    if mutation=='negative_gap':entries(day)[1]['gapBeforeMinutes']=-30
    if mutation=='midnight':day['dayStart']='23:45'
    if mutation=='absolute_time':entries(day)[0]['startTime']='08:00'
    if mutation=='fixed_time':entries(day)[0]['fixedTime']=True
    if mutation=='extra_day':wire['days'].append(deepcopy(day))
    if mutation=='missing_day':wire['days'].pop()
    if mutation=='duplicate_id':entries(day)[1]['id']=entries(day)[0]['id']
    if mutation=='warning_blank':wire['warnings']['verificationWarning']=''
    if mutation=='too_many_warnings':wire['warnings']['additionalWarnings']=['Extra']*7
    original=deepcopy(wire)
    with pytest.raises(RecommendationError):validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert wire==original

def test_nonempty_narratives_and_json_property_order_does_not_change_array_order(payload,wire):
    contract=GenerationContract(TripPreferences(**payload));wire=dict(reversed(list(wire.items())))
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [d.date for d in result.days]==contract.dates
    for day in result.days:
        assert all(getattr(day,n).strip() for n in contract.narratives)
        assert day.mainActivityCount==2
        assert [(a.startTime,a.durationMinutes) for a in day.activities]==[('09:00',90),('14:00',60)]
    assert result.warnings[-1]==SCHEDULE_NOTICE

def test_infeasible_never_fills_missing_activities(payload,wire):
    contract=GenerationContract(TripPreferences(**payload))
    wire.update(status='infeasible',days=[])
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert result.days==[] and result.status=='infeasible'
    assert SCHEDULE_NOTICE not in result.warnings

def test_breakfast_transfer_before_main_and_support_after_last_main(payload,wire):
    contract=GenerationContract(TripPreferences(**payload));day=wire['days'][0]
    first,second=entries(day);template=deepcopy(first);day['dayStart']='08:00'
    first['gapBeforeMinutes']=15;second['gapBeforeMinutes']=45
    ordered=[{**template,'id':'meal','kind':'meal','durationMinutes':30,'gapBeforeMinutes':0},
        {**template,'id':'transfer','kind':'transfer','durationMinutes':30,'gapBeforeMinutes':15},
        first,second,{**template,'id':'rest','kind':'rest','durationMinutes':30,'gapBeforeMinutes':0}]
    regroup(day,[dict(reversed(list(entry.items()))) for entry in ordered])
    result=validate_itinerary(contract.decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [(a.kind,a.startTime) for a in result.days[0].activities]==[('meal','08:00'),('transfer','08:45'),('main','09:30'),('main','11:45'),('rest','12:45')]

@pytest.mark.parametrize('pace',['relaxed','fast'])
def test_other_paces_accept_complete_proposals(payload,wire,pace):
    p=TripPreferences(**{**payload,'travelPace':pace});contract=GenerationContract(p)
    for day in wire['days']:
        if pace=='fast':day['requiredMainActivities']['main_3']={**entries(day)[1],'id':'third','gapBeforeMinutes':0,'sequence':3}
        else:day['activities'].append(day['requiredMainActivities'].pop('main_2'))
    result=validate_itinerary(contract.decode(wire),p,'fixture','fixture')
    assert all(d.mainActivityCount==(3 if pace=='fast' else 2) for d in result.days)

def test_zero_gaps_and_exact_midnight_end(payload,wire):
    for day in wire['days']:
        day['dayStart']='21:30'
        for entry in entries(day):entry['gapBeforeMinutes']=0
    result=validate_itinerary(GenerationContract(TripPreferences(**payload)).decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert [(a.startTime,a.durationMinutes) for a in result.days[0].activities]==[('21:30',90),('23:00',60)]

@pytest.mark.parametrize('mutation',['duration14','duration241','duration_bool','coordinate_pair'])
def test_original_activity_boundaries_preserved(payload,wire,mutation):
    entry=entries(wire['days'][0])[0]
    if mutation=='coordinate_pair':entry['latitude']=12.0;entry['longitude']=None
    else:entry['durationMinutes']={'duration14':14,'duration241':241,'duration_bool':True}[mutation]
    with pytest.raises(RecommendationError):validate_itinerary(GenerationContract(TripPreferences(**payload)).decode(wire),TripPreferences(**payload),'fixture','fixture')

@pytest.mark.parametrize('status',['planned','infeasible'])
def test_captured_metadata_only_shape_is_never_completed_or_accepted(payload,status):
    captured=json.loads((Path(__file__).parent/'fixtures/captured-missing-days-shape.json').read_text())
    raw=captured['failedGeneration'];raw['status']=status;before=deepcopy(raw)
    with pytest.raises(RecommendationError):GenerationContract(TripPreferences(**payload)).decode(raw)
    assert raw==before and 'days' not in raw

@pytest.mark.parametrize('status',[200,400])
def test_captured_shape_through_actual_provider_route_rejected_once(payload,status):
    captured=json.loads((Path(__file__).parent/'fixtures/captured-missing-days-shape.json').read_text())
    raw=captured['failedGeneration'];calls=[]
    def transport(request):
        calls.append(json.loads(request.content))
        body=(envelope(json.dumps(raw))
            if status==200 else {'error':{'code':'json_validate_failed','type':'invalid_request_error','message':"missing required properties: 'days'",'failed_generation':json.dumps(raw)}})
        return httpx.Response(status,json=body)
    with TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(OpenAIProvider('synthetic-offline-key',transport=httpx.MockTransport(transport))))) as client:
        response=client.post('/api/itineraries/generate',json=payload)
    assert response.status_code==502 and len(calls)==1
    assert response.json()['error']['code']==('AI_SCHEMA_REJECTED' if status==400 else 'AI_INVALID_RESPONSE')

@pytest.mark.parametrize('mutation',['reverse','duplicate','unknown','nine_entries','too_many_main'])
def test_flexible_arrays_do_not_relax_coverage_or_counts(payload,wire,mutation):
    if mutation=='reverse':wire['days'].reverse()
    if mutation=='duplicate':wire['days'][1]['date']=wire['days'][0]['date']
    if mutation=='unknown':wire['days'][0]['date']='2099-01-01'
    if mutation in ('nine_entries','too_many_main'):
        first=deepcopy(entries(wire['days'][0])[0])
        regroup(wire['days'][0],[{**first,'id':f'item-{i}','durationMinutes':15,'gapBeforeMinutes':0} for i in range(9 if mutation=='nine_entries' else 4)])
    with pytest.raises(RecommendationError):GenerationContract(TripPreferences(**payload)).decode(wire)

def test_prompt_field_manifest_matches_schema_and_strict_structure(payload):
    contract=GenerationContract(TripPreferences(**payload))
    for group in (contract.schema['properties'],contract.schema['$defs']['GenerationDay']['properties'],contract.schema['$defs']['ActivityProposal']['properties']):
        assert all(name in contract.instructions for name in group)
    def walk(node):
        if not isinstance(node,dict):return
        if node.get('type')=='object':
            assert node['additionalProperties'] is False
            assert set(node['required'])==set(node['properties'])
        if '$ref' in node:assert node['$ref'].split('/')[-1] in contract.shape['$defs']
        for value in node.values():
            if isinstance(value,dict):walk(value)
            elif isinstance(value,list):
                for child in value:walk(child)
    walk(contract.shape)

@pytest.mark.parametrize('main_count',[0,1])
def test_actual_day1_insufficient_main_bounds_are_now_structural_rejections(payload,wire,main_count):
    evidence=json.loads((Path(__file__).parent/'fixtures/captured-day1-pace-evidence.json').read_text())
    assert main_count in evidence['day1']['mainCountPossibleValues']
    contract=GenerationContract(TripPreferences(**payload));day=wire['days'][0]
    template=deepcopy(entries(day)[0])
    # Unknown prose/kinds use explicit synthetic substitutions. This never repairs
    # or purports to replay the actual discarded model prose.
    ordered=[{**template,'id':f'synthetic-{i}','kind':kind,'sequence':i+1,'durationMinutes':30,'gapBeforeMinutes':0}
             for i,kind in enumerate(['accommodation','main' if main_count else 'meal','rest'])]
    day['requiredMainActivities']={f'main_{i+1}':e for i,e in enumerate(a for a in ordered if a['kind']=='main')}
    day['activities']=[a for a in ordered if a['kind']!='main']
    before=deepcopy(wire)
    with pytest.raises(ValueError):check_shape(wire,contract.shape,contract.shape)
    with pytest.raises(RecommendationError):contract.decode(wire)
    assert wire==before

@pytest.mark.parametrize('mutation',['null_main','meal_as_main','duplicate_sequence','gapped_sequence','missing_sequence'])
def test_required_main_content_and_explicit_order_cannot_be_bypassed(payload,wire,mutation):
    day=wire['days'][0];main=day['requiredMainActivities']['main_2']
    if mutation=='null_main':day['requiredMainActivities']['main_2']=None
    if mutation=='meal_as_main':main['kind']='meal'
    if mutation=='duplicate_sequence':main['sequence']=1
    if mutation=='gapped_sequence':main['sequence']=3
    if mutation=='missing_sequence':del main['sequence']
    with pytest.raises(RecommendationError):GenerationContract(TripPreferences(**payload)).decode(wire)

def test_order_is_proposed_by_sequence_not_container_or_key_order(payload,wire):
    for day in wire['days']:
        day['requiredMainActivities']=dict(reversed(list(day['requiredMainActivities'].items())))
    result=validate_itinerary(GenerationContract(TripPreferences(**payload)).decode(wire),TripPreferences(**payload),'fixture','fixture')
    assert all([(a.startTime,a.durationMinutes) for a in d.activities]==[('09:00',90),('14:00',60)] for d in result.days)

def test_representative_real_fastapi_serialization_and_mounted_component(payload,wire):
    calls=[]
    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json=envelope(json.dumps(wire)))
    provider=OpenAIProvider('synthetic-offline-key',transport=httpx.MockTransport(transport))
    with TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(provider))) as client:
        response=client.post('/api/itineraries/generate',json=payload)
    assert response.status_code==200 and len(calls)==1
    assert calls[0]['text']['format']['strict'] is True
    assert calls[0]['model']=='gpt-6-luna' and calls[0]['max_output_tokens']==32768
    assert 'previous end + gapBeforeMinutes' in calls[0]['input'][0]['content']
    run=subprocess.run(['node','frontend/test/renderGeneratedPlan.mjs'],input=json.dumps({'result':response.json(),'preferences':payload}),text=True,capture_output=True,timeout=30,cwd=Path(__file__).resolve().parents[2])
    assert run.returncode==0,'Mounted render failed'
    assert json.loads(run.stdout)['days']==len(wire['days'])
