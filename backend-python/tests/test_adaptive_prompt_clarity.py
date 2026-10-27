import json
from app.adaptive_planning import SectionSpec
from app.adaptive_prompts import build_adaptive_prompt
from app.generation_contract import GenerationContract
from app.prompts import build_itinerary_prompt


def test_remaining_budget_divided_across_remaining_trip_not_section(payload):
    p={**payload,'startDate':'2028-01-01','endDate':'2028-01-24','budget':240000}
    spec=SectionSpec.from_manifest(p)
    prompt=build_adaptive_prompt(spec)
    data=json.loads(prompt.messages[1].content.split('\n',1)[1])
    assert data['remaining_days']==24 and data['section_dates']['end']=='2028-01-03'
    assert data['budget']['indicative_remaining_daily_group_allocation']=='10000.00'
    assert data['budget']['remaining_for_group_across_all_remaining_days']==240000
    assert 'total_for_entire_group_and_trip' not in data['budget']
    assert prompt.generated is False


def test_later_section_remaining_allocation_and_original_context(payload):
    p={**payload,'startDate':'2028-01-01','endDate':'2028-01-24','budget':240000}
    route={'summary':'Goa stay','stays':[{'startDate':p['startDate'],'endDate':p['endDate'],'location':p['destination']}]}
    spec=SectionSpec.from_manifest(p,next_date='2028-01-04',spent_cents=3000000,
        previous_boundary={'date':'2028-01-03','location':p['destination'],'lastActivityEnd':'20:00'},journey_strategy=route)
    data=json.loads(build_adaptive_prompt(spec).messages[1].content.split('\n',1)[1])
    assert data['remaining_days']==21
    assert data['budget']['remaining_for_group_across_all_remaining_days']==210000
    assert data['budget']['indicative_remaining_daily_group_allocation']=='10000.00'
    assert data['original_dates']['start']=='2028-01-01'


def test_useful_recommendations_preserve_safety_and_private_preferences_as_data(payload):
    p={**payload,'dietaryNeeds':'vegan'}
    spec=SectionSpec.from_manifest(p)
    prompt=build_adaptive_prompt(spec)
    system,user=[m.content for m in prompt.messages]
    assert 'specific restaurant' in system and 'neighborhood' in system
    assert 'per-person or whole-group' in system and 'not an additional charge' in system
    assert 'Do not fabricate citations' in system and 'Never claim live bookings' in system
    assert 'vegan' not in system and 'vegan' in user
    assert 'all required output fields' in system


def test_nested_contract_no_competing_root_fields_and_legacy_unchanged(payload):
    spec=SectionSpec.from_manifest(payload)
    legacy=GenerationContract(spec.preferences)
    nested=GenerationContract(spec.preferences,nested_proposal=True)
    assert legacy.schema==nested.schema
    assert 'ALL four root fields' in legacy.instructions
    assert 'ALL four root fields' not in nested.instructions
    assert 'enclosing section schema' in nested.instructions
    assert build_itinerary_prompt(spec.preferences).version=='itinerary-preferences-v1'
