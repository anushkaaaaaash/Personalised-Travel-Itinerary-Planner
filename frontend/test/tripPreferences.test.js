import test from 'node:test';
import assert from 'node:assert/strict';
import { buildTripPayload, createInitialForm } from '../src/utils/tripPreferences.js';

const validForm = () => ({
  ...createInitialForm(),
  destination: '  Kyoto, Japan  ',
  departureCity: '  Mumbai  ',
  startDate: '2028-02-28',
  endDate: '2028-02-29',
  travelers: '2',
  budget: '2500.50',
});

test('all form controls have initial values and independent interest arrays', () => {
  const form = createInitialForm();
  assert.equal(form.dietaryNeeds, '');
  assert.equal(form.travelPace, 'balanced');
  assert.equal(Object.values(form).includes(undefined), false);
  form.interests.push('nature');
  assert.deepEqual(createInitialForm().interests, ['culture', 'food']);
});

test('builds trimmed preferences with numeric budget and travelers', () => {
  const form = validForm();
  const result = buildTripPayload(form);
  assert.equal(result.valid, true);
  assert.equal(result.value.destination, 'Kyoto, Japan');
  assert.equal(result.value.departureCity, 'Mumbai');
  assert.equal(result.value.travelers, 2);
  assert.equal(result.value.budget, 2500.5);
  assert.equal(result.value.dietaryNeeds, '');
  assert.equal(result.value.travelPace, 'balanced');
  assert.equal(form.destination, '  Kyoto, Japan  ');
});

for (const [label, changes, field] of [
  ['blank destination', { destination: '  ' }, 'destination'],
  ['blank departure', { departureCity: ' ' }, 'departureCity'],
  ['missing date', { startDate: '' }, 'startDate'],
  ['impossible date', { startDate: '2027-02-29' }, 'startDate'],
  ['non-ISO date', { startDate: '02/28/2028' }, 'startDate'],
  ['end before start', { endDate: '2028-02-27' }, 'endDate'],
  ['zero budget', { budget: '0' }, 'budget'],
  ['negative budget', { budget: -1 }, 'budget'],
  ['infinite budget', { budget: Infinity }, 'budget'],
  ['empty budget', { budget: '' }, 'budget'],
  ['boolean budget', { budget: true }, 'budget'],
  ['array budget', { budget: [1] }, 'budget'],
  ['hex budget', { budget: '0x10' }, 'budget'],
  ['fractional travelers', { travelers: '2.5' }, 'travelers'],
  ['too many travelers', { travelers: '21' }, 'travelers'],
  ['no travelers', { travelers: '0' }, 'travelers'],
  ['unsupported currency', { currency: 'GBP' }, 'currency'],
  ['unknown interest', { interests: ['not-an-interest'] }, 'interests'],
  ['string interests', { interests: 'food' }, 'interests'],
  ['invalid dietary choice', { dietaryNeeds: 'anything' }, 'dietaryNeeds'],
  ['invalid pace', { travelPace: 'quick' }, 'travelPace'],
]) {
  test(`rejects ${label} with a useful field error`, () => {
    const result = buildTripPayload({ ...validForm(), ...changes });
    assert.equal(result.valid, false);
    assert.equal(typeof result.errors[field], 'string');
    assert.ok(result.errors[field].length > 0);
  });
}

test('rejects unknown fields rather than silently sending them', () => {
  assert.equal(buildTripPayload({ ...validForm(), userId: 'injected' }).valid, false);
});

test('rejects missing preference fields and unsafe top-level shapes', () => {
  const form = validForm();
  delete form.travelPace;
  assert.equal(buildTripPayload(form).valid, false);
  for (const value of [null, undefined, [], 'form', true]) {
    assert.equal(buildTripPayload(value).valid, false);
  }
});

test('accepts same-day travel, fractional positive budget, and no interests', () => {
  const result = buildTripPayload({ ...validForm(), endDate: '2028-02-28', budget: '0.50', interests: [] });
  assert.equal(result.valid, true);
  assert.equal(result.value.budget, 0.5);
});

test('rejects accessor properties without evaluating them, and non-plain objects', () => {
  let accessed = false;
  const form = validForm();
  Object.defineProperty(form, 'budget', { get() { accessed = true; return 10; }, enumerable: true });
  assert.equal(buildTripPayload(form).valid, false);
  assert.equal(accessed, false);
  assert.equal(buildTripPayload(new (class Form {})()).valid, false);
});

test('accepts finite decimal and exponent values supported by numeric controls', () => {
  for (const [input, expected] of [['.5', 0.5], ['1.', 1], ['1e3', 1000]]) {
    const result = buildTripPayload({ ...validForm(), budget: input });
    assert.equal(result.valid, true);
    assert.equal(result.value.budget, expected);
  }
});

test('new optional controls have safe empty defaults and validated payload values', () => {
  assert.equal(createInitialForm().travelStyle, '');
  assert.equal(createInitialForm().mobilityConcerns, '');
  const result = buildTripPayload({ ...validForm(), travelStyle: 'comfort', mobilityConcerns: '  Step-free access  ' });
  assert.equal(result.valid, true);
  assert.equal(result.value.travelStyle, 'comfort');
  assert.equal(result.value.mobilityConcerns, 'Step-free access');
  assert.ok(buildTripPayload({ ...validForm(), travelStyle: 'unknown' }).errors.travelStyle);
  assert.ok(buildTripPayload({ ...validForm(), mobilityConcerns: 'x'.repeat(501) }).errors.mobilityConcerns);
});
