"""Bounded output-only drafts; never accepted checkpoints or verified facts."""
from datetime import timedelta
import json
from .adaptive_planning import AdaptiveError, cents
from .generation_contract import GenerationContract
from .itineraries import validate_itinerary,adaptive_travel_dates
from .models import TripPreferences

MAX_PREVIEW_BYTES = 131072

def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate key')
        result[key] = value
    return result

_DECODER = json.JSONDecoder(object_pairs_hook=_unique,
    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def _space(text, offset):
    while offset < len(text) and text[offset] in ' \t\r\n': offset += 1
    return offset

def _array_prefix(text, offset, path):
    """Walk the actual JSON path, never matching key text inside prose."""
    offset = _space(text, offset)
    if offset >= len(text): return []
    if not path:
        if text[offset] != '[': raise ValueError('Expected day array')
        offset += 1
        values = []
        while True:
            offset = _space(text, offset)
            if offset >= len(text) or text[offset] == ']': return values
            try: value, end = _DECODER.raw_decode(text, offset)
            except json.JSONDecodeError: return values
            if len(values) >= 3: raise ValueError('Too many section days')
            values.append(value)
            offset = _space(text, end)
            if offset >= len(text) or text[offset] == ']': return values
            if text[offset] != ',': raise ValueError('Invalid day separator')
            offset += 1
    if text[offset] != '{': raise ValueError('Expected object')
    offset += 1
    seen = set()
    while True:
        offset = _space(text, offset)
        if offset >= len(text) or text[offset] == '}': return []
        try: key, end = _DECODER.raw_decode(text, offset)
        except json.JSONDecodeError: return []
        if type(key) is not str or key in seen: raise ValueError('Invalid object key')
        seen.add(key)
        offset = _space(text, end)
        if offset >= len(text): return []
        if text[offset] != ':': raise ValueError('Missing colon')
        offset = _space(text, offset + 1)
        if key == path[0]: return _array_prefix(text, offset, path[1:])
        try: _, offset = _DECODER.raw_decode(text, offset)
        except json.JSONDecodeError: return []
        offset = _space(text, offset)
        if offset >= len(text) or text[offset] == '}': return []
        if text[offset] != ',': raise ValueError('Missing separator')
        offset += 1

def preview_days(output_text, spec):
    """Check complete draft days; full section acceptance is still mandatory.

    Caller withdraws these provisional days if final section validation fails.
    They never affect completedDays or accepted budget accounting.
    """
    try:
        if type(output_text) is not str or len(output_text.encode('utf-8')) > MAX_PREVIEW_BYTES: raise ValueError()
        try: _DECODER.decode(output_text)
        except json.JSONDecodeError: pass
        raw_days = _array_prefix(output_text, 0, ('proposal', 'days'))
        days, spent = [], 0
        for index, raw_day in enumerate(raw_days):
            expected = (spec.start + timedelta(days=index)).isoformat()
            if expected > spec.end.isoformat() or type(raw_day) is not dict or raw_day.get('date') != expected: raise ValueError()
            preferences = TripPreferences.model_validate({**spec.preferences.model_dump(), 'startDate': expected, 'endDate': expected})
            eligible = adaptive_travel_dates(spec.original.startDate, spec.original.endDate,spec.journey_strategy)
            contract = GenerationContract(preferences, travel_day_dates=eligible)
            proposal = {'days':[raw_day], 'status':'planned',
                'explanation':'Provisional day; the complete section is still being checked.',
                'warnings':{'verificationWarning':'Draft estimates, not verified prices, hours, routes or bookings.', 'additionalWarnings':[]}}
            if spec.journey_strategy is None and expected not in eligible and sum(a is not None for a in raw_day.get('requiredMainActivities',{}).values())+sum(a.get('kind')=='main' for a in raw_day.get('activities',[])) < contract.minimum:
                break
            payload = contract.decode(proposal)
            checked = validate_itinerary(payload, preferences, 'openai', 'gpt-6-luna', travel_day_dates=eligible).model_dump(mode='json')['days'][0]
            spent += sum(cents(value) for value in checked['costs'].values())
            if spent > spec.remaining_cents: raise ValueError()
            if expected not in {spec.original.startDate,spec.original.endDate} and cents(checked['costs']['departureTravel']): raise ValueError()
            days.append(checked)
        return {'status':'draft', 'accepted':False, 'days':days,
            'notice':'Provisional days. Dates and daily schedules are checked; the whole section, route and budget are not yet accepted.'}
    except Exception:
        raise AdaptiveError('SECTION_PREVIEW_INVALID') from None
