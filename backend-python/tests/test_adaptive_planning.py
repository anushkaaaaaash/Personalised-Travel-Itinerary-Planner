"""Pure synthetic sections; no credentials, provider requests or storage writes."""
from copy import deepcopy
from datetime import date, timedelta
import pytest
from app.adaptive_planning import SectionSpec, SectionContract, AdaptiveError, cents
from generation_fixture import private_proposal
from test_itineraries import generated


def spec_for(payload, **kwargs):
    if kwargs.get('next_date') and 'journey_strategy' not in kwargs:
        kwargs['journey_strategy'] = {'summary':'Synthetic whole-trip route.', 'stays':[{'startDate':payload['startDate'],'endDate':payload['endDate'],'location':payload['destination']}]}
    return SectionSpec.from_manifest(payload, section_days=2, **kwargs)


def section_wire(payload, generated, spec):
    public = deepcopy(generated)
    public['days'] = public['days'][:(spec.end - spec.start).days + 1]
    for index, day in enumerate(public['days']):
        day['date'] = (spec.start + timedelta(days=index)).isoformat()
        day['costs']['departureTravel'] = 0
        for activity in day['activities']:
            if activity['kind']=='main': activity['title'] += ' '+day['date']
        template=deepcopy(day['activities'][0]);template.update(id='arrival-transfer',title='Synthetic transfer',startTime='06:00',durationMinutes=30,kind='transfer')
        day['activities'].insert(0,template)
    public['warnings'] = {'verificationWarning': 'Synthetic estimated schedule only.', 'additionalWarnings': []}
    return {'journeyStrategy': spec.journey_strategy or {'summary':'Synthetic whole-trip route.', 'stays':[{'startDate':spec.original.startDate,'endDate':spec.original.endDate,'location':spec.original.destination}]}, 'proposal': private_proposal(public, spec.preferences.model_dump()),
        'startLocation': spec.start_location,
        'endLocation': spec.original.departureCity if spec.final else spec.original.destination,
        'recommendations': []}


@pytest.mark.parametrize('end', ['2028-01-24', '2028-01-31', '2029-01-01', '9999-12-31'])
def test_long_ranges_have_no_trip_cap_or_eager_date_array(payload, end):
    p = {**payload, 'startDate': '2028-01-01', 'endDate': end}
    spec = SectionSpec.from_manifest(p)
    assert spec.start.isoformat() == p['startDate']
    assert spec.end.isoformat() == '2028-01-03'
    assert spec.original.endDate == end
    assert len(SectionContract(spec).base.dates) == 3
    assert spec.total_days == (date.fromisoformat(end) - date(2028, 1, 1)).days + 1


def test_final_date_at_calendar_limit_does_not_overflow(payload):
    spec = SectionSpec.from_manifest({**payload, 'startDate': '9999-12-31', 'endDate': '9999-12-31'}, section_days=1)
    assert spec.first and spec.final


def test_valid_section_is_exact_costed_checkpoint(payload, generated):
    payload = {**payload, 'endDate': (date.fromisoformat(payload['startDate']) + timedelta(days=1)).isoformat()}
    spec = spec_for(payload)
    result = SectionContract(spec).decode(section_wire(payload, generated, spec))
    assert result['spentCents'] == sum(cents(v) for d in result['itinerary']['days'] for v in d['costs'].values())
    assert result['provenance']['validationVersion'] == 'adaptive-section-v1'
    assert result['endLocation'] == spec.original.departureCity


@pytest.mark.parametrize('mutation,code', [
    ('start', 'SECTION_CONTINUITY_CONFLICT'), ('return', 'SECTION_RETURN_MISSING'),
    ('missing_day', 'SECTION_INVALID_RESULT'), ('duplicate_date', 'SECTION_INVALID_RESULT'),
    ('fractional_cost', 'SECTION_INVALID_COST')])
def test_bad_section_never_becomes_checkpoint(payload, generated, mutation, code):
    payload = {**payload, 'endDate': (date.fromisoformat(payload['startDate']) + timedelta(days=1)).isoformat()}
    spec = spec_for(payload); wire = section_wire(payload, generated, spec)
    if mutation == 'start': wire['startLocation'] = 'Other place'
    if mutation == 'return': wire['endLocation'] = 'Other place'
    if mutation == 'missing_day': wire['proposal']['days'].pop()
    if mutation == 'duplicate_date': wire['proposal']['days'][-1]['date'] = wire['proposal']['days'][0]['date']
    if mutation == 'fractional_cost': wire['proposal']['days'][0]['costs']['meals'] = 0.001
    with pytest.raises(AdaptiveError) as caught: SectionContract(spec).decode(wire)
    assert caught.value.code == code


def test_intermediate_section_cannot_charge_departure_again(payload, generated):
    p = {**payload, 'endDate': (date.fromisoformat(payload['endDate']) + timedelta(days=9)).isoformat()}
    spec = spec_for(p, next_date=(date.fromisoformat(p['startDate']) + timedelta(days=2)).isoformat(),
        spent_cents=100, previous_boundary={'location': p['destination'], 'lastActivityEnd': '20:00'})
    wire = section_wire(p, generated, spec)
    wire['proposal']['days'][0]['costs']['departureTravel'] = 1
    with pytest.raises(AdaptiveError, match='SECTION_TRAVEL_DOUBLE_COUNT'): SectionContract(spec).decode(wire)


def test_budget_and_missing_boundary_are_not_silently_reset(payload):
    next_date = (date.fromisoformat(payload['startDate']) + timedelta(days=1)).isoformat()
    with pytest.raises(AdaptiveError, match='SECTION_BOUNDARY_MISSING'):
        spec_for(payload, next_date=next_date, spent_cents=1)
    with pytest.raises(AdaptiveError, match='SECTION_BUDGET_INVALID'):
        spec_for(payload, spent_cents=cents(payload['budget']) + 1)


def test_previous_day_rest_boundary_enforced(payload, generated):
    p = {**payload, 'endDate': (date.fromisoformat(payload['endDate']) + timedelta(days=5)).isoformat()}
    spec = spec_for(p, next_date=(date.fromisoformat(p['startDate']) + timedelta(days=2)).isoformat(),
        previous_boundary={'location': p['destination'], 'lastActivityEnd': '24:00'})
    wire = section_wire(p, generated, spec)
    wire['proposal']['days'][0]['dayStart'] = '00:00'
    for activity in [*wire['proposal']['days'][0]['requiredMainActivities'].values(),*wire['proposal']['days'][0]['activities']]: activity['gapBeforeMinutes'] = 0
    with pytest.raises(AdaptiveError, match='SECTION_REST_CONFLICT'): SectionContract(spec).decode(wire)


def test_infeasible_requires_actionable_proposed_adjustment(payload, generated):
    spec = spec_for(payload); wire = section_wire(payload, generated, spec)
    wire['proposal']['status'] = 'infeasible'; wire['proposal']['days'] = []
    with pytest.raises(AdaptiveError): SectionContract(spec).decode(wire)
    wire['recommendations'] = [{'field': 'travelPace', 'reason': 'Transfer leaves too little time for the requested activities.',
        'suggestion': 'Consider a relaxed pace, then review the revised schedule.'}]
    result = SectionContract(spec).decode(wire)
    assert result['status'] == 'needs_changes' and result['applicability'] == 'proposed'
    assert result['completed'] is False and 'itinerary' not in result
