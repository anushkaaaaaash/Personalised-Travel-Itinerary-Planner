"""Deterministic local planning estimates, never navigation or verified travel times.

Only separately user-confirmed coordinates are used; model coordinates are untrusted.
Distances are great-circle straight lines;
walking time assumes 4 km/h plus 10 minutes per transfer. Pace adds a rest break
between stops (30/20/10 minutes) and limits the day's span (6/8/10 hours), within
09:00–20:00. These are conservative planning policies, not venue opening hours,
accessibility promises, road distances, or a claim of a globally optimal route.
"""
from copy import deepcopy
import math

BASIS = ('User-confirmed coordinates only, not independently geographically verified; straight-line Haversine distances, not road routes. '
         'Estimated walking at 4 km/h plus 10 minutes per transfer; no live directions, '
         'opening hours, terrain or accessibility verification. Planning window 09:00–20:00; '
         'relaxed/balanced/fast rest breaks 30/20/10 minutes and day limits 6/8/10 hours.')
PACE = {'relaxed': (30, 360), 'balanced': (20, 480), 'fast': (10, 600)}


def _dict(value):
    return value.model_dump() if hasattr(value, 'model_dump') else deepcopy(value)


def _coordinates(stop):
    lat, lon = stop.get('latitude'), stop.get('longitude')
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return lat, lon


def haversine_km(a, b):
    """Return straight-line km, or None for missing/invalid supplied coordinates."""
    aa, bb = _coordinates(a), _coordinates(b)
    if aa is None or bb is None:
        return None
    lat1, lon1 = map(math.radians, aa)
    lat2, lon2 = map(math.radians, bb)
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _distance(stops):
    values = [haversine_km(a, b) for a, b in zip(stops, stops[1:])]
    return None if any(v is None for v in values) else sum(values)


def _minutes(value):
    h, m = map(int, value.split(':'))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError('Invalid activity time')
    return h * 60 + m


def _transfer(a, b):
    distance = haversine_km(a, b)
    return None if distance is None else math.ceil(distance / 4 * 60) + 10


def _schedule(stops, pace, start):
    """Do not mutate on a failed schedule; fixed times are immovable anchors."""
    rest, limit = PACE[pace]
    result = deepcopy(stops)
    cursor = max(540, start)
    first = None
    for i, stop in enumerate(result):
        if i:
            transfer = _transfer(result[i-1], stop)
            if transfer is None:
                return None
            cursor += transfer + rest
        if stop.get('fixedTime', False):
            fixed = _minutes(stop['startTime'])
            if fixed < cursor:
                return None
            cursor = fixed
        if first is None:
            first = cursor
        end = cursor + stop['durationMinutes']
        if end > 1200 or end - first > limit:
            return None
        stop['startTime'] = f'{cursor // 60:02d}:{cursor % 60:02d}'
        cursor = end
    return result


def _candidate_order(stops):
    """Nearest-neighbor candidates inside fixed-anchor segments, never worse distance."""
    result = list(stops)
    start = 0
    for end in range(len(stops) + 1):
        if end < len(stops) and not stops[end].get('fixedTime', False):
            continue
        segment = stops[start:end]
        if len(segment) > 1:
            previous = stops[start-1:start] if start else []
            following = stops[end:end+1]
            best = list(segment)
            best_distance = _distance(previous + best + following)
            for initial in range(len(segment)):
                remaining = list(enumerate(segment))
                _, first = remaining.pop(initial)
                candidate = [first]
                while remaining:
                    chosen = min(range(len(remaining)), key=lambda i: (
                        haversine_km(candidate[-1], remaining[i][1]), remaining[i][0]))
                    candidate.append(remaining.pop(chosen)[1])
                distance = _distance(previous + candidate + following)
                if distance < best_distance - 1e-9:
                    best, best_distance = candidate, distance
            result[start:end] = best
        start = end + 1
    return result


def _confirmed_keys(itinerary, confirmations):
    """Bind explicit caller confirmations to exact current stops, never model metadata.

    This is a user assertion, not external geocoding or a geographic correctness check.
    No confirmation is inferred from plausible ranges, destination, or an AI source label.
    """
    current = {(day['date'], stop['id']): stop
               for day in itinerary['days'] for stop in day.get('activities', [])}
    confirmed = set()
    for entry in confirmations:
        entry = _dict(entry)
        key = (entry['date'], entry['id'])
        stop = current.get(key)
        if (key in confirmed or stop is None or _coordinates(entry) is None
                or any(entry.get(field) != stop.get(field)
                       for field in ('title', 'latitude', 'longitude'))):
            raise ValueError('Coordinate confirmation does not match a current activity')
        confirmed.add(key)
    return confirmed


