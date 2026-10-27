from test_openai import envelope
import copy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.openai import OpenAIProvider
from app.itineraries import ItineraryService, RefinementRequest, validate_itinerary
from app.models import TripPreferences
from app.refinement_contract import RefinementContract
from test_itineraries import generated, NoStorage


def request_for(payload,generated,cap=2,target=None):
    previous=validate_itinerary(generated,TripPreferences(**payload),'Earlier','fixture')
    return RefinementRequest(preferences=TripPreferences(**payload),previous=previous,
        feedback='Two main activities, preserve practical requirements.',vibe='relaxed',
        maxMainActivitiesPerDay=cap,targetDate=target)


def proposal_for(request):
    days={}
    for i,day in enumerate(d for d in request.previous.days if request.targetDate is None or d.date==request.targetDate):
        value={k:v for k,v in day.model_dump().items() if k not in {'date','activities','mainActivityCount'}}
        available=[a.model_dump() for a in day.activities if not a.fixedTime and a.kind=='main']
        fixed_main=sum(a.fixedTime and a.kind=='main' for a in day.activities)
        value['mainSlots']={f'main_{j+1}':available[j] if j<len(available) else None
            for j in range(request.maxMainActivitiesPerDay-fixed_main)}
        days[f'day_{i+1}']=value
    return {'status':'planned','explanation':'A revised estimate.','verificationWarning':'Unverified hours and prices.','days':days}


def invoke(request,proposal,finish='stop',status=200):
    calls=[]
    def handler(req):
        body=json.loads(req.content); calls.append(body)
        assert body['model']=='gpt-6-luna'
        assert body['max_output_tokens']==32768 and body['stream'] is False
        schema=body['text']['format']
        assert schema['strict'] is True
        assert schema['schema']['additionalProperties'] is False
        return httpx.Response(status,json=envelope(proposal if isinstance(proposal,str) else json.dumps(proposal),reason=finish))
    service=ItineraryService(OpenAIProvider('fake-offline-test-key',transport=httpx.MockTransport(handler)))
    response=TestClient(create_app(NoStorage(),itinerary_service=service)).post('/api/itineraries/refine',json=request.model_dump())
    return response,calls


def test_private_valid_whole_contract_and_single_invocation(payload,generated):
    request=request_for(payload,generated)
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==200,response.text
    result=response.json()
    assert len(calls)==1
    assert result['vibe']=='relaxed' and result['travelPace']=='balanced'
    assert result['refinementSummary']['scope']=='whole'
    assert [d['mainActivityCount'] for d in result['days']]==[2]*len(generated['days'])
    schema=calls[0]['text']['format']['schema']
    assert schema['$defs']['NewMainActivity']['properties']['durationMinutes']['enum']==list(range(15,241))
    planned=schema['properties']['days']['anyOf'][0]
    assert set(planned['properties'])=={f'day_{i+1}' for i in range(len(generated['days']))}
    assert all(d['required']==list(d['properties']) and d['additionalProperties'] is False for d in planned['properties'].values())
    assert 'server' in calls[0]['input'][0]['content']


@pytest.mark.parametrize('mutation,reason',[
    ('extra_day','FORMAT_SCHEMA'),('missing_day','FORMAT_SCHEMA'),('extra_main','FORMAT_SCHEMA'),
    ('missing_main','FORMAT_SCHEMA'),('null_required','FORMAT_SCHEMA'),('unknown_field','FORMAT_SCHEMA'),
    ('overlap','TIMELINE'),('reverse','TIMELINE'),('missing_narrative','FORMAT_SCHEMA'),
    ('bad_kind','FORMAT_SCHEMA'),('fixed_new','FORMAT_SCHEMA'),('duplicate_id','TIMELINE'),
    ('budget','BUDGET'),('no_days','FORMAT_SCHEMA')])
def test_private_rejects_bad_shape_and_semantics(payload,generated,mutation,reason):
    request=request_for(payload,generated); data=proposal_for(request)
    d=data['days']['day_1']; slots=d['mainSlots']
    if mutation=='extra_day': data['days']['day_99']=copy.deepcopy(d)
    if mutation=='missing_day': del data['days']['day_1']
    if mutation=='extra_main': slots['main_3']=copy.deepcopy(slots['main_1'])
    if mutation=='missing_main': del slots['main_2']
    if mutation=='null_required': slots['main_2']=None
    if mutation=='unknown_field': d['PRIVATE_FIELD']='PRIVATE_VALUE'
    if mutation=='overlap': slots['main_2']['startTime']='09:30'
    if mutation=='reverse': slots['main_1'],slots['main_2']=slots['main_2'],slots['main_1']
    if mutation=='missing_narrative': del d['dining']
    if mutation=='bad_kind': slots['main_1']['kind']='rest'
    if mutation=='fixed_new': slots['main_1']['fixedTime']=True
    if mutation=='duplicate_id': slots['main_2']['id']=slots['main_1']['id']
    if mutation=='budget': d['costs']['activities']=999999
    if mutation=='no_days': data['days']=None
    response,calls=invoke(request,data)
    assert response.status_code==502,response.text
    assert response.json()['error']['reason']==reason
    assert len(calls)==1 and 'PRIVATE_VALUE' not in response.text


