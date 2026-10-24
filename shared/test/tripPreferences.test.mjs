import test from 'node:test';
import assert from 'node:assert/strict';
import { validateTripPreferences, isRealIsoDate, REQUIRED_PREFERENCE_FIELDS } from '../tripPreferences.mjs';

const valid = () => ({
  destination: ' Kyoto, Japan ', departureCity: ' Mumbai ',
  startDate: '2028-02-28', endDate: '2028-02-29', travelers: 2,
  budget: 2500.5, currency: 'USD', interests: ['culture', 'food'],
  dietaryNeeds: '', travelPace: 'balanced',
});

test('normalizes cities without mutating the complete payload', () => {
  const input = valid();
  const result = validateTripPreferences(input);
  assert.equal(result.valid, true);
  assert.equal(result.value.destination, 'Kyoto, Japan');
  assert.equal(result.value.departureCity, 'Mumbai');
  assert.deepEqual(Object.keys(result.value).sort(), [...REQUIRED_PREFERENCE_FIELDS].sort());
  assert.equal(result.value.dietaryNeeds, '');
  assert.equal(result.value.travelPace, 'balanced');
  assert.notEqual(result.value.interests, input.interests);
  assert.equal(input.destination, ' Kyoto, Japan ');
});

test('real date validation includes leap years, year boundaries, and strict format', () => {
  for (const value of ['2028-02-29', '2000-02-29', '0001-01-01', '9999-12-31']) assert.equal(isRealIsoDate(value), true, value);
  for (const value of ['2027-02-29', '1900-02-29', '2026-04-31', '2026-00-01', '2026-13-01', '2026-01-00', '0000-01-01', '2026-1-01', '2026-01-1', '2026-01-01T00:00:00Z', '', null, 20260101]) assert.equal(isRealIsoDate(value), false, String(value));
});

for (const field of REQUIRED_PREFERENCE_FIELDS) {
  test(`requires ${field}`, () => {
    const input = valid(); delete input[field];
    assert.ok(validateTripPreferences(input).errors[field]);
  });
}

const invalidValues = {
  destination: ['', ' \t ', null, 42, {}, [], 'a'.repeat(201), 'Tokyo\u0000'],
  departureCity: ['', ' ', null, 42, {}, [], 'a'.repeat(201), 'Paris\n'],
  startDate: ['2027-02-29', '', null, {}],
  endDate: ['2028-02-27', '2028-02-30', '', null, {}],
  travelers: [0, 21, -1, 1.5, '2', true, null, [], {}, Infinity, NaN],
  budget: [0, -1, '2500', true, null, [], {}, Infinity, NaN],
  currency: ['GBP', '', null, {}],
  interests: ['food', null, {}, ['food', 'food'], ['unknown'], [1], [null], new Array(1)],
  dietaryNeeds: ['kosher', null, {}, []],
  travelPace: ['', 'speedy', null, {}, []],
};
for (const [field, values] of Object.entries(invalidValues)) {
  test(`rejects invalid ${field} values and unsafe shapes`, () => {
    for (const value of values) {
      const result = validateTripPreferences({ ...valid(), [field]: value });
      assert.equal(result.valid, false, `${field}: ${String(value)}`);
      assert.ok(result.errors[field]);
    }
  });
}

test('accepts boundaries, all options, empty interests and same-day trips', () => {
  for (const travelers of [1, 20]) for (const currency of ['USD', 'EUR', 'INR']) {
    const result = validateTripPreferences({ ...valid(), travelers, currency, budget: 0.01, interests: [], endDate: '2028-02-28' });
    assert.equal(result.valid, true);
  }
  for (const dietaryNeeds of ['', 'vegetarian', 'vegan', 'jain', 'halal']) for (const travelPace of ['relaxed', 'balanced', 'fast']) {
    assert.equal(validateTripPreferences({ ...valid(), dietaryNeeds, travelPace }).valid, true);
  }
});

test('rejects non-object requests and unknown/prototype properties without echoing them', () => {
  for (const input of [null, false, '', 7, [], new Date(), Object.create({ destination: 'inherited' })]) {
    assert.equal(validateTripPreferences(input).valid, false);
  }
  for (const key of ['id', 'user_id', '__proto__', 'constructor', 'toString']) {
    const input = valid(); Object.defineProperty(input, key, { value: 'private-secret', enumerable: true });
    const result = validateTripPreferences(input);
    assert.equal(result.valid, false);
    assert.ok(result.errors.form);
    assert.equal(JSON.stringify(result).includes('private-secret'), false);
  }
  const accessor = valid();
  Object.defineProperty(accessor, 'destination', { get() { throw Error('must not execute'); } });
  assert.equal(validateTripPreferences(accessor).valid, false);
});

test('optional prompt preferences retain legacy shape when absent', () => {
  const value = validateTripPreferences(valid()).value;
  assert.equal(Object.hasOwn(value, 'travelStyle'), false);
  assert.equal(Object.hasOwn(value, 'mobilityConcerns'), false);
});

test('validates travel style options and trims optional mobility preferences', () => {
  for (const travelStyle of ['', 'budget', 'comfort', 'luxury']) {
    const result = validateTripPreferences({ ...valid(), travelStyle, mobilityConcerns: '  Avoid stairs  ' });
    assert.equal(result.valid, true);
    assert.equal(result.value.travelStyle, travelStyle);
    assert.equal(result.value.mobilityConcerns, 'Avoid stairs');
  }
  assert.equal(validateTripPreferences({ ...valid(), mobilityConcerns: 'x'.repeat(500) }).valid, true);
});

test('rejects invalid optional prompt fields without echoing contents', () => {
  for (const [field, values] of Object.entries({
    travelStyle: ['unknown', null, false, [], {}],
    mobilityConcerns: [null, false, [], {}, 42, 'x'.repeat(501), 'private\nsecret', '\u0000', '\u007f'],
  })) for (const value of values) {
    const result = validateTripPreferences({ ...valid(), [field]: value });
    assert.equal(result.valid, false);
    assert.ok(result.errors[field]);
    assert.equal(JSON.stringify(result).includes('private'), false);
  }
});
