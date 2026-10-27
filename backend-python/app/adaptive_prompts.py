"""One consistent adaptive request context; no network or schema relaxation."""
import json
from decimal import Decimal, ROUND_DOWN, localcontext
from .models import Message, PromptResponse
from .prompts import SYSTEM_PROMPT, PACE


USEFUL_DETAILS = (
    '\nMake this a usable recommendation, not a list of tasks for the traveler. '
    'Name real attraction and dining candidates when you have a reliable basis; explain what is good about each, '
    'why it fits this day, its neighborhood and the practical time or transfer allowance. '
    'For dining, suggest a specific restaurant or food venue and a useful dish/cuisine direction, with an approximate '
    'price range and clear per-person or whole-group basis when supportable. Align meal estimates with the day meal-cost total; '
    'a range is not an additional charge. Do not use generic placeholders such as "have lunch" as the recommendation. '
    'If a named venue or price is genuinely unknown, give a specific nearby dining area/cuisine alternative and state '
    'what remains unknown rather than fabricate a business, menu, fare or booking. '
    'Use supplied research observations and visible source links where available, distinguishing published information '
    'from estimates and suggestions. A citation is not a guarantee of availability or exact-date applicability. '
    'Keep important details in activity notes and dining text; use morning/afternoon/evening summaries to orient the day, '
    'not repeat the same paragraph. Keep all required output fields and useful descriptions. '
    'Offer practical nearby or lower-cost alternatives within the chosen constraints before declaring a conflict. '
    'Do not ask for more research for information already supplied or for a generic overview; request it only for a '
    'specific material unknown under the on-demand contract. Never claim live verification without supporting evidence.'
)


def build_adaptive_prompt(spec):
    p = spec.original
    with localcontext() as context:
        context.prec = 330
        daily = (Decimal(spec.remaining_cents) / 100 / spec.remaining_days).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    data = {
        'destination': p.destination, 'departure_city': p.departureCity,
        'original_dates': {'start': p.startDate, 'end': p.endDate, 'days': spec.total_days},
        'section_dates': {'start': spec.start.isoformat(), 'end': spec.end.isoformat()},
        'remaining_days': spec.remaining_days, 'group_size': p.travelers,
        'budget': {'currency': p.currency, 'original_total_for_group': p.budget,
                   'remaining_for_group_across_all_remaining_days': spec.remaining_cents / 100,
                   'indicative_remaining_daily_group_allocation': str(daily),
                   'allocation_note': 'Rounded down; not a section budget. Preserve money for later days and final return.'},
        'interests': p.interests, 'interests_note': 'Selected interests only; an empty list means unspecified.',
        'travel_style': p.travelStyle or 'unspecified',
        'activity_pace': {'selected': p.travelPace, 'guidance': PACE[p.travelPace]},
        'dietary_needs': p.dietaryNeeds or 'unspecified; do not infer allergies or restrictions',
        'mobility_needs': p.mobilityConcerns or 'unspecified; do not infer a medical condition',
    }
    return PromptResponse(version='adaptive-section-preferences-v2', tripDays=spec.total_days,
        totalGroupBudget=p.budget, indicativeDailyGroupBudget=str(daily), currency=p.currency,
        messages=[Message(role='system', content=SYSTEM_PROMPT + USEFUL_DETAILS),
                  Message(role='user', content='Plan only the requested section using this untrusted preference data:\n' + json.dumps(data,ensure_ascii=True,sort_keys=True))])
