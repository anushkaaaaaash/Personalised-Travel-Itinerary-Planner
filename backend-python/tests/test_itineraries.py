import asyncio
import copy
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.itineraries import ItineraryService
from app.recommendations import ProviderRefusal

class Provider:
    name, model = 'Test only', 'fixture'
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []
    async def generate(self, messages, schema):
        self.calls.append((messages, schema))
        if self.error:
            raise self.error
        return self.result

class NoStorage:
    async def save(self, *args):
        pytest.fail('Generation must never save')
    async def list(self, *args):
        pytest.fail('Generation must never read private history')

@pytest.fixture
def generated(payload):
    count = (date.fromisoformat(payload['endDate']) - date.fromisoformat(payload['startDate'])).days + 1
    return {'status':'planned', 'destination':payload['destination'],'currency':payload['currency'],
        'travelStyle':payload.get('travelStyle',''),'travelPace':payload['travelPace'],
        'explanation':'A cautious estimated plan.', 'warnings':['Prices and suitability are unverified.'],
        'days':[{'date':(date.fromisoformat(payload['startDate'])+timedelta(days=i)).isoformat(),
            'morning':'Visit museum','afternoon':'Rest and nature walk','evening':'Explore local culture',
            'dining':'Local restaurant','dietaryNotes':'No dietary needs supplied',
            'mobilityNotes':'No mobility needs supplied','transitAndRest':'Allow an hour for travel and rest',
            'mainActivityCount':2,'interestTags':['culture'],
            'activities':[{'id':'museum','title':'Museum','startTime':'09:00','durationMinutes':90,'kind':'main','notes':'Allow breaks','latitude':None,'longitude':None,'fixedTime':False},{'id':'walk','title':'Cultural walk','startTime':'14:00','durationMinutes':60,'kind':'main','notes':'Rest as needed','latitude':None,'longitude':None,'fixedTime':False}],
            'costs':{'accommodation':100,'meals':20,'localTransport':10,'activities':10,'departureTravel':20}}
            for i in range(count)]}

def call(payload, provider):
    return TestClient(create_app(NoStorage(), itinerary_service=ItineraryService(provider))).post('/api/itineraries/generate', json=payload)

def test_generation(payload, generated):
    provider=Provider(generated)
    response=call(payload,provider)
    assert response.status_code == 200, response.text
    result=response.json()
    assert result['estimatedTotalGroupCost']==960
    assert result['remainingBudget']==1540
    assert result['saved'] is False and result['source']=='ai'
    assert len(provider.calls)==1
    assert 'WHOLE GROUP' in provider.calls[0][0][0]['content']

def test_generation_vibe_schema_is_null_without_mutating_public_contract(payload, generated):
    from app.itineraries import ItineraryPayload
    original=ItineraryPayload.model_json_schema()
    assert 'anyOf' in original['properties']['vibe']
    provider=Provider(generated)
    assert call(payload,provider).status_code==200
    assert provider.calls[0][1]['properties']['vibe']=={'type':'null'}
    assert ItineraryPayload.model_json_schema()==original

@pytest.mark.parametrize('vibe',['relaxed','adventure','luxury','budget'])
def test_generation_does_not_accept_unrequested_vibe(payload,generated,vibe):
    generated['vibe']=vibe
    response=call(payload,Provider(generated))
    assert response.status_code==502
    assert response.json()['error']['reason']=='VIBE_MISMATCH'

@pytest.mark.parametrize('vibe',[None,'relaxed','adventure','luxury','budget'])
def test_refinement_schema_matches_exact_requested_vibe(payload,generated,vibe):
    from app.itineraries import RefinementRequest,validate_itinerary
    from app.models import TripPreferences
    preferences=TripPreferences.model_validate(payload)
    previous=validate_itinerary(generated,preferences,'fixture','fixture')
    request=RefinementRequest(preferences=preferences,previous=previous,feedback='Keep all original constraints',vibe=vibe)
    result=copy.deepcopy(generated);result['vibe']=vibe
    provider=Provider(result)
    response=asyncio.run(ItineraryService(provider).refine(request))
    assert response.vibe==vibe and len(provider.calls)==1
    assert provider.calls[0][1]['properties']['vibe']==({'type':'null'} if vibe is None else {'type':'string','enum':[vibe]})

