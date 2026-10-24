import { buildTripPayload } from './tripPreferences.js';

export const PLANNER_STEPS = Object.freeze([
  Object.freeze({ title: 'Trip details', fields: Object.freeze(['destination', 'departureCity', 'startDate', 'endDate']) }),
  Object.freeze({ title: 'Travel preferences', fields: Object.freeze(['travelers', 'budget', 'currency', 'interests', 'dietaryNeeds', 'travelPace', 'travelStyle', 'mobilityConcerns']) }),
  Object.freeze({ title: 'Review & save', fields: Object.freeze([]) }),
]);
export const FINAL_STEP = PLANNER_STEPS.length - 1;

/** Reuse the shared full validator, exposing only errors relevant to this step. */
export function validatePlannerStep(form, step) {
  const validation = buildTripPayload(form);
  if (validation.valid) return {};
  if (step === FINAL_STEP) return validation.errors;
  const fields = PLANNER_STEPS[step]?.fields || [];
  return Object.fromEntries(Object.entries(validation.errors).filter(([field]) => field === 'form' || fields.includes(field)));
}

export function firstErrorStep(errors) {
  if (errors.form) return 0;
  const index = PLANNER_STEPS.findIndex(({ fields }) => fields.some((field) => errors[field]));
  return index < 0 ? FINAL_STEP : index;
}

export function nextPlannerStep(form, step) {
  const errors = validatePlannerStep(form, step);
  return { step: Object.keys(errors).length ? step : Math.min(step + 1, FINAL_STEP), errors };
}
