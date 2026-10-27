import { planningDateError } from './planningDates.js';
import { buildTripPayload } from './tripPreferences.js';

export const PLANNER_STEPS = Object.freeze([
  Object.freeze({ title: 'Trip details', fields: Object.freeze(['destination', 'departureCity', 'startDate', 'endDate']) }),
  Object.freeze({ title: 'Travel preferences', fields: Object.freeze(['travelers', 'budget', 'currency', 'interests', 'dietaryNeeds', 'travelPace', 'travelStyle', 'mobilityConcerns']) }),
  Object.freeze({ title: 'Review your trip', fields: Object.freeze([]) }),
]);
export const FINAL_STEP = PLANNER_STEPS.length - 1;

/** Reuse the shared full validator, exposing only errors relevant to this step. */
export function validatePlannerStep(form, step, options = {}) {
  const validation = buildTripPayload(form);
  const errors = { ...(validation.errors || {}) };
  const dateError = planningDateError(form, options);
  if (dateError && !errors.endDate) errors.endDate = dateError;
  if (step === FINAL_STEP) return errors;
  const fields = PLANNER_STEPS[step]?.fields || [];
  return Object.fromEntries(Object.entries(errors).filter(([field]) => field === 'form' || fields.includes(field)));
}

export function firstErrorStep(errors) {
  if (errors.form) return 0;
  const index = PLANNER_STEPS.findIndex(({ fields }) => fields.some((field) => errors[field]));
  return index < 0 ? FINAL_STEP : index;
}

export function nextPlannerStep(form, step, options = {}) {
  const errors = validatePlannerStep(form, step, options);
  return { step: Object.keys(errors).length ? step : Math.min(step + 1, FINAL_STEP), errors };
}
