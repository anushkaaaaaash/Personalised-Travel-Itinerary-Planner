"""Public diagnostics are fixed categories, never provider text or submitted data."""
AI_FAILURE_REASONS = frozenset({
    'FORMAT_SCHEMA', 'PREFERENCE_MISMATCH', 'DATE_COVERAGE', 'PACE',
    'BUDGET', 'TIMELINE', 'VIBE_MISMATCH', 'FIXED_COMMITMENT',
})

def safe_reason(value):
    return value if isinstance(value, str) and value in AI_FAILURE_REASONS else None


def itinerary_validation_diagnostics(exc):
    """Fixed codes and schema paths only: never serialize input, messages or context."""
    fields = frozenset({'days', 'activities', 'id', 'title', 'startTime', 'durationMinutes',
                        'notes', 'latitude', 'longitude', 'fixedTime', 'kind', 'warnings', 'explanation',
                        'morning', 'afternoon', 'evening', 'dining', 'dietaryNotes', 'mobilityNotes', 'transitAndRest'})
    codes = frozenset({'itinerary_duplicate_id', 'itinerary_overlap', 'itinerary_midnight',
                       'greater_than_equal', 'less_than_equal', 'string_pattern_mismatch',
                       'string_too_long', 'string_too_short', 'too_long', 'too_short',
                       'int_type', 'float_type', 'finite_number', 'missing', 'literal_error'})
    result = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]:
        path = [part if (type(part) is int and 0 <= part < 112) or
                (type(part) is str and part in fields) else 'field'
                for part in error.get('loc', ())[:6]]
        code = error.get('type')
        result.append({'code': code if code in codes else 'SCHEMA', 'path': path})
    return result
