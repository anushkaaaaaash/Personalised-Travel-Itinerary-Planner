import test from 'node:test';
import assert from 'node:assert/strict';
import { validRouteResult, optimizeItinerary } from '../src/services/routeOptimization.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const prefs = { ...createInitialForm(), destination: 'Kyoto', departureCity: 'Tokyo', startDate: '2028-01-01', endDate: '2028-01-01' };
const activity = (id, startTime) => ({ id, title: id, startTime, durationMinutes: 30, notes: 'Verify access', fixedTime: false, latitude: null, longitude: null });
const itinerary = () => ({ status: 'planned', source: 'ai', saved: false, provider: 'test', model: 'fixture', vibe: null, destination: 'Kyoto', currency: 'USD', travelStyle: '', travelPace: 'balanced', explanation: 'Plan', warnings: ['Unverified estimates'], estimatedTotalGroupCost: 100, remainingBudget: 2400, days: [{ date: '2028-01-01', morning: 'Visit', afternoon: 'Rest', evening: 'Dine', dining: 'Restaurant', dietaryNotes: 'Check menu', mobilityNotes: 'Check access', transitAndRest: 'Allow breaks', mainActivityCount: 2, interestTags: ['culture'], costs: { accommodation: 20, meals: 20, localTransport: 20, activities: 20, departureTravel: 20 }, activities: [activity('a', '09:00'), activity('b', '11:00')] }] });
const response = () => { const plan = itinerary(); return { itinerary: plan, routeSummary: { basis: 'Straight-line estimates only', warnings: ['Not directions'], days: [{ date: plan.days[0].date, status: 'limited', orderedStops: plan.days[0].activities, legs: [], beforeDistanceKm: null, afterDistanceKm: null, totalDistanceKm: null, timingChanges: [], warnings: ['Coordinates unavailable; order retained'] }] } }; };
test('optimizer sends existing plan without saving and accepts honest unknown distances', async () => {
  let request;
  const body = await optimizeItinerary({ preferences: prefs, itinerary: itinerary() }, { fetchImpl: async (...args) => { request = args; return { status: 200, json: async () => response() }; } });
  assert.equal(request[0], '/api/itineraries/optimize'); assert.equal(request[1].method, 'POST'); assert.equal(body.routeSummary.days[0].afterDistanceKm, null);
});
test('reject route responses that drop stops, alter fixed starts or invent negative distance', () => {
  const previous = itinerary();
  for (const change of [b => b.routeSummary.days[0].afterDistanceKm = -1, b => b.itinerary.days[0].activities.pop(), b => b.routeSummary.days[0].orderedStops = []]) {
    const body = response(); change(body); assert.equal(validRouteResult(body, prefs, previous), false);
  }
  previous.days[0].activities[0].fixedTime = true; const body = response(); body.itinerary.days[0].activities[0].fixedTime = true; body.itinerary.days[0].activities[0].startTime = '10:00';
  assert.equal(validRouteResult(body, prefs, previous), false);
});
test('frontend accepts actual local Python optimizer response, not just hand-written mocks', async () => {
  const { readFile } = await import('node:fs/promises');
  const fixture = JSON.parse(await readFile(new URL('./fixtures/optimizer-response.json', import.meta.url), 'utf8'));
  assert.equal(validRouteResult(fixture.response, fixture.preferences, fixture.previous), true);
});
test('optimization defaults to no confirmations and rejects stale or fabricated confirmation entries before requests', async () => {
  let sent;
  await optimizeItinerary({ preferences: prefs, itinerary: itinerary() }, { fetchImpl: async (_, options) => { sent = JSON.parse(options.body); return { status: 200, json: async () => response() }; } });
  assert.deepEqual(sent.confirmedCoordinates, []);
  let called = false;
  await assert.rejects(optimizeItinerary({ preferences: prefs, itinerary: itinerary(), confirmedCoordinates: [{ date: '2028-01-01', id: 'a', title: 'Wrong place', latitude: 19, longitude: 72 }] }, { fetchImpl: () => { called = true; } }), /no longer match/);
  assert.equal(called, false);
});
test('frontend rejects distances or changed routes computed from unconfirmed coordinates', () => {
  const body = response(); body.routeSummary.days[0].afterDistanceKm = 12;
  assert.equal(validRouteResult(body, prefs, itinerary(), []), false);
});
