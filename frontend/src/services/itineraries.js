import { validateTripPreferences, INTEREST_OPTIONS } from '../../../shared/tripPreferences.mjs';
import { PlannerRequestError, requestJson } from './readRequest.js';
export const COST_LABELS = { accommodation: 'Accommodation', meals: 'Meals', localTransport: 'Local transport', activities: 'Activities', departureTravel: 'Departure / return travel' };
const text = (v, max) => typeof v === 'string' && v.trim().length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(v);
const number = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
export function itineraryDates(p) {
  const count = Math.round((Date.parse(`${p.endDate}T00:00:00Z`) - Date.parse(`${p.startDate}T00:00:00Z`)) / 86400000) + 1;
  if (count < 1 || count > 14) return [];
  return Array.from({ length: count }, (_, i) => new Date(Date.parse(`${p.startDate}T00:00:00Z`) + i * 86400000).toISOString().slice(0, 10));
}
export function validActivities(items) {
  if (!Array.isArray(items) || items.length < 1 || items.length > 8 || new Set(items.map(a => a?.id)).size !== items.length) return false;
  let end = 0;
  return items.every(a => a && text(a.id, 80) && text(a.title, 160) && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(a.startTime)
    && Number.isInteger(a.durationMinutes) && a.durationMinutes >= 15 && a.durationMinutes <= 240
    && text(a.notes, 500)
    && [undefined, 'unknown', 'main', 'rest', 'transfer', 'meal', 'accommodation'].includes(a.kind)
    && typeof a.fixedTime === 'boolean'
    && (() => { const [h, m] = a.startTime.split(':').map(Number); const start = h * 60 + m; if (start < end || start + a.durationMinutes > 1440) return false; end = start + a.durationMinutes; return true; })()
    && ((a.latitude === null && a.longitude === null) || (Number.isFinite(a.latitude) && Math.abs(a.latitude) <= 90 && Number.isFinite(a.longitude) && Math.abs(a.longitude) <= 180)));
}
export function validItinerary(b, p) {
  if (!b || b.source !== 'ai' || b.saved !== false || !text(b.provider, 100) || !text(b.model, 100)
    || typeof b.destination !== 'string' || b.destination.toLowerCase() !== p.destination.toLowerCase() || b.currency !== p.currency
    || ![undefined, null, 'relaxed', 'adventure', 'luxury', 'budget'].includes(b.vibe)
    || b.travelStyle !== (p.travelStyle || '') || b.travelPace !== p.travelPace || !text(b.explanation, 1000)
    || !Array.isArray(b.warnings) || b.warnings.length < 1 || b.warnings.length > 8 || !b.warnings.every(w => text(w, 500)) || !Array.isArray(b.days)) return false;
  if (b.status === 'infeasible') return b.days.length === 0 && b.estimatedTotalGroupCost === null && b.remainingBudget === null;
  const dates = itineraryDates(p), pace = { relaxed: [1, 2], balanced: [2, 3], fast: [3, 4] }[p.travelPace];
  if (b.status !== 'planned' || !dates.length || dates.length !== b.days.length || !number(b.estimatedTotalGroupCost) || !number(b.remainingBudget)) return false;
  let total = 0;
  if (!b.days.every((d, i) => {
    if (!d || !validActivities(d.activities) || d.mainActivityCount > d.activities.length || d.date !== dates[i] || !['morning', 'afternoon', 'evening', 'dining'].every(k => text(d[k], 700))
      || !['dietaryNotes', 'mobilityNotes', 'transitAndRest'].every(k => text(d[k], 500))
      || !Number.isInteger(d.mainActivityCount) || d.mainActivityCount < pace[0] || d.mainActivityCount > pace[1]
      || !Array.isArray(d.interestTags) || d.interestTags.length > 8 || new Set(d.interestTags).size !== d.interestTags.length
      || !d.interestTags.every(t => INTEREST_OPTIONS.some(o => o.id === t))
      || (p.interests.length && !d.interestTags.some(t => p.interests.includes(t)))
      || !d.costs || Object.keys(d.costs).length !== 5 || !Object.keys(COST_LABELS).every(k => number(d.costs[k]))) return false;
    total += Object.values(d.costs).reduce((a, v) => a + v, 0); return true;
  })) return false;
  const close = (a, b) => Math.abs(a - b) < 0.005;
  return total <= p.budget + 0.000001 && close(total, b.estimatedTotalGroupCost) && close(p.budget - total, b.remainingBudget);
}
const validationReasons = {
  FORMAT_SCHEMA: 'The AI output failed the required format or field checks.',
  PREFERENCE_MISMATCH: 'The AI output did not match the trip preferences.',
  DATE_COVERAGE: 'The AI output did not cover the requested dates correctly.',
  PACE: 'The AI output failed the selected travel-pace checks.',
  BUDGET: 'The AI output failed the whole-trip budget checks.',
  TIMELINE: 'The AI output contained an invalid or overlapping activity timeline.',
  VIBE_MISMATCH: 'The AI output did not preserve the requested vibe.',
  FIXED_COMMITMENT: 'The AI output changed a fixed activity commitment.',
};
const clientValidationFailure = 'The server returned an itinerary, but it failed browser-side validation and could not be verified. No replacement was accepted.';
const failure = (status, diagnostic = {}) => {
  if (status === 502 && diagnostic.code === 'AI_SCHEMA_REJECTED') return 'The AI provider rejected its generated output against the required schema. No plan was accepted or saved; no automatic retry was made.';
  if (diagnostic.kind === 'network') return 'The planner service could not be reached. Check the backend connection; no replacement was accepted.';
  if (diagnostic.kind === 'invalid_json') return 'The planner service returned unreadable JSON. No replacement was accepted.';
  if (status === 400 && diagnostic.code === 'REFINEMENT_PACE_CONFLICT') return 'The activity limit conflicts with the selected travel pace. Choose a compatible limit or explicitly change the pace; your previous plan is unchanged.';
  if (status === 422 && diagnostic.code === 'REFINEMENT_FIXED_CONFLICT') return 'The activity limit cannot accommodate the fixed activities. Review the limit or fixed commitments; your previous plan is unchanged.';
  if (status === 429) return 'The AI service rate limit was reached. Wait before retrying; no automatic retry was made.';
  if (status === 502 && diagnostic.code === 'AI_OUTPUT_TRUNCATED') return 'The AI response was cut off at its output limit. No replacement was accepted; no automatic retry was made.';
  if (status === 502 && diagnostic.code === 'AI_INVALID_RESPONSE') {
    const reason = Object.hasOwn(validationReasons, diagnostic.reason) ? validationReasons[diagnostic.reason] : 'The AI output failed server-side validation.';
    return `${reason} No replacement was accepted.`;
  }
  return status === 503 ? 'AI itinerary generation is not configured yet. Saved preferences are unchanged.'
    : status === 504 ? 'AI itinerary generation timed out. Try again when ready; no trip was saved.'
    : status === 400 || status === 422 ? 'Check your preferences. AI itineraries support trips of 1–14 days.'
    : 'The AI itinerary could not be verified. Try again later; no trip was saved.';
};
export async function generateItinerary(payload, options = {}) {
  const validation = validateTripPreferences(payload);
  if (!validation.valid || !itineraryDates(validation.value).length) throw new PlannerRequestError(failure(400));
  const body = await requestJson('/itineraries/generate', { ...options, timeoutMs: options.timeoutMs ?? 65000, method: 'POST', payload: validation.value, failure });
  if (!validItinerary(body, validation.value)) throw new PlannerRequestError(clientValidationFailure);
  return body;
}