def optimize_itinerary(preferences, itinerary, confirmed_coordinates=None):
    """Pure operation: preserve all stops/content and return explicit estimate metadata."""
    preferences, result = _dict(preferences), _dict(itinerary)
    confirmed = _confirmed_keys(result, confirmed_coordinates or [])
    pace = preferences.get('travelPace', 'balanced')
    if pace not in PACE:
        raise ValueError('Invalid travel pace')
    summaries = []
    for day in result['days']:
        original = deepcopy(day.get('activities', []))
        warnings = []
        trusted = bool(original) and all(
            (day['date'], stop['id']) in confirmed and _coordinates(stop) is not None
            for stop in original)
        before = _distance(original) if trusted else None
        status = 'unchanged'
        selected = original
        if not original:
            status = 'limited'
            warnings.append('No structured activities supplied; prose was not converted into invented stops or coordinates.')
        elif not trusted:
            status = 'limited'
            before = None
            warnings.append('Coordinates are missing or not explicitly confirmed by you: original order and times retained; no route distances or travel times estimated. Check each location on a map, correct its coordinates, and confirm it before optimizing. AI coordinates are not trusted.')
        else:
            candidate = _candidate_order(original)
            # The input's earliest time is an explicit start preference, not an inferred opening time.
            start = min(_minutes(s['startTime']) for s in original)
            scheduled = _schedule(candidate, pace, start)
            if scheduled is None:
                scheduled = _schedule(original, pace, start)
            if scheduled is None:
                status = 'infeasible'
                warnings.append('All stops cannot fit the planning window, pace/rest limits and fixed times using the stated walking estimate. Original plan retained; revise stops, times or transport.')
            else:
                selected = scheduled
                if selected != original:
                    status = 'optimized'
                if [s['id'] for s in selected] == [s['id'] for s in original]:
                    warnings.append('No feasible shorter order found; original stop order retained.')
        if preferences.get('mobilityConcerns'):
            warnings.append('Walking assumption is not accessibility-verified; review stated mobility needs before using this plan.')
        if selected != original:
            warnings.append('Use the structured activity schedule for updated times; prose day-part descriptions remain the original overview.')
        day['activities'] = selected
        old_times = {s['id']: s['startTime'] for s in original}
        after = _distance(selected) if before is not None else None
        legs = [{'fromId': a['id'], 'toId': b['id'],
                 'distanceKm': None if not trusted or (d := haversine_km(a,b)) is None else round(d, 3),
                 'estimatedMinutes': _transfer(a,b) if trusted else None} for a,b in zip(selected, selected[1:])]
        summaries.append({'date': day['date'], 'status': status, 'orderedStops': deepcopy(selected),
                          'legs': legs, 'beforeDistanceKm': None if before is None else round(before, 3),
                          'afterDistanceKm': None if after is None else round(after, 3),
                          'totalDistanceKm': None if after is None else round(after, 3),
                          'timingChanges': [{'id': s['id'], 'from': old_times[s['id']], 'to': s['startTime']}
                                            for s in selected if old_times[s['id']] != s['startTime']],
                          'warnings': warnings})
    return {'itinerary': result, 'routeSummary': {'basis': BASIS, 'warnings': [
        'Planning estimates only; not verified directions or a guarantee of feasibility on the ground.'], 'days': summaries}}


def build_optimizer_router():
    from fastapi import APIRouter
    from pydantic import BaseModel, ConfigDict, Field
    from .models import TripPreferences
    from .itineraries import ItineraryResponse, ItineraryPayload, validate_itinerary, MAX_DAYS
    from .recommendations import RecommendationError
    from .trip_routes import fail

    class CoordinateConfirmation(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
        id: str = Field(min_length=1, max_length=80)
        title: str = Field(min_length=1, max_length=160)
        latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
        longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)

    class OptimizeRequest(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        preferences: TripPreferences
        itinerary: ItineraryResponse
        confirmedCoordinates: list[CoordinateConfirmation] = Field(default_factory=list, max_length=MAX_DAYS * 8)

    router = APIRouter(prefix='/api/itineraries', tags=['Local route planning estimates'])

    @router.post('/optimize')
    async def optimize(request: OptimizeRequest):
        try:
            raw = request.itinerary.model_dump()
            validated = validate_itinerary({k:v for k,v in raw.items() if k in ItineraryPayload.model_fields},
                                           request.preferences, request.itinerary.provider, request.itinerary.model)
            answer = optimize_itinerary(request.preferences, validated, request.confirmedCoordinates)
            updated = answer['itinerary']
            validate_itinerary({k:v for k,v in updated.items() if k in ItineraryPayload.model_fields},
                               request.preferences, request.itinerary.provider, request.itinerary.model)
            return answer
        except RecommendationError as exc:
            return fail(400, 'INVALID_OPTIMIZATION_INPUT', exc.public_message)
        except (ValueError, KeyError, TypeError):
            return fail(400, 'INVALID_OPTIMIZATION_INPUT', 'The itinerary could not be safely optimized. No plan was saved.')

    return router
