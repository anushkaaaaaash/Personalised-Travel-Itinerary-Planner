import test from 'node:test';
import assert from 'node:assert/strict';
import {tripDayLabel,visibleDayRange} from '../src/utils/dayLabels.js';
test('day labels use original dated trip offsets across pages and calendar boundaries',()=>{
  assert.equal(tripDayLabel('2028-01-01','2028-01-01'),'Day 01');
  assert.equal(tripDayLabel('2028-01-10','2028-01-01'),'Day 10');
  assert.equal(tripDayLabel('2028-03-01','2028-02-28'),'Day 03');
  assert.equal(tripDayLabel('2029-01-01','2028-12-31'),'Day 02');
  assert.equal(tripDayLabel('2028-04-10','2028-01-01'),'Day 101');
  for(const [day,start] of [['2028-02-31','2028-02-01'],['2028-01-01',undefined],['2027-12-31','2028-01-01'],['2028-01-02T00:00:00Z','2028-01-01']])assert.equal(tripDayLabel(day,start),'Day');
});
test('visible day range reports only the bounded page and never resets its day number',()=>{
  const sections=[{checkpoint:{itinerary:{days:[{date:'2028-01-10'},{date:'2028-01-11'},{date:'2028-01-12'}]}}}];
  const copy=structuredClone(sections);
  assert.equal(visibleDayRange(sections,'2028-01-01'),'Day 10–Day 12 · 2028-01-10 to 2028-01-12');
  assert.equal(visibleDayRange([],'2028-01-01'),'No completed days on this page');
  assert.deepEqual(sections,copy);
});
