import test from 'node:test';
import assert from 'node:assert/strict';
import { createTrip, TripApiError } from '../src/services/api.js';
import { buildTripPayload, createInitialForm } from '../src/utils/tripPreferences.js';

const payload = () => buildTripPayload({
  ...createInitialForm(), destination: 'Kyoto', departureCity: 'Mumbai',
  startDate: '2028-02-28', endDate: '2028-02-29', budget: '1200.50', travelers: '3',
}).value;
const response = (status, body) => ({ status, json: async () => body });

test('POSTs exact typed preferences and accepts only the confirmed ID', async () => {
  let calls = 0;
  const expected = payload();
  const result = await createTrip(expected, {
    baseUrl: 'http://local.test/api/',
    fetchImpl: async (url, options) => {
      calls++;
      assert.equal(url, 'http://local.test/api/trips');
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.deepEqual(JSON.parse(options.body), expected);
      assert.equal(typeof JSON.parse(options.body).budget, 'number');
      assert.equal(typeof JSON.parse(options.body).travelers, 'number');
      assert.equal(options.signal.aborted, false);
      return response(201, { trip: { id: 'trip-test-1', secret: 'never returned' } });
    },
  });
  assert.deepEqual(result, { id: 'trip-test-1' });
  assert.equal(calls, 1);
});

test('rejects invalid preferences before making a request', async () => {
  let called = false;
  await assert.rejects(createTrip({ ...payload(), budget: '1200' }, {
    fetchImpl: async () => { called = true; },
  }), { code: 'VALIDATION_ERROR' });
  assert.equal(called, false);
});

for (const [label, status, body] of [
  ['empty success body', 201, null],
  ['missing ID', 201, { trip: {} }],
  ['blank ID', 201, { trip: { id: '' } }],
  ['zero ID', 201, { trip: { id: 0 } }],
  ['object ID', 201, { trip: { id: { value: 'x' } } }],
  ['unsafe numeric ID', 201, { trip: { id: Number.MAX_SAFE_INTEGER + 1 } }],
  ['wrong success status', 200, { trip: { id: 'x' } }],
  ['storage failure', 500, { error: { message: 'postgres://secret-password' } }],
  ['setup missing', 503, { error: { message: 'secret-service-role' } }],
  ['server validation', 400, { error: { message: '<script>raw message</script>' } }],
]) {
  test(`does not confirm a save for ${label}`, async () => {
    await assert.rejects(createTrip(payload(), {
      fetchImpl: async () => response(status, body),
    }), (error) => error instanceof TripApiError && !/postgres|secret|script/.test(error.message));
  });
}

test('a malformed JSON success response remains unconfirmed', async () => {
  await assert.rejects(createTrip(payload(), {
    fetchImpl: async () => ({ status: 201, json: async () => { throw new Error('raw body'); } }),
  }), { code: 'SAVE_UNCONFIRMED' });
});

test('network failures have friendly errors and are never retried automatically', async () => {
  let calls = 0;
  await assert.rejects(createTrip(payload(), {
    fetchImpl: async () => { calls++; throw new Error('private raw transport details'); },
  }), (error) => error.code === 'NETWORK_ERROR' && !error.message.includes('private'));
  assert.equal(calls, 1);
});

test('timeout aborts the request and warns that the save may have happened', async () => {
  let requestSignal;
  await assert.rejects(createTrip(payload(), {
    timeoutMs: 5,
    fetchImpl: async (_url, { signal }) => {
      requestSignal = signal;
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
    },
  }), (error) => error.code === 'TIMEOUT' && error.message.includes('may have been saved'));
  assert.equal(requestSignal.aborted, true);
});

test('external cancellation reaches the underlying request', async () => {
  const controller = new AbortController();
  const request = createTrip(payload(), {
    signal: controller.signal,
    fetchImpl: async (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Canceled', 'AbortError')), { once: true });
    }),
  });
  controller.abort();
  await assert.rejects(request, { name: 'AbortError' });
});

test('a request canceled before submission does not call fetch', async () => {
  const controller = new AbortController();
  controller.abort();
  let called = false;
  await assert.rejects(createTrip(payload(), {
    signal: controller.signal,
    fetchImpl: async () => { called = true; return response(201, { trip: { id: 'late' } }); },
  }), { name: 'AbortError' });
  assert.equal(called, false);
});

test('a late response cannot confirm success after the timeout', async () => {
  await assert.rejects(createTrip(payload(), {
    timeoutMs: 1,
    fetchImpl: async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      return response(201, { trip: { id: 'late' } });
    },
  }), { code: 'TIMEOUT' });
});