def test_infeasible(payload, generated):
    generated.update(status='infeasible',days=[],explanation='Travel costs alone exceed the budget.')
    response=call(payload,Provider(generated))
    assert response.status_code==200
    assert response.json()['estimatedTotalGroupCost'] is None

@pytest.mark.parametrize('mutation', ['missing','duplicate','order','currency','destination','pace','style','negative','budget','nan','interest','activityCount','infeasibleDays','warnings','unknown'])
def test_invalid_output(payload, generated, mutation):
    if mutation=='missing': generated['days'].pop()
    if mutation=='duplicate': generated['days'][1]['date']=generated['days'][0]['date']
    if mutation=='order': generated['days'].reverse()
    if mutation=='currency': generated['currency']='USD'
    if mutation=='destination': generated['destination']='Elsewhere'
    if mutation=='pace': generated['travelPace']='fast'
    if mutation=='style': generated['travelStyle']='luxury'
    if mutation=='negative': generated['days'][0]['costs']['meals']=-1
    if mutation=='budget': generated['days'][0]['costs']['meals']=999999
    if mutation=='nan': generated['days'][0]['costs']['meals']=float('nan')
    if mutation=='interest': generated['days'][0]['interestTags']=[]
    if mutation=='activityCount': generated['days'][0]['mainActivityCount']=4
    if mutation=='infeasibleDays': generated['status']='infeasible'
    if mutation=='warnings': generated['warnings']=[]
    if mutation=='unknown': generated['private']='secret'
    response=call(payload,Provider(generated))
    assert response.status_code==502
    assert response.json()['error']['code']=='AI_INVALID_RESPONSE'

@pytest.mark.parametrize('error,code,status', [(ProviderRefusal(),'AI_REFUSED',502),(TimeoutError(),'AI_TIMEOUT',504),(RuntimeError('secret'),'AI_PROVIDER_FAILED',502)])
def test_provider_errors(payload,error,code,status):
    provider=Provider(error=error)
    response=call(payload,provider)
    assert response.status_code==status
    assert response.json()['error']['code']==code
    assert 'secret' not in response.text
    assert len(provider.calls)==1

def test_duration_before_provider(payload):
    payload['endDate']='2026-11-30'
    provider=Provider()
    response=call(payload,provider)
    assert response.status_code==400
    assert response.json()['error']['code']=='ITINERARY_DURATION_UNSUPPORTED'
    assert provider.calls==[]

def test_bad_request_before_provider(payload):
    payload['budget']=-1
    provider=Provider()
    assert call(payload,provider).status_code==400
    assert provider.calls==[]

def test_default_unconfigured(payload):
    response=TestClient(create_app(NoStorage())).post('/api/itineraries/generate',json=payload)
    assert response.status_code==503

def refine_call(payload, generated, provider, target=None, feedback='Please include more rest', vibe=None):
    from app.itineraries import validate_itinerary
    from app.models import TripPreferences
    previous=validate_itinerary(generated,TripPreferences(**payload),'Earlier provider','earlier-model').model_dump()
    client=TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(provider)))
    return client.post('/api/itineraries/refine',json={'preferences':payload,'previous':previous,
        'targetDate':target,'feedback':feedback,'vibe':vibe}), previous

def test_target_refinement_preserves_every_other_day(payload,generated):
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['morning']='Unwanted unrelated change'
    proposal['days'][1]['morning']='Revised target museum visit'
    proposal['vibe']='relaxed'
    provider=Provider(proposal)
    response,previous=refine_call(payload,generated,provider,target=generated['days'][1]['date'],vibe='relaxed')
    assert response.status_code==200,response.text
    result=response.json()
    assert result['days'][1]['morning']=='Revised target museum visit'
    for i in [0,2,3,4,5]:
        assert result['days'][i]==previous['days'][i]
    assert result['vibe']=='relaxed'
    assert len(provider.calls)==1
    context=provider.calls[0][0][1]['content']
    assert 'Please include more rest' in context and 'Earlier provider' in context

