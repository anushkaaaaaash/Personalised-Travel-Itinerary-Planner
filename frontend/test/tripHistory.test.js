import test from 'node:test';
import assert from 'node:assert/strict';
import { getTrip, listTrips, validTripRecord } from '../src/services/tripHistory.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const prefs = { ...createInitialForm(), destination: 'Kyoto', departureCity: 'Tokyo', startDate: '2028-02-28', endDate: '2028-02-29' };
const trip = () => ({ id: 42, destination: prefs.destination, startDate: prefs.startDate, endDate: prefs.endDate, budget: prefs.budget, travelers: prefs.travelers, createdAt: null, preferences: prefs, preferencesStatus: 'available' });
const listing = () => ({ trips: [trip()], limit: 20, offset: 0, hasMore: false, scope: 'local-project-saved-trips' });
test('history and detail are GET-only and validate confirmed preferences', async () => {
  const calls = [];
  const fetchImpl = async (...args) => { calls.push(args); return { status: 200, json: async () => calls.length === 1 ? listing() : { trip: trip() } }; };
  const list = await listTrips({}, { fetchImpl }); const detail = await getTrip(list.trips[0].id, { fetchImpl });
  assert.equal(detail.id, 42); assert.deepEqual(calls.map(c => c[0]), ['/api/trips?limit=20&offset=0', '/api/trips/42']);
  assert.ok(calls.every(c => c[1].method === 'GET' && !c[1].body));
});
test('legacy records remain viewable without fabricated form defaults', () => {
  assert.equal(validTripRecord({ ...trip(), preferences: null, preferencesStatus: 'unavailable' }), true);
  assert.equal(validTripRecord({ ...trip(), preferences: null }), false);
});
test('reject mismatched IDs, untrusted listing scope, malformed and duplicate rows', async () => {
  await assert.rejects(getTrip(7, { fetchImpl: async () => ({ status: 200, json: async () => ({ trip: trip() }) }) }), /read safely/);
  for (const mutate of [b => b.scope = 'all-users', b => b.trips.push(trip()), b => b.trips[0].budget = 1, b => b.trips[0].id = '', b => b.offset = 20]) {
    const body = listing(); mutate(body);
    await assert.rejects(listTrips({}, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), /read safely/);
  }
});
test('missing and unconfigured history return useful safe errors', async () => {
  await assert.rejects(getTrip(42, { fetchImpl: async () => ({ status: 404 }) }), /no longer available/);
  await assert.rejects(listTrips({}, { fetchImpl: async () => ({ status: 503 }) }), /not configured/);
});
test('owned-history UI accepts only the authenticated scope, never project-wide rows', async () => {
  await assert.rejects(listTrips({ ownershipEnabled: true }, { fetchImpl: async () => ({ status: 200, json: async () => listing() }) }), /read safely/);
  const result = await listTrips({ ownershipEnabled: true }, { fetchImpl: async () => ({ status: 200, json: async () => ({ ...listing(), scope: 'authenticated-user-saved-trips' }) }) });
  assert.equal(result.scope, 'authenticated-user-saved-trips');
});