def test_private_relaxed_nullable_slot(payload,generated):
    payload['travelPace']='relaxed'; generated['travelPace']='relaxed'
    request=request_for(payload,generated); data=proposal_for(request)
    for day in data['days'].values(): day['mainSlots']['main_2']=None
    response,calls=invoke(request,data)
    assert response.status_code==200,response.text
    assert all(d['mainActivityCount']==1 for d in response.json()['days'])
    assert len(calls)==1


def test_private_fixed_commitment_preserved_exactly(payload,generated):
    fixed=generated['days'][0]['activities'][0]
    fixed.update(fixedTime=True,notes='Preserve exact commitment notes',latitude=12.0,longitude=13.0)
    request=request_for(payload,generated); before=request.previous.model_dump()
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==200,response.text
    actual=response.json()['days'][0]['activities'][0]
    assert actual==before['days'][0]['activities'][0]
    assert request.previous.model_dump()==before and len(calls)==1
    schema=calls[0]['text']['format']['schema']
    slots=schema['properties']['days']['anyOf'][0]['properties']['day_1']['properties']['mainSlots']
    assert set(slots['properties'])=={'main_1'}


def test_private_fixed_overlap_rejected(payload,generated):
    generated['days'][0]['activities'][0]['fixedTime']=True
    request=request_for(payload,generated); data=proposal_for(request)
    data['days']['day_1']['mainSlots']['main_1']['startTime']='09:30'
    response,calls=invoke(request,data)
    assert response.status_code==502 and response.json()['error']['reason']=='TIMELINE'
    assert len(calls)==1


def test_private_fixed_support_preserved_and_unknown_rejected(payload,generated):
    generated['days'][0]['activities'].append(dict(id='rest',title='Fixed rest',startTime='17:00',durationMinutes=30,
        notes='Required break',latitude=None,longitude=None,fixedTime=True,kind='rest'))
    request=request_for(payload,generated)
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==200,response.text
    assert response.json()['days'][0]['activities'][-1]==request.previous.days[0].activities[-1].model_dump()
    generated['days'][0]['activities'][-1]['kind']='unknown'
    request=request_for(payload,generated)
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==422 and calls==[]


def test_capped_target_day_uses_public_path_and_preserves_others(payload,generated):
    request=request_for(payload,generated,target=generated['days'][1]['date'])
    proposal=copy.deepcopy(generated); proposal['vibe']='relaxed'
    proposal['warnings']={'verificationWarning':proposal['warnings'][0],'additionalWarnings':proposal['warnings'][1:]}
    proposal['days'][1]['morning']='Updated target visit'
    response,calls=invoke(request,proposal)
    assert response.status_code==200,response.text
    result=response.json()
    schema=calls[0]['text']['format']['schema']
    assert schema['properties']['days']['type']=='array'
    assert result['days'][1]['morning']=='Updated target visit'
    for i,day in enumerate(request.previous.days):
        if i!=1: assert result['days'][i]==day.model_dump()
    assert len(calls)==1


@pytest.mark.parametrize('proposal,finish,status,code',[
    ('not JSON','stop',200,'AI_INVALID_RESPONSE'),
    ('{"status":"planned","status":"infeasible"}','stop',200,'AI_INVALID_RESPONSE'),
    ('{}','length',200,'AI_OUTPUT_TRUNCATED'),('{}','stop',429,'AI_RATE_LIMITED'),
    ('{}','stop',500,'AI_PROVIDER_FAILED')])
def test_private_format_truncation_provider_failure_once(payload,generated,proposal,finish,status,code):
    response,calls=invoke(request_for(payload,generated),proposal,finish,status)
    assert response.json()['error']['code']==code and len(calls)==1


def test_private_infeasible_preserves_previous(payload,generated):
    request=request_for(payload,generated)
    before=request.previous.model_dump()
    response,calls=invoke(request,{'status':'infeasible','explanation':'Cannot fit fixed commitments.',
        'verificationWarning':'Unverified.','days':None})
    assert response.status_code==422 and len(calls)==1
    assert request.previous.model_dump()==before



def test_private_slot_object_key_order_is_not_timeline_order(payload,generated):
    request=request_for(payload,generated); proposal=proposal_for(request)
    for day in proposal['days'].values():
        day['mainSlots']=dict(reversed(list(day['mainSlots'].items())))
    response,calls=invoke(request,proposal)
    assert response.status_code==200,response.text
    assert len(calls)==1


