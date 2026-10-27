import { COST_LABELS, validActivities, itineraryDates } from './itineraries.js';
import { INTEREST_OPTIONS } from '../../../shared/tripPreferences.mjs';
const text = (v, max) => typeof v === 'string' && v.trim().length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(v);
const number = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
/** Adaptive-only endpoint exception; never treat an intermediate section boundary as a trip endpoint.
 * Keep ordinary itinerary identity/date/budget/timeline/interest checks unchanged.
 * Explicit transfers totaling >=120 minutes permit fewer main activities only on original first/last dates.
 */
export function validAdaptiveSectionItinerary(b, p, original) {
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
    const endpoint = d && [original.startDate,original.endDate].includes(d.date);
    const substantialTransfer = Array.isArray(d?.activities) && d.activities.filter(a=>a?.kind==='transfer').reduce((sum,a)=>sum+a.durationMinutes,0)>=120;
    const minimum = endpoint && substantialTransfer ? 0 : pace[0];
    if (!d || !validActivities(d.activities) || d.mainActivityCount > d.activities.length || d.date !== dates[i] || !['morning', 'afternoon', 'evening', 'dining'].every(k => text(d[k], 700))
      || !['dietaryNotes', 'mobilityNotes', 'transitAndRest'].every(k => text(d[k], 500))
      || !Number.isInteger(d.mainActivityCount) || d.mainActivityCount < minimum || d.mainActivityCount !== d.activities.filter(a=>a.kind==='main').length || d.mainActivityCount > pace[1]
      || !Array.isArray(d.interestTags) || d.interestTags.length > 8 || new Set(d.interestTags).size !== d.interestTags.length
      || !d.interestTags.every(t => INTEREST_OPTIONS.some(o => o.id === t))
      || (p.interests.length && !d.interestTags.some(t => p.interests.includes(t)))
      || !d.costs || Object.keys(d.costs).length !== 5 || !Object.keys(COST_LABELS).every(k => number(d.costs[k]))) return false;
    total += Object.values(d.costs).reduce((a, v) => a + v, 0); return true;
  })) return false;
  const close = (a, b) => Math.abs(a - b) < 0.005;
  return total <= p.budget + 0.000001 && close(total, b.estimatedTotalGroupCost) && close(p.budget - total, b.remainingBudget);
}
