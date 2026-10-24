import test from 'node:test';
import assert from 'node:assert/strict';
import { generateItinerary, refineItinerary, validItinerary, itineraryDates } from '../src/services/itineraries.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const prefs = { ...createInitialForm(), destination: 'Kyoto', departureCity: 'Tokyo', startDate: '2028-02-28', endDate: '2028-02-29' };
export const fixture = () => ({ source: 'ai', saved: false, provider: 'test-only', model: 'fixture', status: 'planned', vibe: null, destination: 'Kyoto', currency: 'USD', travelStyle: '', travelPace: 'balanced', explanation: 'A culture-focused visit', warnings: ['Verify all prices and access directly.'], estimatedTotalGroupCost: 300, remainingBudget: 2200, days: ['2028-02-28', '2028-02-29'].map(date => ({ date, morning: 'Museum', afternoon: 'Garden', evening: 'Rest', dining: 'Local dining', dietaryNotes: 'Verify menus', mobilityNotes: 'Verify access', transitAndRest: 'Allow travel and breaks', activities: [{ id: 'museum', title: 'Museum', startTime: '09:00', durationMinutes: 60, notes: 'Confirm access', latitude: null, longitude: null, fixedTime: false }, { id: 'garden', title: 'Garden', startTime: '11:00', durationMinutes: 60, notes: 'Take a break', latitude: null, longitude: null, fixedTime: false }], mainActivityCount: 2, interestTags: ['culture'], costs: { accommodation: 50, meals: 30, localTransport: 20, activities: 20, departureTravel: 30 } })) });
test('itinerary generation posts normalized preferences only and never saves', async () => {
  const calls = [];
  const result = await generateItinerary(prefs, { fetchImpl: async (...args) => { calls.push(args); return { status: 200, json: async () => fixture() }; } });
  assert.equal(result.saved, false); assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/api/itineraries/generate'); assert.equal(calls[0][1].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0][1].body), prefs);
});
test('inclusive dates account for leap day and reject unsupported duration before request', async () => {
  assert.deepEqual(itineraryDates(prefs), ['2028-02-28', '2028-02-29']);
  let calls = 0;
  await assert.rejects(generateItinerary({ ...prefs, endDate: '2028-03-30' }, { fetchImpl: () => calls++ }), /1–14 days/);
  assert.equal(calls, 0);
});
for (const mutate of [b => b.source = 'sample', b => b.saved = true, b => b.days.pop(), b => b.days.reverse(), b => b.days[0].mainActivityCount = 4, b => b.days[0].interestTags = ['nature'], b => b.days[0].costs.meals = -1, b => b.days[0].costs.meals = '30', b => b.estimatedTotalGroupCost = 200, b => b.remainingBudget = 10, b => b.currency = 'INR', b => b.days[0].morning = '', b => b.days[0].dietaryNotes = '', b => b.warnings = [], b => b.travelPace = 'fast']) test(`reject malformed/mismatched itinerary: ${mutate}`, async () => {
  const body = fixture(); mutate(body); assert.equal(validItinerary(body, prefs), false);
  await assert.rejects(generateItinerary(prefs, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), /could not be verified/);
});
test('infeasible response has no invented days or totals', () => {
  const body = { ...fixture(), status: 'infeasible', days: [], estimatedTotalGroupCost: null, remainingBudget: null };
  assert.equal(validItinerary(body, prefs), true); body.days = fixture().days; assert.equal(validItinerary(body, prefs), false);
});
test('AI configuration/network errors remain distinct from preference saving', async () => {
  await assert.rejects(generateItinerary(prefs, { fetchImpl: async () => ({ status: 503 }) }), /not configured.*unchanged/);
});
test('day refinement sends full previous context and preserves all other days', async () => {
  const previous = fixture(); const updated = fixture(); updated.days[0].morning = 'Revised museum visit'; updated.vibe = 'relaxed';
  let sent;
  const body = await refineItinerary({ preferences: prefs, previous, targetDate: previous.days[0].date, feedback: 'More rest', vibe: 'relaxed' }, { fetchImpl: async (url, options) => { sent = { url, body: JSON.parse(options.body) }; return { status: 200, json: async () => updated }; } });
  assert.equal(sent.url, '/api/itineraries/refine'); assert.deepEqual(sent.body.previous, previous); assert.equal(sent.body.targetDate, '2028-02-28'); assert.equal(body.days[1].morning, previous.days[1].morning);
  updated.days[1].morning = 'Unexpected change';
  await assert.rejects(refineItinerary({ preferences: prefs, previous, targetDate: previous.days[0].date, feedback: 'More rest', vibe: 'relaxed' }, { fetchImpl: async () => ({ status: 200, json: async () => updated }) }), /changed another day/);
});
test('timeline edits must retain valid nonoverlapping bounded activities before refinement', async () => {
  for (const edit of [d => d.activities = [], d => d.activities[0].startTime = '25:00', d => d.activities[1].startTime = '09:30', d => d.activities[0].notes = '', d => d.activities[0].latitude = 40]) {
    const previous = fixture(); edit(previous.days[0]); let called = false;
    assert.equal(validItinerary(previous, prefs), false);
    await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Change day' }, { fetchImpl: () => { called = true; } }), /Check your edited/);
    assert.equal(called, false);
  }
});

