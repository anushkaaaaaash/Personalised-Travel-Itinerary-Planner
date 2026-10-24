from copy import deepcopy
import pytest
from app.optimizer import haversine_km, optimize_itinerary


def stop(i, lon, time='09:00', fixed=False, lat=0, duration=30):
    return dict(id=str(i), title=f'Stop {i}', startTime=time, durationMinutes=duration,
                notes=f'Keep notes {i}', latitude=lat, longitude=lon, fixedTime=fixed, kind='unknown')


def confirmations(itinerary):
    return [dict(date=day['date'], **{k:stop[k] for k in ('id','title','latitude','longitude')})
            for day in itinerary['days'] for stop in day['activities']
            if stop['latitude'] is not None and stop['longitude'] is not None]


def optimize(stops, pace='balanced', confirmed=True):
    source = {'days': [{'date': '2027-01-01', 'activities': deepcopy(stops)}]}
    saved = deepcopy(source)
    answer = optimize_itinerary({'travelPace': pace}, source, confirmations(source) if confirmed else [])
    assert source == saved
    return answer['itinerary']['days'][0]['activities'], answer['routeSummary']['days'][0]


def test_zero_and_antimeridian():
    assert haversine_km(stop(1, 0), stop(2, 0)) == 0
    assert 222 < haversine_km(stop(1, 179), stop(2, -179)) < 223
    assert 20000 < haversine_km(stop(1, 0), stop(2, 180)) < 20020


@pytest.mark.parametrize('lat,lon', [(91,0), (0,181), (float('nan'),0), (0,float('inf')), (None,0), (True,0)])
def test_invalid_coordinates(lat, lon):
    assert haversine_km(stop(1, lon, lat=lat), stop(2, 0)) is None


def test_shorter_route_and_content_invariants():
    original = [stop(1, 0), stop(2, .02, '10:00'), stop(3, .01, '11:00')]
    result, summary = optimize(original)
    assert summary['status'] == 'optimized'
    assert summary['afterDistanceKm'] < summary['beforeDistanceKm']
    assert sorted(s['id'] for s in result) == sorted(s['id'] for s in original)
    for s in result:
        old = next(o for o in original if o['id'] == s['id'])
        assert {k:v for k,v in s.items() if k != 'startTime'} == {k:v for k,v in old.items() if k != 'startTime'}
    assert optimize(original) == (result, summary)
    assert all('09:00' <= s['startTime'] < '20:00' for s in result)
    assert summary['timingChanges']


def test_missing_coordinate_retains_all_order_and_times():
    original = [stop(1, 0), stop(2, None, '10:00', lat=None), stop(3, .01, '11:00')]
    result, summary = optimize(original)
    assert result == original
    assert summary['status'] == 'limited'
    assert summary['afterDistanceKm'] is None
    assert summary['timingChanges'] == []
    assert all(leg['distanceKm'] is None for leg in summary['legs'])


def test_all_missing_no_fake_zero_distance():
    _, summary = optimize([stop(1,None,lat=None)])
    assert summary['totalDistanceKm'] is None
    assert summary['status'] == 'limited'


def test_fixed_anchor_never_moves_or_crosses():
    original = [stop(1, 0), stop(2, .02, '10:00'), stop(3, .01, '12:00', True),
                stop(4, .03, '13:00'), stop(5, .02, '14:00')]
    result, summary = optimize(original, 'fast')
    assert result[2] == original[2]
    assert {s['id'] for s in result[:2]} == {'1','2'}
    assert {s['id'] for s in result[3:]} == {'4','5'}
    assert summary['afterDistanceKm'] <= summary['beforeDistanceKm']


def test_overlapping_fixed_times_are_not_silently_changed():
    original = [stop(1,0,'09:00',True), stop(2,.01,'09:15',True)]
    result, summary = optimize(original)
    assert result == original
    assert summary['status'] == 'infeasible'
    assert not summary['timingChanges']


