"""Private Groq warning shape; public itinerary warnings remain a validated array."""
from copy import deepcopy
import json
from .recommendations import RecommendationError


class WarningContract:
    def __init__(self, schema):
        self.schema = deepcopy(schema)
        self.schema['properties']['warnings'] = {
            'type': 'object', 'additionalProperties': False,
            'required': ['verificationWarning', 'additionalWarnings'],
            'properties': {
                'verificationWarning': {'type': 'string', 'minLength': 1, 'maxLength': 500,
                    'description': 'Required nonblank warning: prices, hours, availability, dining suitability and accessibility are unverified estimates requiring direct verification.'},
                'additionalWarnings': {'type': 'array', 'maxItems': 7,
                    'items': {'type': 'string', 'minLength': 1, 'maxLength': 500}},
            },
        }
        self.instructions = (
            '\nWARNING OUTPUT CONTRACT: warnings is an object, not the public warnings array. '
            'Write a nonblank verificationWarning (at most 500 characters) stating that prices, hours, '
            'availability, dining suitability and accessibility are unverified and must be checked directly. '
            'Supply additionalWarnings as an array of zero to seven other nonblank warnings, each at most '
            '500 characters. This applies to planned AND infeasible results. Do not omit the required '
            'verificationWarning or return an empty warnings array. All other output fields keep the supplied '
            'schema. Previous public itineraries are input context, not the required output shape.')

    def decode(self, raw):
        try:
            text = raw if isinstance(raw, str) else json.dumps(raw, allow_nan=False)
            if len(text.encode('utf-8')) > 65536:
                raise ValueError()
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            data = json.loads(text, object_pairs_hook=unique)
            warnings = data['warnings']
            if type(warnings) is not dict or set(warnings) != {'verificationWarning', 'additionalWarnings'}:
                raise ValueError()
            additional = warnings['additionalWarnings']
            if type(additional) is not list or len(additional) > 7:
                raise ValueError()
            values = [warnings['verificationWarning'], *additional]
            if any(type(value) is not str or not value.strip() or len(value) > 500 for value in values):
                raise ValueError()
            # Shape conversion only: retain every provider-authored warning verbatim.
            # Existing public validation still checks control characters and all other constraints.
            data['warnings'] = values
            return data
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise RecommendationError('AI_INVALID_RESPONSE', 502,
                'The AI warning fields did not satisfy the required format. No replacement was accepted.',
                reason='FORMAT_SCHEMA') from None
