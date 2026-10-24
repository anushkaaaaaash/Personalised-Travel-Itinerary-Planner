const assert = require('node:assert/strict');
const { once } = require('node:events');
const test = require('node:test');
const { createApp } = require('../src/app');
const { createTripService } = require('../src/services/tripService');
const { createSupabaseProvider } = require('../src/config/supabase');

function preferences(overrides = {}) {
  return {
    destination: '  Kyoto, Japan  ',
    departureCity: '  Mumbai  ',
    startDate: '2028-02-28',
    endDate: '2028-02-29',
    travelers: 2,
    budget: 2500,
    currency: 'USD',
    interests: ['culture', 'food'],
    dietaryNeeds: '',
    travelPace: 'balanced',
    ...overrides,
  };
}

async function withServer(app, run) {
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await run(base);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
      server.closeAllConnections();
    });
  }
}

async function post(base, body, headers = { 'Content-Type': 'application/json' }) {
  const response = await fetch(`${base}/api/trips`, { method: 'POST', headers, body });
  return { status: response.status, data: await response.json() };
}

function unexpectedSave() {
  throw new Error('Storage must not be called by this request test.');
}

test('health works without a database client or save call', async () => {
  await withServer(createApp({ saveTrip() { throw new Error('Must not be called'); } }), async (base) => {
    const response = await fetch(`${base}/api/health`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      status: 'ok', service: 'personalized-travel-itinerary-planner',
    });
  });
  assert.equal(Object.keys(require.cache).some((key) => key.includes('@supabase/supabase-js')), false);
});

test('valid POST sends trimmed, complete preferences to the injected service and confirms its ID', async () => {
  const calls = [];
  const input = preferences({ dietaryNeeds: 'jain', travelPace: 'relaxed', budget: 2500.5 });
  await withServer(createApp({ saveTrip: async (value) => {
    calls.push(value);
    return { id: 'local-test-only', databaseInternal: 'never return extra fields' };
  } }), async (base) => {
    const response = await post(base, JSON.stringify(input));
    assert.equal(response.status, 201);
    assert.deepEqual(response.data, { trip: { id: 'local-test-only' } });
  });
  assert.deepEqual(calls, [{ ...input, destination: 'Kyoto, Japan', departureCity: 'Mumbai' }]);
});

test('a database-confirmed positive safe integer ID is accepted', async () => {
  await withServer(createApp({ saveTrip: async () => ({ id: 42 }) }), async (base) => {
    assert.deepEqual(await post(base, JSON.stringify(preferences())), {
      status: 201, data: { trip: { id: 42 } },
    });
  });
});

const invalidCases = [
  ['blank destination', () => preferences({ destination: '   ' })],
  ['blank departure', () => preferences({ departureCity: '\t' })],
  ['impossible date', () => preferences({ startDate: '2027-02-29' })],
  ['non-ISO date', () => preferences({ startDate: '02/28/2028' })],
  ['reversed dates', () => preferences({ endDate: '2028-02-27' })],
  ['string budget', () => preferences({ budget: '2500' })],
  ['zero budget', () => preferences({ budget: 0 })],
  ['null budget', () => preferences({ budget: null })],
  ['fractional travelers', () => preferences({ travelers: 1.5 })],
  ['too many travelers', () => preferences({ travelers: 21 })],
  ['string travelers', () => preferences({ travelers: '2' })],
  ['unsupported currency', () => preferences({ currency: 'GBP' })],
  ['unsupported interest', () => preferences({ interests: ['unknown'] })],
  ['nested interests', () => preferences({ interests: [['food']] })],
  ['unsupported dietary need', () => preferences({ dietaryNeeds: 'arbitrary' })],
  ['unsupported travel pace', () => preferences({ travelPace: 'arbitrary' })],
  ['unsupported travel style', () => preferences({ travelStyle: 'arbitrary' })],
  ['overlong mobility concerns', () => preferences({ mobilityConcerns: 'x'.repeat(501) })],
  ['non-string mobility concerns', () => preferences({ mobilityConcerns: {} })],
  ['control characters in mobility concerns', () => preferences({ mobilityConcerns: 'Avoid\nstairs' })],
  ['unexpected property', () => preferences({ id: 'client-chosen-id' })],
  ['object in place of string', () => preferences({ destination: { city: 'Kyoto' } })],
  ['missing field', () => { const value = preferences(); delete value.travelPace; return value; }],
  ['array body', () => [preferences()]],
  ['prototype key', () => JSON.parse('{"__proto__":{"admin":true}}')],
];

for (const [label, input] of invalidCases) {
  test(`rejects ${label} before calling storage`, async () => {
    let calls = 0;
    await withServer(createApp({ saveTrip: async () => { calls += 1; return { id: 'unexpected' }; } }), async (base) => {
      const response = await post(base, JSON.stringify(input()));
      assert.equal(response.status, 400);
      assert.equal(response.data.error.code, 'VALIDATION_ERROR');
      assert.ok(Object.keys(response.data.error.fields).length > 0);
    });
    assert.equal(calls, 0);
  });
}

