import test from 'node:test';
import assert from 'node:assert/strict';
import { createTripSubmission } from '../src/services/tripSubmission.js';
import { TripApiError } from '../src/services/api.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('repeat clicks share one in-flight request, and saved state blocks another unchanged save', async () => {
  const pending = deferred();
  const states = [];
  let calls = 0;
  const controller = createTripSubmission({
    saveTrip: () => { calls++; return pending.promise; },
    onStateChange: (state) => states.push(state),
  });
  const first = controller.submit({ destination: 'Kyoto' });
  assert.equal(controller.isBusy(), true);
  assert.deepEqual(await controller.submit({ destination: 'Kyoto' }), { ignored: true });
  assert.equal(calls, 1);
  assert.equal(states.length, 1);
  assert.equal(states[0].loading, true);
  pending.resolve({ id: 'confirmed' });
  await first;
  assert.equal(controller.isBusy(), false);
  assert.equal(states.at(-1).savedTrip.id, 'confirmed');
  assert.deepEqual(await controller.submit({}), { ignored: true });
  assert.equal(calls, 1);
});

test('failure clears loading, reports no success, and allows an explicit retry', async () => {
  const states = [];
  let calls = 0;
  const controller = createTripSubmission({
    saveTrip: async () => {
      if (++calls === 1) throw new TripApiError('Saving is not ready.', 'STORAGE_UNAVAILABLE');
      return { id: 123 };
    },
    onStateChange: (state) => states.push(state),
  });
  await controller.submit({});
  assert.deepEqual(states.at(-1), { loading: false, error: 'Saving is not ready.', savedTrip: null });
  await controller.submit({});
  assert.deepEqual(states.at(-1), { loading: false, error: '', savedTrip: { id: 123 } });
  assert.equal(calls, 2);
});

test('editing clears saved status and allows saving new preferences', async () => {
  const states = [];
  let calls = 0;
  const controller = createTripSubmission({
    saveTrip: async () => ({ id: ++calls }),
    onStateChange: (state) => states.push(state),
  });
  await controller.submit({});
  controller.reset();
  assert.deepEqual(states.at(-1), { loading: false, error: '', savedTrip: null });
  await controller.submit({});
  assert.equal(states.at(-1).savedTrip.id, 2);
});

test('reset cannot unlock a pending save', async () => {
  const pending = deferred();
  const states = [];
  const controller = createTripSubmission({ saveTrip: () => pending.promise, onStateChange: (state) => states.push(state) });
  const request = controller.submit({});
  controller.reset();
  assert.equal(states.length, 1);
  assert.deepEqual(await controller.submit({}), { ignored: true });
  pending.resolve({ id: 'confirmed' });
  await request;
});

test('unmount/navigation aborts the request and ignores a late response', async () => {
  const pending = deferred();
  const states = [];
  let requestSignal;
  const controller = createTripSubmission({
    saveTrip: (_payload, { signal }) => { requestSignal = signal; return pending.promise; },
    onStateChange: (state) => states.push(state),
  });
  const request = controller.submit({});
  controller.dispose();
  assert.equal(requestSignal.aborted, true);
  pending.resolve({ id: 'late-id' });
  assert.deepEqual(await request, { ignored: true });
  assert.equal(states.length, 1);
  assert.deepEqual(await controller.submit({}), { ignored: true });
});

test('unexpected raw errors and missing IDs cannot produce success', async () => {
  for (const saveTrip of [async () => ({}), async () => { throw new Error('private database details'); }]) {
    const states = [];
    const controller = createTripSubmission({ saveTrip, onStateChange: (state) => states.push(state) });
    await controller.submit({});
    assert.equal(states.at(-1).savedTrip, null);
    assert.equal(states.at(-1).loading, false);
    assert.ok(states.at(-1).error);
    assert.equal(states.at(-1).error.includes('private'), false);
  }
});