def test_whole_refinement(payload,generated):
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['morning']='Whole-plan revision'
    response,_=refine_call(payload,generated,Provider(proposal))
    assert response.status_code==200
    assert response.json()['days'][0]['morning']=='Whole-plan revision'

@pytest.mark.parametrize('feedback', ['', ' ', 'x'*1001, 'bad\ncontrol'])
def test_feedback_bounds_before_provider(payload,generated,feedback):
    provider=Provider(generated)
    response,_=refine_call(payload,generated,provider,feedback=feedback)
    assert response.status_code==400
    assert not provider.calls

def test_refine_target_outside_plan_before_provider(payload,generated):
    provider=Provider(generated)
    response,_=refine_call(payload,generated,provider,target='2030-01-01')
    assert response.status_code==400 and not provider.calls

def test_target_infeasible_keeps_previous(payload,generated):
    proposal=copy.deepcopy(generated)
    proposal.update(status='infeasible',days=[],explanation='Cannot afford requested activity.')
    response,_=refine_call(payload,generated,Provider(proposal),target=generated['days'][0]['date'])
    assert response.status_code==422
    assert response.json()['error']['code']=='REFINEMENT_INFEASIBLE'

def test_target_new_costs_still_whole_budget_checked(payload,generated):
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['costs']['activities']=2000
    response,_=refine_call(payload,generated,Provider(proposal),target=generated['days'][0]['date'])
    assert response.status_code==502

@pytest.mark.parametrize('mutation',['empty','overlap','midnight','badTime','partialCoordinates','duplicate','nanCoordinates','tooFew'])
def test_timeline_validation(payload,generated,mutation):
    day=generated['days'][0]
    if mutation=='empty': day['activities']=[]
    if mutation=='overlap': day['activities'][1]['startTime']='09:30'
    if mutation=='midnight': day['activities'][1]['startTime']='23:30'
    if mutation=='badTime': day['activities'][0]['startTime']='9am'
    if mutation=='partialCoordinates': day['activities'][0]['latitude']=12.0
    if mutation=='duplicate': day['activities'][1]['id']=day['activities'][0]['id']
    if mutation=='nanCoordinates': day['activities'][0].update(latitude=float('nan'),longitude=0)
    if mutation=='tooFew': day['activities'].pop()
    assert call(payload,Provider(generated)).status_code==502

def test_refinement_timeout(payload,generated):
    response,_=refine_call(payload,generated,Provider(error=TimeoutError()))
    assert response.status_code==504

def test_refinement_accepts_valid_prior_context_over_16k(payload,generated):
    import json
    for day in generated['days']:
        for key in ('morning','afternoon','evening','dining'):
            day[key]='Detailed estimated plan. ' * 25
    assert len(json.dumps(generated).encode())>16384
    response,_=refine_call(payload,generated,Provider(generated))
    assert response.status_code==200,response.text

def test_refinement_preserves_fixed_commitment(payload,generated):
    generated['days'][0]['activities'][0]['fixedTime']=True
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['activities'][0]['startTime']='10:00'
    response,_=refine_call(payload,generated,Provider(proposal))
    assert response.status_code==502
    assert 'fixed-time' in response.json()['error']['message']

@pytest.mark.parametrize('mutation,reason', [
    ('schema','FORMAT_SCHEMA'),('preference','PREFERENCE_MISMATCH'),
    ('dates','DATE_COVERAGE'),('pace','PACE'),('budget','BUDGET'),('timeline','TIMELINE'),
])
def test_safe_validation_categories(payload,generated,mutation,reason,caplog):
    if mutation=='schema': generated['private-field']='PRIVATE_PROVIDER_VALUE'
    if mutation=='preference': generated['travelPace']='relaxed'
    if mutation=='dates': generated['days'].pop()
    if mutation=='pace': generated['days'][0]['mainActivityCount']=4
    if mutation=='budget': generated['days'][0]['costs']['meals']=999999
    if mutation=='timeline': generated['days'][0]['activities'][1]['startTime']='09:15'
    provider=Provider(generated)
    response=call(payload,provider)
    assert response.status_code==502
    assert response.json()['error']['code']=='AI_INVALID_RESPONSE'
    assert response.json()['error']['reason']==reason
    assert len(provider.calls)==1
    assert 'PRIVATE_PROVIDER_VALUE' not in response.text+caplog.text