test('malformed JSON returns a safe 400 without echoing request contents', async () => {
  await withServer(createApp({ saveTrip: unexpectedSave }), async (base) => {
    const response = await post(base, '{"secret-marker":');
    assert.equal(response.status, 400);
    assert.equal(response.data.error.code, 'INVALID_JSON');
    assert.equal(JSON.stringify(response.data).includes('secret-marker'), false);
  });
});

test('scalar JSON is rejected by the strict JSON parser', async () => {
  await withServer(createApp({ saveTrip: unexpectedSave }), async (base) => {
    const response = await post(base, 'null');
    assert.equal(response.status, 400);
    assert.equal(response.data.error.code, 'INVALID_JSON');
  });
});

test('non-JSON requests return 415', async () => {
  await withServer(createApp({ saveTrip: unexpectedSave }), async (base) => {
    const response = await post(base, JSON.stringify(preferences()), { 'Content-Type': 'text/plain' });
    assert.equal(response.status, 415);
    assert.equal(response.data.error.code, 'UNSUPPORTED_MEDIA_TYPE');
  });
});

test('oversized JSON returns 413 before storage', async () => {
  let calls = 0;
  await withServer(createApp({ saveTrip: async () => { calls += 1; } }), async (base) => {
    const response = await post(base, JSON.stringify(preferences({ destination: 'x'.repeat(20_000) })));
    assert.equal(response.status, 413);
    assert.equal(response.data.error.code, 'PAYLOAD_TOO_LARGE');
  });
  assert.equal(calls, 0);
});

test('missing database configuration returns 503 even for valid preferences', async () => {
  // Explicit empty config prevents tests from touching a developer's real DB.
  const saveTrip = createTripService({ getSupabase: createSupabaseProvider({ config: {} }) });
  await withServer(createApp({ saveTrip }), async (base) => {
    const response = await post(base, JSON.stringify(preferences()));
    assert.equal(response.status, 503);
    assert.equal(response.data.error.code, 'TRIP_STORAGE_NOT_CONFIGURED');
    assert.equal(response.data.trip, undefined);
  });
});

test('storage failures do not leak database errors or imply a safe automatic retry', async () => {
  await withServer(createApp({ saveTrip: async () => {
    throw new Error('secret-marker table_private rejected SQL insert');
  } }), async (base) => {
    const response = await post(base, JSON.stringify(preferences()));
    assert.equal(response.status, 500);
    assert.equal(response.data.error.code, 'TRIP_SAVE_FAILED');
    assert.match(response.data.error.message, /Check stored trips before retrying/);
    assert.equal(JSON.stringify(response.data).includes('secret-marker'), false);
    assert.equal(response.data.trip, undefined);
  });
});

for (const id of [
  undefined, null, '', '   ', ' leading', 'trailing ', 'line\nbreak', 'nul\0byte',
  0, -1, 1.1, Number.MAX_SAFE_INTEGER + 1, {}, [],
]) {
  test(`storage cannot claim success without a usable ID (${JSON.stringify(id)})`, async () => {
    await withServer(createApp({ saveTrip: async () => ({ id }) }), async (base) => {
      const response = await post(base, JSON.stringify(preferences()));
      assert.equal(response.status, 500);
      assert.equal(response.data.error.code, 'TRIP_SAVE_UNCONFIRMED');
      assert.equal(response.data.trip, undefined);
    });
  });
}

test('frontend payload and POST client reach Express and the confirmed schema adapter over loopback only', async () => {
  const { createTrip } = await import('../../frontend/src/services/api.js');
  const { buildTripPayload } = await import('../../frontend/src/utils/tripPreferences.js');
  const payload = buildTripPayload(preferences({
    travelers: '3', budget: '4800.75', currency: 'EUR',
    dietaryNeeds: 'halal', travelPace: 'fast', interests: ['history', 'nature'],
  }));
  assert.equal(payload.valid, true);

  const calls = [];
  const fakeClient = {
    from(table) { calls.push(['from', table]); return this; },
    insert(row) { calls.push(['insert', row]); return this; },
    select(columns) { calls.push(['select', columns]); return this; },
    async single() { calls.push(['single']); return { data: { id: 73 }, error: null }; },
  };
  const saveTrip = createTripService({ getSupabase: () => fakeClient });
  const statuses = [];
  await withServer(createApp({ saveTrip }), async (base) => {
    const saved = await createTrip(payload.value, {
      baseUrl: `${base}/api`,
      fetchImpl: async (...args) => {
        const response = await fetch(...args);
        statuses.push(response.status);
        return response;
      },
    });
    assert.deepEqual(saved, { id: 73 });
  });
  assert.deepEqual(statuses, [201]);
  const details = {
    departureCity: 'Mumbai', currency: 'EUR', interests: ['history', 'nature'],
    dietaryNeeds: 'halal', travelPace: 'fast',
  };
  assert.deepEqual(calls, [
    ['from', 'trips'],
    ['insert', {
      destination: 'Kyoto, Japan', start_date: '2028-02-28', end_date: '2028-02-29',
      budget: 4800.75, travelers: 3, preferences: JSON.stringify(details),
    }],
    ['select', 'id'], ['single'],
  ]);
  assert.deepEqual(JSON.parse(calls[1][1].preferences), details);
  assert.equal(Object.keys(require.cache).some((key) => key.includes('@supabase/supabase-js')), false);
});
