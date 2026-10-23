import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPreviewItinerary } from '../src/utils/buildPreviewItinerary.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';

const preferences = { ...createInitialForm(), destination: 'Kyoto', departureCity: 'Mumbai', startDate: '2028-02-28', endDate: '2028-03-01' };

test('preview is explicitly sample data, uses inclusive dates, and handles leap day', () => {
  const preview = buildPreviewItinerary(preferences);
  assert.equal(preview.source, 'sample');
  assert.equal(preview.days.length, 3);
  assert.equal(preview.totalDays, 3);
  assert.equal(preview.truncated, false);
});

test('large valid date ranges do not allocate an unbounded sample itinerary', () => {
  const preview = buildPreviewItinerary({ ...preferences, startDate: '0001-01-01', endDate: '9999-12-31' });
  assert.equal(preview.days.length, 14);
  assert.equal(preview.truncated, true);
  assert.ok(preview.totalDays > 1000000);
});
