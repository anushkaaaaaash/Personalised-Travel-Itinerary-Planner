import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parseItineraryImport, readItineraryFile, MAX_IMPORT_BYTES } from '../src/services/itineraryImport.js';
const exported = JSON.parse(await readFile(new URL('./fixtures/synthetic-legacy-itinerary.json', import.meta.url), 'utf8'));
test('synthetic legacy export restores existing 2/2/3 counts without inventing missing preferences or making requests', async () => {
  const original = globalThis.fetch; let calls = 0; globalThis.fetch = () => { calls++; throw Error('No network'); };
  try {
    const result = await readItineraryFile({ size: JSON.stringify(exported).length, text: async () => JSON.stringify(exported) });
    assert.deepEqual(result.itinerary.days.map(d => d.mainActivityCount), [2, 2, 3]);
    assert.equal(result.preferences, null); assert.equal(result.knownPreferences.budget, 4800);
    assert.equal(Object.hasOwn(result.knownPreferences, 'travelers'), false);
    assert.equal(Object.hasOwn(result.knownPreferences, 'departureCity'), false);
    assert.equal(calls, 0); assert.equal(Object.hasOwn(result.itinerary, 'notice'), false);
  } finally { globalThis.fetch = original; }
});
test('new exports with original valid preferences restore complete review context', () => {
  const preferences = { destination: exported.destination, departureCity: 'Example Origin', startDate: exported.days[0].date, endDate: exported.days.at(-1).date, travelers: 2, budget: 4800, currency: 'USD', interests: [], dietaryNeeds: '', travelPace: 'balanced', travelStyle: '', mobilityConcerns: '' };
  const result = parseItineraryImport(JSON.stringify({ ...exported, preferences }));
  assert.deepEqual(result.preferences, preferences);
});
test('oversized, malformed, foreign, invalid and mismatched imports reject without changing source', async () => {
  const before = structuredClone(exported);
  for (const contents of ['{broken', 'null', '[]', JSON.stringify({ ...exported, apiKey: 'not-accepted' }), JSON.stringify({ ...exported, saved: true }), JSON.stringify({ ...exported, days: [] }), JSON.stringify({ ...exported, estimatedTotalGroupCost: 1 }), JSON.stringify({ ...exported, preferences: { destination: 'Wrong' } }), ' '.repeat(MAX_IMPORT_BYTES + 1)]) assert.throws(() => parseItineraryImport(contents), /not a valid itinerary export/);
  let read = false;
  await assert.rejects(readItineraryFile({ size: MAX_IMPORT_BYTES + 1, text: () => { read = true; } }), /not a valid/);
  assert.equal(read, false); assert.deepEqual(exported, before);
});
