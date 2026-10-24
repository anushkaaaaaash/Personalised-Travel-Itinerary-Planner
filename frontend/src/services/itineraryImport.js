import { validItinerary, canonicalDay } from './itineraries.js';
import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { PlannerRequestError } from './readRequest.js';
export const MAX_IMPORT_BYTES = 131072;
const fail = () => new PlannerRequestError('This file is not a valid itinerary export. Choose a planner JSON export up to 128 KiB; your current plan is unchanged.');
const keys = (value, allowed) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(k => allowed.includes(k));
const top = ['status','destination','currency','travelStyle','travelPace','explanation','days','warnings','vibe','source','provider','model','saved','estimatedTotalGroupCost','remainingBudget','refinementSummary'];
export function parseItineraryImport(contents) {
  if (typeof contents !== 'string' || new TextEncoder().encode(contents).length > MAX_IMPORT_BYTES) throw fail();
  let body;
  try { body = JSON.parse(contents); } catch { throw fail(); }
  if (!keys(body, [...top, 'userEdited','notice','preferences']) || body.status !== 'planned'
    || !Array.isArray(body.days) || body.days.length < 1 || body.days.length > 14
    || (body.userEdited !== undefined && typeof body.userEdited !== 'boolean')
    || (body.notice !== undefined && (typeof body.notice !== 'string' || body.notice.length > 1000))) throw fail();
  for (const d of body.days) {
    if (!keys(d, ['date','morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest','mainActivityCount','interestTags','costs','activities'])
      || !Array.isArray(d.activities) || !d.activities.every(a => keys(a, ['id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind']))) throw fail();
  }
  const knownPreferences = { destination: body.destination, startDate: body.days[0].date, endDate: body.days.at(-1).date,
    budget: body.estimatedTotalGroupCost + body.remainingBudget, currency: body.currency, travelStyle: body.travelStyle, travelPace: body.travelPace };
  const validated = body.preferences === undefined ? null : validateTripPreferences(body.preferences);
  if (validated && !validated.valid) throw fail();
  const context = validated?.value || { ...knownPreferences, interests: [] };
  if (!Number.isFinite(knownPreferences.budget) || knownPreferences.budget <= 0 || !validItinerary(body, context)) throw fail();
  // Never trust imported prose as a verified constraint summary. Keep only the plan
  // schema; current structured counts are shown directly by the day cards.
  const itinerary = Object.fromEntries(top.filter(k => k !== 'refinementSummary' && Object.hasOwn(body, k)).map(k => [k, body[k]]));
  itinerary.days = itinerary.days.map(canonicalDay);
  return { itinerary, preferences: validated?.value || null, knownPreferences, userEdited: body.userEdited === true };
}
export async function readItineraryFile(file) {
  if (!file || typeof file.size !== 'number' || file.size > MAX_IMPORT_BYTES || file.size === 0 || typeof file.text !== 'function') throw fail();
  let contents;
  try { contents = await file.text(); } catch { throw fail(); }
  return parseItineraryImport(contents);
}