def test_private_schema_only_documented_structural_subset(payload,generated):
    from app.openai import strict_schema
    schema=strict_schema(RefinementContract(request_for(payload,generated)).schema)
    assert set(schema['$defs'])=={'DayCosts','NewMainActivity'}
    allowed={'type','title','description','enum','anyOf','$ref','$defs','items','properties','required','additionalProperties'}
    def visit(node):
        assert set(node)<=allowed
        if node.get('type')=='object':
            assert node['additionalProperties'] is False
            assert set(node['required'])==set(node['properties'])
        for child in node.get('properties',{}).values(): visit(child)
        for child in node.get('$defs',{}).values(): visit(child)
        for child in node.get('anyOf',[]): visit(child)
        if 'items' in node: visit(node['items'])
    visit(schema)



def test_private_prompt_has_one_output_contract_and_preserves_context(payload,generated):
    request=request_for(payload,generated)
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==200 and len(calls)==1
    prompt=calls[0]['input'][0]['content']
    assert 'ONLY output shape' in prompt and 'including mainSlots' in prompt
    assert 'Return a complete payload' not in prompt
    assert 'an empty days array' not in prompt
    assert 'one short sentence per narrative field' in prompt
    assert 'whole-group daily estimates' in prompt and '15-240 minutes' in prompt
    context=calls[0]['input'][1]['content']
    assert request.feedback in context and request.previous.days[0].activities[0].title in context


@pytest.mark.parametrize('value',[None,'',' ','\t',[],['Unverified']])
def test_private_warning_invalid_rejected(payload,generated,value):
    request=request_for(payload,generated); proposal=proposal_for(request)
    proposal['verificationWarning']=value
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1
    assert response.json()['error']['reason']=='FORMAT_SCHEMA'


def test_private_warning_is_model_authored_and_mapped_without_replacement(payload,generated):
    request=request_for(payload,generated); proposal=proposal_for(request)
    warning='Flight availability and venue access are unverified; check directly.'
    proposal['verificationWarning']=warning
    response,calls=invoke(request,proposal)
    assert response.status_code==200,response.text
    assert response.json()['warnings']==[warning] and len(calls)==1


@pytest.mark.parametrize('field',['status','explanation','verificationWarning','days'])
def test_private_every_root_field_required(payload,generated,field):
    request=request_for(payload,generated); proposal=proposal_for(request); del proposal[field]
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1


@pytest.mark.parametrize('field',['morning','afternoon','evening','dining','dietaryNotes','mobilityNotes',
    'transitAndRest','interestTags','costs','mainSlots'])
def test_private_every_day_field_required(payload,generated,field):
    request=request_for(payload,generated); proposal=proposal_for(request); del proposal['days']['day_1'][field]
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1


@pytest.mark.parametrize('field',['morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest'])
@pytest.mark.parametrize('value',['',' '])
def test_private_day_minimum_text_checks(payload,generated,field,value):
    request=request_for(payload,generated); proposal=proposal_for(request); proposal['days']['day_1'][field]=value
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1


@pytest.mark.parametrize('field',['id','title','notes'])
@pytest.mark.parametrize('value',['',' '])
def test_private_activity_minimum_text_checks(payload,generated,field,value):
    request=request_for(payload,generated); proposal=proposal_for(request)
    proposal['days']['day_1']['mainSlots']['main_1'][field]=value
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1


@pytest.mark.parametrize('value',['',' '])
def test_private_explanation_minimum(payload,generated,value):
    request=request_for(payload,generated); proposal=proposal_for(request); proposal['explanation']=value
    response,calls=invoke(request,proposal)
    assert response.status_code==502 and len(calls)==1


def test_private_provider_descriptions_cover_public_minima(payload,generated):
    contract=RefinementContract(request_for(payload,generated))
    schema=contract.schema
    assert 'Minimum characters: 1' in schema['properties']['explanation']['description']
    day=schema['properties']['days']['anyOf'][0]['properties']['day_1']['properties']
    for name in ['morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest']:
        assert 'Minimum characters: 1' in day[name]['description']
    for name in ['id','title','notes']:
        assert 'Minimum characters: 1' in schema['$defs']['NewMainActivity']['properties'][name]['description']
    assert 'verificationWarning' in schema['required'] and 'warnings' not in schema['properties']


@pytest.mark.parametrize('pace,bounds',[('relaxed','1-2'),('balanced','2-3')])
def test_private_prompt_uses_requested_pace(payload,generated,pace,bounds):
    payload['travelPace']=generated['travelPace']=pace
    request=request_for(payload,generated)
    response,calls=invoke(request,proposal_for(request))
    assert response.status_code==200,response.text
    assert f'Original {pace} pace requires {bounds}' in calls[0]['input'][0]['content']


def test_uncapped_whole_refinement_still_uses_public_contract(payload,generated):
    request=request_for(payload,generated,cap=None)
    proposal=copy.deepcopy(generated); proposal['vibe']='relaxed'
    proposal['warnings']={'verificationWarning':proposal['warnings'][0],'additionalWarnings':proposal['warnings'][1:]}
    response,calls=invoke(request,proposal)
    assert response.status_code==200,response.text
    assert len(calls)==1
    assert calls[0]['text']['format']['schema']['properties']['days']['type']=='array'
    assert response.json()['refinementSummary']['scope']=='whole'