def test_vibe_reason_does_not_change_pace_policy(payload,generated):
    response,previous=refine_call(payload,generated,Provider(generated),vibe='relaxed')
    assert response.status_code==502
    assert response.json()['error']['reason']=='VIBE_MISMATCH'
    assert previous['travelPace']==payload['travelPace']

def test_fixed_time_reason(payload,generated):
    generated['days'][0]['activities'][0]['fixedTime']=True
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['activities'][0]['startTime']='10:00'
    response,_=refine_call(payload,generated,Provider(proposal))
    assert response.status_code==502
    assert response.json()['error']['reason']=='FIXED_COMMITMENT'

def test_unrecognized_reason_never_serialized():
    from app.recommendations import RecommendationError
    from app.trip_routes import fail
    from app.main import error_response
    assert RecommendationError('AI_INVALID_RESPONSE',502,'Safe',reason='PRIVATE_PROVIDER_VALUE').reason is None
    for response in [fail(502,'AI_INVALID_RESPONSE','Safe',reason='PRIVATE_PROVIDER_VALUE'),
                     error_response(502,'AI_INVALID_RESPONSE','Safe',reason='PRIVATE_PROVIDER_VALUE')]:
        assert b'PRIVATE_PROVIDER_VALUE' not in response.body
        assert b'reason' not in response.body

def capped_refine(payload, generated, provider, cap=2, target=None):
    from app.itineraries import validate_itinerary
    from app.models import TripPreferences
    previous=validate_itinerary(generated,TripPreferences(**payload),'Earlier provider','earlier-model').model_dump()
    response=TestClient(create_app(NoStorage(),itinerary_service=ItineraryService(provider))).post('/api/itineraries/refine',json={
        'preferences':payload,'previous':previous,'targetDate':target,'feedback':'Keep the explicitly selected activity limit.',
        'vibe':None,'maxMainActivitiesPerDay':cap})
    return response,previous

def add_third_activity(day):
    day['mainActivityCount']=3
    day['activities'].append({'id':'third','title':'Additional visit','startTime':'18:00','durationMinutes':30,
        'kind':'main','notes':'Estimated visit','latitude':None,'longitude':None,'fixedTime':False})

def test_explicit_cap_rejects_false_narrative_compliance(payload,generated):
    proposal=copy.deepcopy(generated)
    add_third_activity(proposal['days'][-1])
    proposal['explanation']='Every day now has at most two main activities.'
    provider=Provider(proposal)
    response,_=capped_refine(payload,generated,provider,cap=2)
    assert response.status_code==502
    assert response.json()['error']['reason']=='PACE'
    assert len(provider.calls)==1
    assert '"maxMainActivitiesPerDay": 2' in provider.calls[0][0][1]['content']
    assert 'HARD REFINEMENT CONSTRAINT' in provider.calls[0][0][0]['content']

def test_cap_target_preserves_uncapped_other_days(payload,generated):
    add_third_activity(generated['days'][-1])
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['morning']='Revised target only'
    provider=Provider(proposal)
    response,previous=capped_refine(payload,generated,provider,cap=2,target=generated['days'][0]['date'])
    assert response.status_code==200,response.text
    result=response.json()
    assert result['days'][1:]==previous['days'][1:]
    assert result['days'][-1]['mainActivityCount']==3
    assert result['refinementSummary']=={'scope':'day','targetDate':generated['days'][0]['date'],
        'maxMainActivitiesPerDay':2,'dayCounts':[{'date':generated['days'][0]['date'],'mainActivityCount':2}],
        'unchangedDates':[day['date'] for day in generated['days'][1:]]}

