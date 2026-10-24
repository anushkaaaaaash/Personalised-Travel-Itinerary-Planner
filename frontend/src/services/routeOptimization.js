import { validItinerary, canonicalDay } from './itineraries.js';
import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { PlannerRequestError, requestJson } from './readRequest.js';
const failure = () => 'The route optimization could not be verified. Your itinerary is unchanged.';
const amount = v => v === null || (typeof v === 'number' && Number.isFinite(v) && v >= 0);
const strings = a => Array.isArray(a) && a.length <= 30 && a.every(s => typeof s === 'string' && s.length <= 1000);
export function validRouteResult(body, prefs, previous, confirmations = null) {
  if (!validItinerary(body?.itinerary, prefs) || !body.routeSummary || typeof body.routeSummary.basis !== 'string' || body.routeSummary.basis.length > 1000
    || !strings(body.routeSummary.warnings) || !Array.isArray(body.routeSummary.days) || body.routeSummary.days.length !== previous.days.length) return false;
  return body.routeSummary.days.every((d, i) => {
    const original = previous.days[i], day = body.itinerary.days[i];
    if (!day || d.date !== original.date || day.date !== original.date || !['optimized', 'unchanged', 'limited', 'infeasible'].includes(d.status)
      || !strings(d.warnings) || !['beforeDistanceKm', 'afterDistanceKm', 'totalDistanceKm'].every(k => amount(d[k]))
      || !Array.isArray(d.orderedStops) || JSON.stringify(d.orderedStops) !== JSON.stringify(day.activities || [])
      || !Array.isArray(d.legs) || d.legs.length > 12 || !Array.isArray(d.timingChanges) || d.timingChanges.length > 12) return false;
    if (confirmations && !(original.activities || []).every(a => confirmations.some(c => c.date === original.date && c.id === a.id && c.title === a.title && c.latitude === a.latitude && c.longitude === a.longitude))) {
      if (d.status !== 'limited' || ['beforeDistanceKm', 'afterDistanceKm', 'totalDistanceKm'].some(k => d[k] !== null)
        || d.timingChanges.length || JSON.stringify(canonicalDay({ activities: day.activities })) !== JSON.stringify(canonicalDay({ activities: original.activities }))
        || d.legs.some(l => l.distanceKm !== null || l.estimatedMinutes !== null)) return false;
    }
    const ids = (original.activities || []).map(a => a.id);
    if (ids.length !== (day.activities || []).length || !day.activities?.every(a => {
      const old = original.activities.find(o => o.id === a.id);
      return old && (old.kind || 'unknown') === (a.kind || 'unknown') && (!old.fixedTime || old.startTime === a.startTime) && ['title', 'durationMinutes', 'notes', 'latitude', 'longitude', 'fixedTime'].every(k => old[k] === a[k]);
    })) return false;
    return d.legs.every(l => ids.includes(l.fromId) && ids.includes(l.toId) && amount(l.distanceKm) && amount(l.estimatedMinutes))
      && d.timingChanges.every(c => ids.includes(c.id) && /^\d{2}:\d{2}$/.test(c.from) && /^\d{2}:\d{2}$/.test(c.to));
  });
}
export async function optimizeItinerary({ preferences, itinerary, confirmedCoordinates = [] }, options = {}) {
  const validation = validateTripPreferences(preferences);
  if (!validation.valid || !validItinerary(itinerary, validation.value)) throw new PlannerRequestError('Check edited activities and times before optimizing.');
  if (!Array.isArray(confirmedCoordinates) || confirmedCoordinates.length > 112 || new Set(confirmedCoordinates.map(c => `${c?.date}/${c?.id}`)).size !== confirmedCoordinates.length
    || !confirmedCoordinates.every(c => c && Object.keys(c).length === 5 && ['date', 'id', 'title', 'latitude', 'longitude'].every(k => Object.hasOwn(c, k))
      && Number.isFinite(c.latitude) && Math.abs(c.latitude) <= 90 && Number.isFinite(c.longitude) && Math.abs(c.longitude) <= 180
      && itinerary.days.some(d => d.date === c.date && d.activities.some(a => a.id === c.id && a.title === c.title && a.latitude === c.latitude && a.longitude === c.longitude)))) throw new PlannerRequestError('Coordinate confirmations no longer match this plan. Review and confirm each corrected stop again.');
  const body = await requestJson('/itineraries/optimize', { ...options, method: 'POST', payload: { preferences: validation.value, itinerary, confirmedCoordinates }, failure });
  if (!validRouteResult(body, validation.value, itinerary, confirmedCoordinates)) throw new PlannerRequestError(failure());
  return body;
}