@pytest.mark.parametrize('original', [
    [stop(1,0,'19:45',duration=60)],
    [stop(1,0,'09:00',duration=240), stop(2,.01,'14:00',duration=240)],
    [stop(1,0,'08:00',True)],
    [stop(1,0),stop(2,100,'10:00')],
])
def test_overflow_preserves_original(original):
    result, summary = optimize(original, 'relaxed')
    assert result == original
    assert summary['status'] == 'infeasible'


def test_already_optimal_order_and_feasible_schedule_unchanged():
    original = [stop(1,0), stop(2,0,'10:00')]
    result, summary = optimize(original)
    assert result == original
    assert summary['status'] == 'unchanged'
    assert summary['beforeDistanceKm'] == summary['afterDistanceKm'] == 0


def test_repairs_nonfixed_overlap_using_declared_buffers():
    result, summary = optimize([stop(1,0), stop(2,0,'09:10')])
    assert result[1]['startTime'] == '10:00'
    assert summary['status'] == 'optimized'


def test_pace_changes_breaks():
    original = [stop(1,0),stop(2,0,'10:00')]
    assert optimize(original,'relaxed')[0][1]['startTime'] == '10:10'
    assert optimize(original,'fast')[0][1]['startTime'] == '09:50'


def test_empty_day_explicitly_limited():
    result, summary = optimize([])
    assert result == [] and summary['status'] == 'limited'


def api_itinerary(payload):
    from datetime import date, timedelta
    count = (date.fromisoformat(payload['endDate'])-date.fromisoformat(payload['startDate'])).days+1
    return dict(status='planned', destination=payload['destination'], currency=payload['currency'],
                travelStyle='', travelPace=payload['travelPace'], explanation='Estimated only',
                warnings=['Unverified prices and coordinates.'], source='ai', provider='fixture', model='fixture',
                saved=False, estimatedTotalGroupCost=999, remainingBudget=999,
                days=[dict(date=(date.fromisoformat(payload['startDate'])+timedelta(days=i)).isoformat(),
                           morning='Museum',afternoon='Walk',evening='Rest',dining='Restaurant',
                           dietaryNotes='None supplied',mobilityNotes='None supplied',transitAndRest='Rest',
                           mainActivityCount=2,interestTags=['culture'],
                           activities=[stop(1,0),stop(2,.01,'11:00')],
                           costs=dict(accommodation=0,meals=10,localTransport=10,activities=10,departureTravel=10))
                      for i in range(count)])


def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.optimizer import build_optimizer_router
    app = FastAPI()
    app.include_router(build_optimizer_router())
    return TestClient(app)