const diagnosticReasons = {
  FORMAT_SCHEMA: /required format or field checks/,
  PREFERENCE_MISMATCH: /did not match the trip preferences/,
  DATE_COVERAGE: /requested dates correctly/,
  PACE: /travel-pace checks/,
  BUDGET: /whole-trip budget checks/,
  TIMELINE: /invalid or overlapping activity timeline/,
  VIBE_MISMATCH: /requested vibe/,
  FIXED_COMMITMENT: /fixed activity commitment/,
};
for (const [reason, expected] of Object.entries(diagnosticReasons)) test(`refinement safely distinguishes backend rejection ${reason}`, async () => {
  const previous = fixture(), snapshot = structuredClone(previous); let calls = 0;
  await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'More rest' }, { fetchImpl: async () => {
    calls++; return { status: 502, json: async () => ({ error: { code: 'AI_INVALID_RESPONSE', reason, message: 'secret provider prompt <script>' } }) };
  } }), error => { assert.match(error.message, expected); assert.ok(!error.message.includes('secret')); return true; });
  assert.deepEqual(previous, snapshot); assert.equal(calls, 1);
});
test('truncation, rate limiting, network, malformed JSON and invalid 200 itinerary remain distinct', async () => {
  const cases = [
    [async () => ({ status: 502, json: async () => ({ error: { code: 'AI_OUTPUT_TRUNCATED', message: 'secret' } }) }), /cut off at its output limit/],
    [async () => ({ status: 429, json: async () => ({ error: { code: 'AI_RATE_LIMITED', message: 'secret' } }) }), /rate limit/],
    [async () => { throw Error('secret'); }, /could not be reached/],
    [async () => ({ status: 200, json: async () => { throw Error('secret'); } }), /unreadable JSON/],
    [async () => ({ status: 200, json: async () => ({ secret: 'private data' }) }), /browser-side validation/],
  ];
  for (const [fetchImpl, expected] of cases) {
    let calls = 0;
    await assert.rejects(generateItinerary(prefs, { fetchImpl: (...args) => { calls++; return fetchImpl(...args); } }), error => {
      assert.match(error.message, expected); assert.ok(!error.message.includes('secret')); return true;
    });
    assert.equal(calls, 1);
  }
});
test('unknown error codes, unknown reasons and malformed failure bodies stay masked', async () => {
  for (const body of [{ error: { code: 'secret code', reason: 'TIMELINE', message: 'secret message' } }, { error: { code: 'AI_INVALID_RESPONSE', reason: 'secret reason', message: 'secret message' } }, null, '<script>secret</script>']) {
    await assert.rejects(generateItinerary(prefs, { fetchImpl: async () => ({ status: 502, json: async () => body }) }), error => {
      assert.ok(!error.message.includes('secret')); assert.ok(!error.message.includes('<script>')); assert.ok(!error.message.includes('overlapping')); return true;
    });
  }
  await assert.rejects(generateItinerary(prefs, { fetchImpl: async () => ({ status: 502, json: async () => { throw Error('secret HTML'); } }) }), /could not be verified/);
});
test('whole and single-day refinement include explicit hard cap and require matching computed counts', async () => {
  for (const targetDate of [null, prefs.startDate]) {
    const previous = fixture(), body = fixture(); let sent;
    for (const day of body.days) for (const activity of day.activities) activity.kind = 'main';
    for (const day of previous.days) for (const activity of day.activities) activity.kind = 'main';
    body.refinementSummary = { scope: targetDate ? 'day' : 'whole', targetDate, maxMainActivitiesPerDay: 2, dayCounts: body.days.filter(d => !targetDate || d.date === targetDate).map(d => ({ date: d.date, mainActivityCount: d.mainActivityCount })), unchangedDates: body.days.filter(d => targetDate && d.date !== targetDate).map(d => d.date) };
    const result = await refineItinerary({ preferences: prefs, previous, feedback: 'Rest more', targetDate, maxMainActivitiesPerDay: 2 }, { fetchImpl: async (_, options) => { sent = JSON.parse(options.body); return { status: 200, json: async () => body }; } });
    assert.equal(sent.maxMainActivitiesPerDay, 2); assert.equal(sent.targetDate, targetDate); assert.deepEqual(result.refinementSummary, body.refinementSummary);
    body.refinementSummary.dayCounts[0].mainActivityCount = 1;
    await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Rest more', targetDate, maxMainActivitiesPerDay: 2 }, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), /count summary could not be verified/);
  }
});
test('a cap request rejects a legacy response without confirmation and does not mutate old plan', async () => {
  const previous = fixture(), snapshot = structuredClone(previous);
  await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Rest', maxMainActivitiesPerDay: 2 }, { fetchImpl: async () => ({ status: 200, json: async () => fixture() }) }), /count summary could not be verified/);
  assert.deepEqual(previous, snapshot);
});
test('pace and fixed-activity cap conflicts have controlled actionable messages; no retry or old-plan change', async () => {
  for (const [status, code, expected] of [[400, 'REFINEMENT_PACE_CONFLICT', /conflicts with the selected travel pace/], [422, 'REFINEMENT_FIXED_CONFLICT', /cannot accommodate the fixed activities/]]) {
    const previous = fixture(), snapshot = structuredClone(previous); let calls = 0;
    await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Rest', maxMainActivitiesPerDay: 1 }, { fetchImpl: async () => { calls++; return { status, json: async () => ({ error: { code, message: 'secret' } }) }; } }), error => { assert.match(error.message, expected); assert.ok(!error.message.includes('secret')); return true; });
    assert.equal(calls, 1); assert.deepEqual(previous, snapshot);
  }
});
test('hard-cap response counts typed main entries, rejects unknown kinds and misleading declared counts', async () => {
  const previous = fixture();
  const body = fixture();
  body.refinementSummary = { scope: 'whole', targetDate: null, maxMainActivitiesPerDay: 2, dayCounts: body.days.map(d => ({ date: d.date, mainActivityCount: 2 })), unchangedDates: [] };
  // The prose or declared count alone cannot prove a hard cap.
  await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Maximum two', maxMainActivitiesPerDay: 2 }, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), /count summary could not be verified/);
  for (const day of body.days) for (const activity of day.activities) activity.kind = 'rest';
  await assert.rejects(refineItinerary({ preferences: prefs, previous, feedback: 'Maximum two', maxMainActivitiesPerDay: 2 }, { fetchImpl: async () => ({ status: 200, json: async () => body }) }), /count summary could not be verified/);
});
test('single-day refinement permits untouched legacy kinds normalized to unknown without changing their content', async () => {
  const previous = fixture(), body = fixture();
  body.days[0].activities.forEach(a => { a.kind = 'main'; });
  body.days[1].activities = body.days[1].activities.map(a => ({ kind: 'unknown', ...a }));
  body.refinementSummary = { scope: 'day', targetDate: prefs.startDate, maxMainActivitiesPerDay: 2, dayCounts: [{ date: prefs.startDate, mainActivityCount: 2 }], unchangedDates: [prefs.endDate] };
  const result = await refineItinerary({ preferences: prefs, previous, targetDate: prefs.startDate, feedback: 'Maximum two', maxMainActivitiesPerDay: 2 }, { fetchImpl: async () => ({ status: 200, json: async () => body }) });
  assert.equal(result.days[1].activities[0].kind, 'unknown');
});
