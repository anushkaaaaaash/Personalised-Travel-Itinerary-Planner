import json
from copy import deepcopy
import pytest
from app.adaptive_day_preview import preview_days
from app.adaptive_planning import AdaptiveError
from test_adaptive_planning import spec_for, section_wire
from test_itineraries import generated

def fixture(payload, generated):
    spec = spec_for(payload)
    return spec, section_wire(payload, generated, spec)

def test_complete_day_exposed_before_section_complete(payload, generated):
    spec, wire = fixture(payload, generated)
    first = json.dumps(wire['proposal']['days'][0])
    result = preview_days('{"proposal":{"days":[' + first + ', {"date":', spec)
    assert result['accepted'] is False and result['status'] == 'draft'
    assert len(result['days']) == 1 and result['days'][0]['date'] == spec.start.isoformat()
    assert 'not yet accepted' in result['notice']

def test_all_split_points_never_expose_partial_day(payload, generated):
    spec, wire = fixture(payload, generated)
    text = '{"proposal":{"days":[' + json.dumps(wire['proposal']['days'][0])
    for index in range(len(text)):
        assert preview_days(text[:index], spec)['days'] == []
    assert len(preview_days(text, spec)['days']) == 1

def test_path_text_inside_description_does_not_create_day(payload, generated):
    spec, _ = fixture(payload, generated)
    assert preview_days('{"description":"proposal days [ fake ]"', spec)['days'] == []

@pytest.mark.parametrize('kind', ['date','cost','sequence','blank','duplicate','overflow'])
def test_invalid_days_never_preview(payload, generated, kind):
    spec, wire = fixture(payload, generated)
    day = deepcopy(wire['proposal']['days'][0])
    if kind == 'date': day['date'] = '2000-01-01'
    if kind == 'cost': day['costs']['meals'] = float(spec.original.budget) + 1
    if kind == 'sequence': day['activities'][0]['sequence'] = 8
    if kind == 'blank': day['morning'] = ''
    text = json.dumps({'proposal':{'days':[day]}})
    if kind == 'duplicate': text = '{"proposal":{"days":[]},"proposal":' + json.dumps({'days':[day]}) + '}'
    if kind == 'overflow': text = ' ' * 131073
    with pytest.raises(AdaptiveError, match='SECTION_PREVIEW_INVALID'): preview_days(text, spec)
