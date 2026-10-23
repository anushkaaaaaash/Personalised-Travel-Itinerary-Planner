/** Public preference contract. Contains no database schema or secrets. */
export const INTEREST_OPTIONS = Object.freeze([
  { id: 'culture', label: 'Culture' },
  { id: 'food', label: 'Food' },
  { id: 'adventure', label: 'Adventure' },
  { id: 'nature', label: 'Nature' },
  { id: 'nightlife', label: 'Nightlife' },
  { id: 'shopping', label: 'Shopping' },
  { id: 'relaxation', label: 'Relaxation' },
  { id: 'history', label: 'History' },
].map(Object.freeze));
export const CURRENCIES = Object.freeze(['USD', 'EUR', 'INR']);
export const DIETARY_NEEDS = Object.freeze(['', 'vegetarian', 'vegan', 'jain', 'halal']);
export const TRAVEL_PACES = Object.freeze(['relaxed', 'balanced', 'fast']);
export const PREFERENCE_FIELDS = Object.freeze([
  'destination', 'departureCity', 'startDate', 'endDate', 'travelers',
  'budget', 'currency', 'interests', 'dietaryNeeds', 'travelPace',
]);

/** Strict calendar validation: Date's automatic overflow normalization is not used. */
export function isRealIsoDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthLengths = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= monthLengths[month - 1];
}

/**
 * Validate the JSON API contract. Numbers must already be numbers (not coerced).
 * Success returns a fresh, normalized object; the caller's input is never changed.
 */
export function validateTripPreferences(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(input))) {
    return { valid: false, errors: { form: 'Submit a trip preference object.' } };
  }

  const errors = {};
  const keys = Reflect.ownKeys(input);
  if (keys.some((key) => !PREFERENCE_FIELDS.includes(key))) {
    errors.form = 'Only the listed trip preference fields are accepted.';
  }
  // An HTTP JSON object cannot have getters; also reject them for direct callers.
  if (keys.some((key) => !('value' in Object.getOwnPropertyDescriptor(input, key)))) {
    return { valid: false, errors: { form: 'Submit plain trip preference values.' } };
  }
  for (const field of PREFERENCE_FIELDS) {
    if (!Object.hasOwn(input, field)) errors[field] = 'This preference is required.';
  }

  const value = {};
  for (const [field, label] of [['destination', 'Destination'], ['departureCity', 'Departure city']]) {
    if (typeof input[field] !== 'string' || !input[field].trim()) {
      errors[field] = `${label} is required.`;
    } else if (input[field].trim().length > 200 || /[\u0000-\u001f\u007f]/.test(input[field])) {
      errors[field] = `${label} must be at most 200 characters without control characters.`;
    } else {
      value[field] = input[field].trim();
    }
  }
  for (const [field, label] of [['startDate', 'Start date'], ['endDate', 'End date']]) {
    if (!isRealIsoDate(input[field])) errors[field] = `${label} must be a real date in YYYY-MM-DD format.`;
    else value[field] = input[field];
  }
  if (!errors.startDate && !errors.endDate && value.endDate < value.startDate) {
    errors.endDate = 'End date must be on or after the start date.';
  }
  if (!Number.isInteger(input.travelers) || input.travelers < 1 || input.travelers > 20) {
    errors.travelers = 'Travelers must be a whole number from 1 to 20.';
  } else value.travelers = input.travelers;
  if (typeof input.budget !== 'number' || !Number.isFinite(input.budget) || input.budget <= 0) {
    errors.budget = 'Budget must be a finite number greater than zero.';
  } else value.budget = input.budget;
  for (const [field, allowed, label] of [
    ['currency', CURRENCIES, 'Choose USD, EUR, or INR.'],
    ['dietaryNeeds', DIETARY_NEEDS, 'Choose a listed dietary preference.'],
    ['travelPace', TRAVEL_PACES, 'Choose a listed travel pace.'],
  ]) {
    if (!allowed.includes(input[field])) errors[field] = label;
    else value[field] = input[field];
  }
  const interestIds = INTEREST_OPTIONS.map(({ id }) => id);
  if (!Array.isArray(input.interests) || input.interests.length > interestIds.length
    || ![...input.interests].every((id) => typeof id === 'string' && interestIds.includes(id))
    || new Set(input.interests).size !== input.interests.length) {
    errors.interests = 'Choose unique interests from the listed options.';
  } else value.interests = [...input.interests];

  return Object.keys(errors).length ? { valid: false, errors } : { valid: true, value };
}
