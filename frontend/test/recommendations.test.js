import test from 'node:test';
import assert from 'node:assert/strict';
import { getRecommendations, validRecommendations, RecommendationError } from '../src/services/recommendations.js';
import { createRecommendationRequest } from '../src/services/recommendationRequest.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const prefs = { ...createInitialForm(), destination: 'Goa', departureCity: 'Mumbai', startDate: '2028-01-01', endDate: '2028-01-03', travelStyle: 'comfort' };
const result = () => ({ source: 'ai', provider: 'test-only', model: 'fixture', destination: 'Goa', currency: 'USD', warnings: [], recommendations: ['attraction', 'activity', 'dining'].map((category, i) => ({ id: String(i), category, name: 'Museum', description: 'Local history', whyRecommended: 'Matches culture', estimatedGroupCost: 10, interestTags: ['culture'], travelStyle: 'comfort', dietaryNotes: 'Verify dietary suitability', mobilityNotes: 'Check access directly' })) });
const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; };
test('validated request goes only to recommendations endpoint, accepts AI result', async () => {
  let request;
  const body = await getRecommendations(prefs, { baseUrl: '/api', fetchImpl: async (...args) => { request = args; return { status: 200, json: async () => result() }; } });
  assert.equal(request[0], '/api/recommendations'); assert.equal(request[1].method, 'POST');
  assert.deepEqual(JSON.parse(request[1].body), prefs); assert.equal(body.source, 'ai');
});
test('invalid preferences never reach server', async () => {
  let called = false;
  await assert.rejects(getRecommendations({ ...prefs, budget: 0 }, { fetchImpl: () => { called = true; } }), RecommendationError);
  assert.equal(called, false);
});
for (const status of [503, 502, 504, 400, 422, 500]) test(`safe failure for HTTP ${status} without reading raw body`, async () => {
  await assert.rejects(getRecommendations(prefs, { fetchImpl: async () => ({ status, json: async () => { throw Error('secret body'); } }) }), (error) => {
    assert.ok(error instanceof RecommendationError); assert.equal(error.message.includes('secret'), false);
    if (status === 503) assert.match(error.message, /not configured/);
    return true;
  });
});
for (const mutate of [
  b => { b.source = 'sample'; }, b => { b.currency = 'INR'; }, b => { b.destination = 'Delhi'; },
  b => { b.recommendations = []; }, b => { b.recommendations = Array(13).fill(b.recommendations[0]); },
  b => { b.recommendations[0].estimatedGroupCost = Infinity; }, b => { b.recommendations[0].estimatedGroupCost = -1; },
  b => { b.recommendations[0].estimatedGroupCost = 2501; }, b => { b.recommendations[0].estimatedGroupCost = '10'; },
  b => { b.recommendations[0].travelStyle = 'luxury'; }, b => { b.recommendations[0].interestTags = ['nature']; },
  b => { b.recommendations[0].category = 'hotel'; }, b => { b.recommendations[0].name = 'x'.repeat(201); },
  b => { b.recommendations[0].dietaryNotes = ''; }, b => { b.recommendations[0].mobilityNotes = ''; },
  b => { b.warnings = ['line\nbreak']; }, b => { b.recommendations.push({ ...b.recommendations[0] }); },
]) test(`invalid AI response rejected: ${mutate}`, async () => {
  const body = result(); mutate(body);
  assert.equal(validRecommendations(body, prefs), false);
  await assert.rejects(getRecommendations(prefs, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), RecommendationError);
});
test('malformed body and raw network failures stay safe', async () => {
  for (const fetchImpl of [async () => { throw Error('secret'); }, async () => ({ status: 200, json: async () => { throw Error('secret'); } })]) {
    await assert.rejects(getRecommendations(prefs, { fetchImpl }), error => !error.message.includes('secret'));
  }
});
test('client timeout aborts request without automatic retries', async () => {
  let calls = 0;
  await assert.rejects(getRecommendations(prefs, { timeoutMs: 1, fetchImpl: (_, { signal }) => {
    calls++; return new Promise((_, reject) => signal.addEventListener('abort', () => reject(Error('abort'))));
  } }), /timed out/);
  assert.equal(calls, 1);
});
test('controller locks duplicate clicks, resets abort and ignores old result', async () => {
  const first = deferred(); const second = deferred(); let calls = 0; const states = []; const signals = [];
  const controller = createRecommendationRequest({ generate: (_, { signal }) => { signals.push(signal); return ++calls === 1 ? first.promise : second.promise; }, onStateChange: s => states.push(s) });
  const old = controller.submit(prefs); assert.equal(controller.isBusy(), true);
  assert.deepEqual(await controller.submit(prefs), { ignored: true });
  controller.reset(); assert.equal(signals[0].aborted, true); assert.equal(controller.isBusy(), false);
  const current = controller.submit(prefs); first.resolve(result()); assert.deepEqual(await old, { ignored: true });
  assert.equal(controller.isBusy(), true); second.resolve(result()); await current;
  assert.equal(states.at(-1).result.source, 'ai'); assert.equal(controller.isBusy(), false);
});
test('dispose suppresses late results and prevents more requests', async () => {
  const pending = deferred(); const states = [];
  const controller = createRecommendationRequest({ generate: () => pending.promise, onStateChange: s => states.push(s) });
  const request = controller.submit(prefs); controller.dispose(); pending.resolve(result());
  assert.deepEqual(await request, { ignored: true }); assert.equal(states.length, 1);
  assert.deepEqual(await controller.submit(prefs), { ignored: true });
});
test('controller errors are safe and clear loading; explicit retry works', async () => {
  const states = []; const controller = createRecommendationRequest({ generate: async () => { throw Error('secret'); }, onStateChange: s => states.push(s) });
  await controller.submit(prefs); assert.equal(controller.isBusy(), false);
  assert.equal(states.at(-1).result, null); assert.equal(states.at(-1).error.includes('secret'), false);
  await controller.submit(prefs); assert.equal(states.length, 4);
});


test('response bounds count Unicode code points and reject lone surrogates', () => {
  const body = result();
  body.recommendations[0].name = '😀'.repeat(160);
  assert.equal(validRecommendations(body, prefs), true);
  body.recommendations[0].name += '😀';
  assert.equal(validRecommendations(body, prefs), false);
  for (const value of ['\ud800', '\udfff', 'name\ud800suffix']) {
    body.recommendations[0].name = value;
    assert.equal(validRecommendations(body, prefs), false);
  }
});