def test_endpoint_validates_and_recalculates_metadata(payload):
    response = client().post('/api/itineraries/optimize', json={'preferences':payload,'itinerary':api_itinerary(payload)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['itinerary']['estimatedTotalGroupCost'] == 240
    assert result['itinerary']['remainingBudget'] == 2260
    assert result['itinerary']['saved'] is False
    assert len(result['routeSummary']['days']) == 6


def test_endpoint_rejects_mismatched_preferences(payload):
    itinerary = api_itinerary(payload)
    itinerary['destination'] = 'Other'
    response = client().post('/api/itineraries/optimize', json={'preferences':payload,'itinerary':itinerary})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'INVALID_OPTIMIZATION_INPUT'


def test_endpoint_rejects_invalid_coordinates(payload):
    itinerary = api_itinerary(payload)
    itinerary['days'][0]['activities'][0]['latitude'] = 91
    response = client().post('/api/itineraries/optimize', json={'preferences':payload,'itinerary':itinerary})
    assert response.status_code == 422


def test_endpoint_infeasible_walking_plan_preserves_stops(payload):
    itinerary = api_itinerary(payload)
    itinerary['days'][0]['activities'][1]['longitude'] = 100
    response = client().post('/api/itineraries/optimize', json={'preferences':payload,'itinerary':itinerary,'confirmedCoordinates':confirmations(itinerary)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['routeSummary']['days'][0]['status'] == 'infeasible'
    assert result['itinerary']['days'][0]['activities'] == itinerary['days'][0]['activities']


def test_repeat_optimization_is_idempotent():
    result, _ = optimize([stop(1,0),stop(2,.02,'11:00'),stop(3,.01,'12:00')])
    repeated, summary = optimize(result)
    assert repeated == result
    assert summary['status'] == 'unchanged'
    assert not summary['timingChanges']


@pytest.mark.parametrize('stops', [
    [stop(1,44.2,lat=-12.1),stop(2,44.2,'10:00',lat=-12.1)],
    [stop(1,0),stop(2,.01,'10:00')],
    [stop(1,0)],
])
def test_ai_coordinates_never_used_without_explicit_confirmation(stops):
    result, summary = optimize(stops, confirmed=False)
    assert result == stops
    assert summary['status'] == 'limited'
    assert all(summary[k] is None for k in ('beforeDistanceKm','afterDistanceKm','totalDistanceKm'))
    assert all(l['distanceKm'] is None and l['estimatedMinutes'] is None for l in summary['legs'])
    assert not summary['timingChanges']


def test_model_source_labels_cannot_claim_confirmation():
    stops = [dict(stop(1,0), coordinateSource='verified', coordinatesConfirmed=True)]
    assert optimize(stops, confirmed=False)[1]['status'] == 'limited'


@pytest.mark.parametrize('change', ['title','latitude','longitude','id','date','duplicate'])
def test_stale_unknown_or_duplicate_confirmation_rejected(change):
    itinerary = {'days':[{'date':'2027-01-01','activities':[stop(1,0)]}]}
    entries = confirmations(itinerary)
    if change == 'duplicate':
        entries.append(deepcopy(entries[0]))
    else:
        entries[0][change] = 1 if change in ('latitude','longitude') else 'different'
    with pytest.raises(ValueError):
        optimize_itinerary({'travelPace':'balanced'}, itinerary, entries)


def test_partial_confirmation_does_not_report_partial_day_distance():
    itinerary = {'days':[{'date':'2027-01-01','activities':[stop(1,0),stop(2,.01,'10:00'),stop(3,.02,'11:00')]}]}
    answer = optimize_itinerary({'travelPace':'balanced'}, itinerary, confirmations(itinerary)[:2])
    assert answer['itinerary'] == itinerary
    summary = answer['routeSummary']['days'][0]
    assert summary['status'] == 'limited'
    assert summary['totalDistanceKm'] is None
    assert all(l['distanceKm'] is None and l['estimatedMinutes'] is None for l in summary['legs'])


def test_synthetic_ai_fixture_has_no_fake_distances():
    import json
    from pathlib import Path
    itinerary = json.loads((Path(__file__).parent / 'fixtures' / 'synthetic-unconfirmed-itinerary.json').read_text())
    answer = optimize_itinerary({'travelPace':'balanced'}, itinerary)
    assert answer['itinerary'] == itinerary
    for summary in answer['routeSummary']['days']:
        assert summary['status'] == 'limited'
        assert summary['totalDistanceKm'] is None
        assert all(l['distanceKm'] is None and l['estimatedMinutes'] is None for l in summary['legs'])


def test_endpoint_requires_confirmation_and_allows_explicit_confirmation(payload):
    itinerary = api_itinerary(payload)
    request = {'preferences':payload,'itinerary':itinerary}
    unconfirmed = client().post('/api/itineraries/optimize',json=request)
    assert unconfirmed.status_code == 200
    assert all(d['status'] == 'limited' and d['totalDistanceKm'] is None for d in unconfirmed.json()['routeSummary']['days'])
    request['confirmedCoordinates'] = confirmations(itinerary)
    confirmed = client().post('/api/itineraries/optimize',json=request)
    assert confirmed.status_code == 200, confirmed.text
    assert all(d['totalDistanceKm'] is not None for d in confirmed.json()['routeSummary']['days'])
    request['confirmedCoordinates'][0]['title'] = 'Stale location'
    stale = client().post('/api/itineraries/optimize',json=request)
    assert stale.status_code == 400


def test_endpoint_confirmation_bounds(payload):
    itinerary = api_itinerary(payload)
    entries = confirmations(itinerary)
    entries[0]['latitude'] = 91
    response = client().post('/api/itineraries/optimize',json={'preferences':payload,'itinerary':itinerary,'confirmedCoordinates':entries})
    assert response.status_code == 422
