const assert = require('node:assert/strict');
const test = require('node:test');
const { createTripService } = require('../src/services/tripService');
const { createSupabaseProvider } = require('../src/config/supabase');

function preferences(overrides = {}) {
  return {
    destination: ' Kyoto, Japan ',
    departureCity: ' Mumbai ',
    startDate: '2028-02-28',
    endDate: '2028-02-29',
    travelers: 2,
    budget: 2500.5,
    currency: 'INR',
    interests: ['culture', 'food'],
    dietaryNeeds: 'vegetarian',
    travelPace: 'relaxed',
    ...overrides,
  };
}

function fakeClient(result, failure) {
  const calls = [];
  const chain = {
    from(table) { calls.push(['from', table]); return chain; },
    insert(row) { calls.push(['insert', row]); return chain; },
    select(columns) { calls.push(['select', columns]); return chain; },
    async single() {
      calls.push(['single']);
      if (failure) throw failure;
      return result;
    },
  };
  return { client: chain, calls };
}

test('the storage service imports and constructs without loading the SDK or asking for a client', () => {
  let calls = 0;
  createTripService({ getSupabase: () => { calls += 1; throw new Error('not called'); } });
  assert.equal(calls, 0);
  assert.equal(Object.keys(require.cache).some((key) => key.includes('@supabase/supabase-js')), false);
});

test('maps only the confirmed columns and saves the five extra preference fields as JSON text', async () => {
  const fake = fakeClient({ data: { id: 37 }, error: null });
  let clientCalls = 0;
  const saveTrip = createTripService({ getSupabase: () => { clientCalls += 1; return fake.client; } });
  const input = preferences();
  const original = structuredClone(input);
  assert.deepEqual(await saveTrip(input), { id: 37 });
  assert.equal(clientCalls, 1);

  const expectedDetails = {
    departureCity: 'Mumbai', currency: 'INR', interests: ['culture', 'food'],
    dietaryNeeds: 'vegetarian', travelPace: 'relaxed',
  };
  assert.deepEqual(fake.calls, [
    ['from', 'trips'],
    ['insert', {
      destination: 'Kyoto, Japan', start_date: '2028-02-28', end_date: '2028-02-29',
      budget: 2500.5, travelers: 2, preferences: JSON.stringify(expectedDetails),
    }],
    ['select', 'id'],
    ['single'],
  ]);
  const row = fake.calls[1][1];
  assert.equal(typeof row.preferences, 'string');
  assert.deepEqual(JSON.parse(row.preferences), expectedDetails);
  assert.equal(Object.hasOwn(row, 'id'), false);
  assert.equal(Object.hasOwn(row, 'created_at'), false);
  assert.deepEqual(input, original);
});

test('empty dietary selection and no interests survive the JSON text round trip', async () => {
  const fake = fakeClient({ data: { id: 1 }, error: null });
  await createTripService({ getSupabase: () => fake.client })(preferences({ dietaryNeeds: '', interests: [] }));
  const details = JSON.parse(fake.calls[1][1].preferences);
  assert.equal(details.dietaryNeeds, '');
  assert.deepEqual(details.interests, []);
});

test('preserves a bigint ID delivered as decimal text without converting it to a number', async () => {
  const id = '9223372036854775807';
  const fake = fakeClient({ data: { id }, error: null });
  assert.deepEqual(await createTripService({ getSupabase: () => fake.client })(preferences()), { id });
});

test('invalid direct service input is rejected before client initialization', async () => {
  let calls = 0;
  const saveTrip = createTripService({ getSupabase: () => { calls += 1; } });
  await assert.rejects(saveTrip(preferences({ budget: '2500' })), { code: 'INVALID_TRIP_PREFERENCES' });
  assert.equal(calls, 0);
});

test('missing configuration remains a safe not-configured error without initializing an SDK client', async () => {
  const saveTrip = createTripService({ getSupabase: createSupabaseProvider({ config: {} }) });
  await assert.rejects(saveTrip(preferences()), { code: 'TRIP_STORAGE_NOT_CONFIGURED' });
  assert.equal(Object.keys(require.cache).some((key) => key.includes('@supabase/supabase-js')), false);
});

test('Supabase returned errors are sanitized, even if a data ID is also present', async () => {
  const fake = fakeClient({ data: { id: 9 }, error: { message: 'secret-marker SQL table detail' } });
  await assert.rejects(createTripService({ getSupabase: () => fake.client })(preferences()), (error) => {
    assert.equal(error.code, 'TRIP_SAVE_FAILED');
    assert.equal(error.message.includes('secret-marker'), false);
    assert.equal(error.cause, undefined);
    return true;
  });
});

test('network failures are sanitized and are not retried automatically', async () => {
  const fake = fakeClient(null, new Error('secret-marker request failed'));
  await assert.rejects(createTripService({ getSupabase: () => fake.client })(preferences()), (error) => {
    assert.equal(error.code, 'TRIP_SAVE_FAILED');
    assert.equal(error.message.includes('secret-marker'), false);
    return true;
  });
  assert.equal(fake.calls.filter(([name]) => name === 'insert').length, 1);
});

for (const result of [undefined, null, {}, { data: null }, { data: {} }, { data: [] }]) {
  test(`rejects an unconfirmed response (${JSON.stringify(result)})`, async () => {
    const fake = fakeClient(result);
    await assert.rejects(createTripService({ getSupabase: () => fake.client })(preferences()), {
      code: 'TRIP_SAVE_FAILED',
    });
  });
}

for (const id of [
  0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, '', ' 12', '12 ', '12\n', 'abc',
  '0', '-1', '9223372036854775808', {}, [],
]) {
  test(`rejects an invalid or precision-losing bigint identity (${JSON.stringify(id)})`, async () => {
    const fake = fakeClient({ data: { id }, error: null });
    await assert.rejects(createTripService({ getSupabase: () => fake.client })(preferences()), {
      code: 'TRIP_SAVE_FAILED',
    });
  });
}
