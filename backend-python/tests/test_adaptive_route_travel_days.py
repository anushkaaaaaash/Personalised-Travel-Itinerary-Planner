from copy import deepcopy
from datetime import date,timedelta
import json
import pytest
from app.adaptive_planning import SectionSpec,SectionContract,AdaptiveError
from app.adaptive_day_preview import preview_days
from app.section_repository import validate_checkpoint
from test_adaptive_planning import section_wire
from test_itineraries import generated


def route_case(payload,generated,*,same=False,minutes=120):
    first=date.fromisoformat(payload['startDate']);switch=(first+timedelta(days=1)).isoformat()
    strategy={'summary':'Regional rail itinerary; unverified transport estimate.','stays':[
        {'startDate':payload['startDate'],'endDate':payload['startDate'],'location':payload['destination']},
        {'startDate':switch,'endDate':payload['endDate'],'location':payload['destination'] if same else 'Pune'}]}
    spec=SectionSpec.from_manifest(payload);raw=section_wire(payload,generated,spec)
    raw['journeyStrategy']=strategy;raw['endLocation']=strategy['stays'][-1]['location']
    day=raw['proposal']['days'][1]
    day['requiredMainActivities']={k:None for k in day['requiredMainActivities']}
    day['activities']=[a for a in day['activities'] if a['kind']!='main']
    for index,a in enumerate(day['activities']):a['sequence']=index+1
    next(a for a in day['activities'] if a['kind']=='transfer')['durationMinutes']=minutes
    return spec,raw


def test_first_generated_strategy_intermediate_rail_day_and_checkpoint(payload,generated):
    spec,raw=route_case(payload,generated)
    cp=SectionContract(spec).decode(raw)
    assert cp['itinerary']['days'][1]['mainActivityCount']==0
    row={'start_date':spec.start.isoformat(),'end_date':spec.end.isoformat(),'input_boundary':{'location':spec.start_location},'final_section':False,'departure_city':payload['departureCity'],'budget_limit_cents':spec.remaining_cents}
    assert validate_checkpoint(cp,row)==cp
    # Unknown first-section route is not yet authoritative while streaming:
    # hold its under-target draft until full route+section acceptance.
    draft=preview_days(json.dumps(raw),spec)
    assert len(draft['days'])==1


@pytest.mark.parametrize('kind',['same','short','cost','missing_transfer','wrong_count'])
def test_nonqualifying_or_hard_constraint_remains_rejected(payload,generated,kind):
    spec,raw=route_case(payload,generated,same=kind=='same',minutes=119 if kind=='short' else 120)
    day=raw['proposal']['days'][1]
    if kind=='cost':day['costs']['departureTravel']=1
    if kind=='missing_transfer':next(a for a in day['activities'] if a['kind']=='transfer')['kind']='rest'
    if kind=='wrong_count':day['activities'][0]['kind']='main'
    with pytest.raises(AdaptiveError):SectionContract(spec).decode(raw)


def test_accepted_strategy_preview_allows_transition_not_new_section_boundary(payload,generated):
    spec,raw=route_case(payload,generated)
    from dataclasses import replace
    pinned=replace(spec,journey_strategy=deepcopy(raw['journeyStrategy']))
    assert len(preview_days(json.dumps(raw),pinned)['days'])==3