export async function refineItinerary({ preferences, previous, targetDate = null, feedback, vibe = null, maxMainActivitiesPerDay = null }, options = {}) {
  const validation = validateTripPreferences(preferences);
  if (!validation.valid || !validItinerary(previous, validation.value) || !text(feedback, 1000)
    || ![null, 1, 2, 3, 4].includes(maxMainActivitiesPerDay)
    || ![null, 'relaxed', 'adventure', 'luxury', 'budget'].includes(vibe)
    || (targetDate !== null && !previous.days.some(d => d.date === targetDate))) throw new PlannerRequestError('Check your edited activities and enter feedback before regenerating.');
  const body = await requestJson('/itineraries/refine', { ...options, timeoutMs: options.timeoutMs ?? 65000, method: 'POST', payload: { preferences: validation.value, previous, targetDate, feedback, vibe, maxMainActivitiesPerDay }, failure });
  if (!validItinerary(body, validation.value) || body.vibe !== vibe) throw new PlannerRequestError(clientValidationFailure);
  if (!validRefinementSummary(body, { targetDate, maxMainActivitiesPerDay })) throw new PlannerRequestError('The returned activity limit or count summary could not be verified. Your previous plan is unchanged.');
  if (targetDate && previous.days.some(d => d.date !== targetDate && JSON.stringify(canonicalDay(d)) !== JSON.stringify(canonicalDay(body.days.find(n => n.date === d.date))))) throw new PlannerRequestError('The response changed another day. Your previous itinerary has been retained.');
  return body;
}

function ordered(value) { return Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k => [k, ordered(value[k])])) : value; }
export function canonicalDay(day) { return day ? ordered({ ...day, activities: day.activities.map(a => ({ ...a, kind: a.kind || 'unknown' })) }) : day; }

export function validRefinementSummary(body, { targetDate = null, maxMainActivitiesPerDay = null } = {}) {
  const summary = body?.refinementSummary;
  // Older servers remain usable only for requests without a new hard constraint.
  if (summary == null) return maxMainActivitiesPerDay === null;
  if (!summary || summary.scope !== (targetDate ? 'day' : 'whole') || summary.targetDate !== targetDate || summary.maxMainActivitiesPerDay !== maxMainActivitiesPerDay) return false;
  const selected = body.days.filter(d => !targetDate || d.date === targetDate);
  const otherDates = body.days.filter(d => targetDate && d.date !== targetDate).map(d => d.date);
  return Array.isArray(summary.dayCounts) && summary.dayCounts.length === selected.length
    && summary.dayCounts.every((d, i) => d.date === selected[i].date && d.mainActivityCount === selected[i].mainActivityCount
      && (maxMainActivitiesPerDay === null || (selected[i].activities.every(a => a.kind && a.kind !== 'unknown')
        && d.mainActivityCount === selected[i].activities.filter(a => a.kind === 'main').length
        && d.mainActivityCount <= maxMainActivitiesPerDay)))
    && Array.isArray(summary.unchangedDates) && JSON.stringify(summary.unchangedDates) === JSON.stringify(otherDates);
}
