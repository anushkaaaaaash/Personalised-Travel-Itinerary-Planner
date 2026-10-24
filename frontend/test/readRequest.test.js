import test from 'node:test';
import assert from 'node:assert/strict';
import { createReadRequest, PlannerRequestError, requestJson } from '../src/services/readRequest.js';
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
test('generation/history controller ignores duplicate clicks and old responses after edits', async () => {
  const first = deferred(), second = deferred(), states = [], signals = [];
  let calls = 0;
  const controller = createReadRequest({ request: (_, { signal }) => { signals.push(signal); return ++calls === 1 ? first.promise : second.promise; }, onStateChange: s => states.push(s) });
  const old = controller.submit({});
  assert.deepEqual(await controller.submit({}), { ignored: true });
  controller.reset(); assert.equal(signals[0].aborted, true);
  const current = controller.submit({});
  first.resolve('stale'); assert.deepEqual(await old, { ignored: true });
  assert.equal(controller.isBusy(), true);
  second.resolve('current'); await current;
  assert.equal(states.at(-1).result, 'current');
  controller.dispose(); assert.deepEqual(await controller.submit({}), { ignored: true });
});
test('cancel/unmount suppress late results and errors; retry is explicit', async () => {
  const pending = deferred(), states = [];
  const controller = createReadRequest({ request: () => pending.promise, onStateChange: s => states.push(s) });
  const promise = controller.submit({}); controller.dispose(); pending.resolve('late'); await promise;
  assert.equal(states.length, 1);
  let calls = 0;
  const retry = createReadRequest({ request: async () => { calls++; throw new PlannerRequestError('Not configured'); }, onStateChange: s => states.push(s) });
  await retry.submit({}); assert.equal(states.at(-1).error, 'Not configured'); assert.equal(calls, 1);
  await retry.submit({}); assert.equal(calls, 2);
});
test('HTTP failures sanitize raw body; timeout aborts without retry', async () => {
  const failure = status => status === 504 ? 'Timed out' : 'Unavailable';
  await assert.rejects(requestJson('/trips', { failure, fetchImpl: async () => ({ status: 500, json: () => { throw Error('secret'); } }) }), /Unavailable/);
  let calls = 0;
  await assert.rejects(requestJson('/trips', { failure, timeoutMs: 1, fetchImpl: (_, { signal }) => { calls++; return new Promise((_, reject) => signal.addEventListener('abort', () => reject(Error('secret')))); } }), /Timed out/);
  assert.equal(calls, 1);
});
test('JSON logout sends application/json and an empty object for backend boundary', async () => {
  let call;
  await requestJson('/auth/logout', { method: 'POST', payload: {}, failure: () => 'Failed', fetchImpl: async (...args) => { call = args; return { status: 200, json: async () => ({ signed_out: true }) }; } });
  assert.equal(call[0], '/api/auth/logout'); assert.equal(call[1].headers['Content-Type'], 'application/json'); assert.equal(call[1].body, '{}');
});

test('transport forwards only allowlisted diagnostic enums, never backend message or raw fields', async () => {
  const seen = [];
  const failure = (status, diagnostic) => { seen.push({ status, diagnostic }); return 'Controlled failure'; };
  for (const error of [
    { code: 'AI_INVALID_RESPONSE', reason: 'TIMELINE', message: 'secret prompt', providerText: '<script>secret</script>' },
    { code: 'secret-key', reason: 'BUDGET', message: 'secret prompt' },
    { code: 'AI_INVALID_RESPONSE', reason: 'secret-output', message: 'secret prompt' },
    { code: 'AI_OUTPUT_TRUNCATED', reason: 'BUDGET', message: 'secret prompt' },
  ]) await assert.rejects(requestJson('/itineraries/refine', { failure, fetchImpl: async () => ({ status: 502, json: async () => ({ error }) }) }), /Controlled failure/);
  assert.deepEqual(seen.map(s => s.diagnostic), [
    { kind: 'http', code: 'AI_INVALID_RESPONSE', reason: 'TIMELINE' },
    { kind: 'http' }, { kind: 'http', code: 'AI_INVALID_RESPONSE' },
    { kind: 'http', code: 'AI_OUTPUT_TRUNCATED' },
  ]);
  assert.ok(!JSON.stringify(seen).includes('secret'));
});

test('network and malformed successful JSON have distinct sanitized transport categories', async () => {
  const seen = [];
  for (const fetchImpl of [async () => { throw new Error('secret network'); }, async () => ({ status: 200, json: async () => { throw new Error('secret JSON'); } })]) {
    await assert.rejects(requestJson('/itineraries/refine', { fetchImpl, failure: (_, diagnostic) => { seen.push(diagnostic); return 'Controlled failure'; } }), /Controlled failure/);
  }
  assert.deepEqual(seen, [{ kind: 'network' }, { kind: 'invalid_json' }]);
});
