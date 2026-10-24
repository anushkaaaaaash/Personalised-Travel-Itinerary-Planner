import test from 'node:test';
import assert from 'node:assert/strict';
import { editActivity } from '../src/utils/itineraryEdits.js';
test('changing an activity destination clears stale coordinates without altering other activities', () => {
  const day = { activities: [{ title: 'Museum', latitude: 35, longitude: 139 }, { title: 'Garden', latitude: 34, longitude: 138 }] };
  const changed = editActivity(day, 0, 'title', 'Beach');
  assert.equal(changed.activities[0].latitude, null); assert.equal(changed.activities[0].longitude, null);
  assert.equal(day.activities[0].title, 'Museum'); assert.deepEqual(changed.activities[1], day.activities[1]);
  const notes = editActivity(day, 0, 'notes', 'Bring water'); assert.equal(notes.activities[0].latitude, 35);
});
test('explicit kind edits compute count only once all kinds are known; no title-based guesses', () => {
  const day = { mainActivityCount: 2, activities: [{ title: 'Museum', kind: 'unknown' }, { title: 'Rest at museum', kind: 'unknown' }] };
  const first = editActivity(day, 0, 'kind', 'main'); assert.equal(first.mainActivityCount, 2);
  const second = editActivity(first, 1, 'kind', 'rest'); assert.equal(second.mainActivityCount, 1);
  assert.equal(day.activities[0].kind, 'unknown');
});