def test_whole_cap_summary_computed_from_validated_days(payload,generated):
    response,_=capped_refine(payload,generated,Provider(generated),cap=2)
    assert response.status_code==200
    summary=response.json()['refinementSummary']
    assert summary['scope']=='whole' and summary['unchangedDates']==[]
    assert summary['dayCounts']==[{'date':d['date'],'mainActivityCount':2} for d in generated['days']]

@pytest.mark.parametrize('cap',[0,5,True,2.5,'2'])
def test_invalid_cap_before_provider(payload,generated,cap):
    provider=Provider(generated)
    response,_=capped_refine(payload,generated,provider,cap=cap)
    assert response.status_code==400 and not provider.calls

def test_cap_below_pace_minimum_before_provider(payload,generated):
    provider=Provider(generated)
    response,_=capped_refine(payload,generated,provider,cap=1)
    assert response.status_code==400
    assert response.json()['error']['code']=='REFINEMENT_PACE_CONFLICT'
    assert not provider.calls

def test_fixed_entries_conflict_before_provider(payload,generated):
    add_third_activity(generated['days'][0])
    for activity in generated['days'][0]['activities']: activity['fixedTime']=True
    provider=Provider(generated)
    response,_=capped_refine(payload,generated,provider,cap=2)
    assert response.status_code==422
    assert response.json()['error']['code']=='REFINEMENT_FIXED_CONFLICT'
    assert not provider.calls

def test_other_day_fixed_entries_do_not_block_target_cap(payload,generated):
    add_third_activity(generated['days'][-1])
    for activity in generated['days'][-1]['activities']: activity['fixedTime']=True
    response,_=capped_refine(payload,generated,Provider(generated),cap=2,target=generated['days'][0]['date'])
    assert response.status_code==200

def test_null_cap_retains_existing_behavior(payload,generated):
    add_third_activity(generated['days'][-1])
    response,_=capped_refine(payload,generated,Provider(generated),cap=None)
    assert response.status_code==200
    assert response.json()['refinementSummary']['maxMainActivitiesPerDay'] is None

def test_cap_rejects_scalar_two_with_three_main_entries(payload,generated):
    proposal=copy.deepcopy(generated)
    add_third_activity(proposal['days'][0])
    proposal['days'][0]['mainActivityCount']=2
    response,_=capped_refine(payload,generated,Provider(proposal),cap=2)
    assert response.status_code==502
    assert response.json()['error']['reason']=='PACE'

def test_cap_two_main_plus_rest_is_accepted(payload,generated):
    proposal=copy.deepcopy(generated)
    add_third_activity(proposal['days'][0])
    proposal['days'][0]['mainActivityCount']=2
    proposal['days'][0]['activities'][-1].update(kind='rest',title='Rest break')
    response,_=capped_refine(payload,generated,Provider(proposal),cap=2)
    assert response.status_code==200
    assert response.json()['refinementSummary']['dayCounts'][0]['mainActivityCount']==2

def test_cap_rejects_unknown_response_kind(payload,generated):
    proposal=copy.deepcopy(generated)
    del proposal['days'][0]['activities'][0]['kind']
    response,_=capped_refine(payload,generated,Provider(proposal),cap=2)
    assert response.status_code==502
    assert response.json()['error']['reason']=='PACE'

def test_legacy_prior_missing_kinds_remains_valid_and_can_refine(payload,generated):
    previous=copy.deepcopy(generated)
    for day in previous['days']:
        for activity in day['activities']:
            del activity['kind']
    # Provider explicitly classifies requested day; legacy other days stay unknown.
    response,prior=capped_refine(payload,previous,Provider(generated),cap=2,target=generated['days'][0]['date'])
    assert response.status_code==200,response.text
    assert response.json()['days'][1:]==prior['days'][1:]
    assert all(a['kind']=='unknown' for day in response.json()['days'][1:] for a in day['activities'])

def test_fixed_rest_does_not_consume_main_activity_cap(payload,generated):
    add_third_activity(generated['days'][0])
    generated['days'][0]['mainActivityCount']=2
    generated['days'][0]['activities'][-1].update(kind='rest',title='Fixed rest break')
    for activity in generated['days'][0]['activities']: activity['fixedTime']=True
    response,_=capped_refine(payload,generated,Provider(generated),cap=2)
    assert response.status_code==200

