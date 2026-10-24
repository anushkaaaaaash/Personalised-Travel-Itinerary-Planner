import { PREFERENCE_FIELDS, validateTripPreferences } from '../../../shared/tripPreferences.mjs';

export function createInitialForm() {
  return {
    destination: '',
    departureCity: '',
    startDate: '',
    endDate: '',
    travelers: 2,
    budget: 2500,
    currency: 'USD',
    interests: ['culture', 'food'],
    dietaryNeeds: '',
    travelPace: 'balanced',
    travelStyle: '',
    mobilityConcerns: '',
  };
}

function numericFormValue(value) {
  if (typeof value === 'number') return value;
  // Browser number fields return strings. Do not coerce booleans, arrays,
  // empty values, hex literals, or arbitrary objects into valid numbers.
  if (typeof value !== 'string' || !/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())) {
    return Number.NaN;
  }
  return Number(value.trim());
}

/** Convert form controls into a validated, JSON-ready API payload. */
export function buildTripPayload(form) {
  if (!form || typeof form !== 'object' || Array.isArray(form)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(form))) {
    return validateTripPreferences(form);
  }
  if (Reflect.ownKeys(form).some((key) => !PREFERENCE_FIELDS.includes(key)
    || !('value' in Object.getOwnPropertyDescriptor(form, key)))) {
    return { valid: false, errors: { form: 'Submit only plain trip preference values.' } };
  }
  return validateTripPreferences({
    ...form,
    travelers: numericFormValue(form.travelers),
    budget: numericFormValue(form.budget),
  });
}
