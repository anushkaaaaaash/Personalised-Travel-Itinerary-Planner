"""Private token reduction leaves public acceptance and stored routes unchanged."""
from copy import deepcopy
from datetime import date, timedelta
import json
import pytest
from app.adaptive_planning import SectionContract, AdaptiveError
from app.adaptive_day_preview import preview_days
from app.adaptive_revision import RevisionContract
from test_adaptive_planning import spec_for, section_wire
from test_adaptive_revision import base, context, wire
from test_itineraries import generated


def later(payload):
    return spec_for(payload, next_date=(date.fromisoformat(payload['startDate'])+timedelta(days=2)).isoformat(),
        previous_boundary={'location':payload['destination'],'lastActivityEnd':'20:00'})


def test_later_output_omits_route_but_public_checkpoint_identical(payload, generated):
    spec=later(payload);contract=SectionContract(spec)
    old=section_wire(payload,generated,spec);new=deepcopy(old);del new['journeyStrategy']
    assert 'journeyStrategy' not in contract.schema['properties']
    assert 'journeyStrategy' not in contract.schema['required']
    before=deepcopy(spec.journey_strategy)
    accepted=contract.decode(new)
    assert accepted==contract.decode(old)
    assert accepted['journeyStrategy']==before
    accepted['journeyStrategy']['summary']='Changed output'
    assert spec.journey_strategy==before
    assert len(json.dumps(new))<len(json.dumps(old))
    assert preview_days(json.dumps(new),spec)==preview_days(json.dumps(old),spec)
    assert preview_days(json.dumps(new),spec)['days']


def test_first_section_still_requires_route(payload,generated):
    spec=spec_for(payload);contract=SectionContract(spec);value=section_wire(payload,generated,spec)
    assert 'journeyStrategy' in contract.schema['required']
    del value['journeyStrategy']
    with pytest.raises(AdaptiveError,match='SECTION_INVALID_RESULT'):contract.decode(value)


@pytest.mark.parametrize('change',['extra','changed_route','null_route'])
def test_legacy_compatibility_never_relaxes_shape_or_route(payload,generated,change):
    spec=later(payload);value=deepcopy(section_wire(payload,generated,spec))
    if change=='extra':value['untrusted']=True
    elif change=='changed_route':value['journeyStrategy']['summary']='Changed route'
    else:value['journeyStrategy']=None
    with pytest.raises(AdaptiveError):SectionContract(spec).decode(value)


@pytest.mark.parametrize('offset',[0,1,3,5])
def test_revision_uses_same_omission_even_original_first_day(base,generated,offset):
    ctx=context(base,offset);contract=RevisionContract(ctx);old=wire(ctx,generated)
    new=deepcopy(old);del new['journeyStrategy']
    assert 'journeyStrategy' not in contract.schema['properties']
    assert contract.decode(new)==contract.decode(old)


def test_research_placeholder_legacy_and_new_remain_compatible(payload,generated):
    spec=later(payload);contract=SectionContract(spec,allow_research=True)
    value=section_wire(payload,generated,spec)
    value['proposal'].update(status='infeasible',days=[])
    value['researchRequest']='transport'
    value['journeyStrategy']={'summary':'Research requested','stays':[]}
    assert contract.decode(value)=={'status':'needs_research','kind':'transport'}
    del value['journeyStrategy']
    assert contract.decode(value)=={'status':'needs_research','kind':'transport'}


def test_reattached_strategy_counts_toward_existing_output_bound(payload,generated,monkeypatch):
    spec=later(payload);value=section_wire(payload,generated,spec);del value['journeyStrategy']
    monkeypatch.setattr('app.adaptive_planning.MAX_SECTION_BYTES',len(json.dumps(value).encode()))
    with pytest.raises(AdaptiveError,match='SECTION_OUTPUT_LIMIT'):SectionContract(spec).decode(value)


def test_new_shape_rejects_extra_and_duplicate_keys(payload,generated):
    spec=later(payload);value=section_wire(payload,generated,spec);del value['journeyStrategy']
    contract=SectionContract(spec)
    with pytest.raises(AdaptiveError):contract.decode({**value,'extra':'not allowed'})
    raw=json.dumps(value)
    with pytest.raises(AdaptiveError):contract.decode(raw[:-1]+',"recommendations":[]}')