def test_fixed_known_kind_cannot_be_relabelled_to_evade_cap(payload,generated):
    generated['days'][0]['activities'][0]['fixedTime']=True
    proposal=copy.deepcopy(generated)
    proposal['days'][0]['activities'][0]['kind']='rest'
    response,_=capped_refine(payload,generated,Provider(proposal),cap=2)
    assert response.status_code==502
    assert response.json()['error']['reason']=='FIXED_COMMITMENT'


@pytest.mark.parametrize('mutation,code,path', [
    ('duration','less_than_equal',['days',0,'activities',0,'durationMinutes']),
    ('overlap','itinerary_overlap',['days',0]),
    ('midnight','itinerary_midnight',['days',0]),
    ('duplicate','itinerary_duplicate_id',['days',0]),
])
def test_precise_safe_timeline_diagnostics(payload,generated,mutation,code,path,caplog):
    day=generated['days'][0]
    day['activities'][0]['notes']='PRIVATE_PROVIDER_NOTE'
    if mutation=='duration': day['activities'][0]['durationMinutes']=241
    if mutation=='overlap': day['activities'][1]['startTime']='09:30'
    if mutation=='midnight': day['activities'][1]['startTime']='23:30'
    if mutation=='duplicate': day['activities'][1]['id']=day['activities'][0]['id']
    response=call(payload,Provider(generated))
    assert response.status_code==502
    assert response.json()['error']['reason']=='TIMELINE'
    import json
    assert json.dumps({'code':code,'path':path}) in caplog.text
    assert 'PRIVATE_PROVIDER_NOTE' not in caplog.text+response.text


def test_diagnostic_unknown_fields_and_messages_are_redacted(payload,generated,caplog):
    generated['days'][0]['activities'][0]['PRIVATE_FIELD']='PRIVATE_VALUE'
    response=call(payload,Provider(generated))
    assert response.status_code==502
    assert 'PRIVATE_FIELD' not in caplog.text+response.text
    assert 'PRIVATE_VALUE' not in caplog.text+response.text
    assert '"code": "SCHEMA"' in caplog.text


def test_provider_sees_duration_contract_after_schema_projection(payload,generated):
    from app.groq import strict_schema
    provider=Provider(generated)
    assert call(payload,provider).status_code==200
    messages,schema=provider.calls[0]
    projected=strict_schema(schema)
    duration=projected['$defs']['ItineraryActivity']['properties']['durationMinutes']
    assert '15 through 240' in duration['description']
    assert 'minimum' not in duration and 'maximum' not in duration
    assert '09:00 plus 90 minutes ends at 10:30' in messages[0]['content']



def test_provider_sees_total_timeline_entry_budget(payload,generated):
    from app.groq import strict_schema
    provider=Provider(generated)
    assert call(payload,provider).status_code==200
    messages,schema=provider.calls[0]
    field=strict_schema(schema)['$defs']['ItineraryDay']['properties']['activities']
    assert '8 total' in field['description'] and 'ALL kinds' in field['description']
    assert 'at most six supporting entries' in messages[0]['content']


def test_ninth_entry_is_rejected_with_safe_exact_path(payload,generated,caplog):
    day=generated['days'][0]
    day['activities']=[{**day['activities'][0], 'id':str(i), 'startTime':f'{8+i:02d}:00',
                        'durationMinutes':30, 'kind':'main' if i<2 else 'rest'} for i in range(9)]
    response=call(payload,Provider(generated))
    assert response.status_code==502
    assert '\"code\": \"too_long\"' in caplog.text
    assert '[\"days\", 0, \"activities\"]' in caplog.text



def test_capped_prompt_uses_compact_timeline_without_dropping_commitments(payload,generated):
    provider=Provider(generated)
    response,_=capped_refine(payload,generated,provider)
    assert response.status_code==200
    prompt=provider.calls[0][0][0]['content']
    assert 'supporting timeline entries are optional' in prompt
    assert 'Never omit a main activity or fixed commitment' in prompt
