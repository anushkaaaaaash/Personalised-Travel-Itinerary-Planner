import { isRealIsoDate, validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { isConfirmedTripId } from './api.js';
import { PlannerRequestError, requestJson } from './readRequest.js';
const failure = status => status === 503 ? 'Saved-trip storage is not configured yet.' : status === 404 ? 'This saved trip is no longer available. Refresh the history.' : status === 504 ? 'Reading saved trips timed out. Please retry.' : 'Saved trips could not be read safely. Please retry; no data was changed.';
export function validTripRecord(t) {
  if (!t || !isConfirmedTripId(t.id) || typeof t.destination !== 'string' || !t.destination.trim() || t.destination.length > 200
    || !isRealIsoDate(t.startDate) || !isRealIsoDate(t.endDate) || t.endDate < t.startDate
    || !Number.isFinite(t.budget) || t.budget <= 0 || !Number.isInteger(t.travelers) || t.travelers < 1 || t.travelers > 20
    || !(t.createdAt === null || (typeof t.createdAt === 'string' && Number.isFinite(Date.parse(t.createdAt))))) return false;
  if (t.preferencesStatus === 'unavailable') return t.preferences === null;
  if (t.preferencesStatus !== 'available' || !validateTripPreferences(t.preferences).valid) return false;
  return ['destination', 'startDate', 'endDate', 'travelers', 'budget'].every(k => t[k] === t.preferences[k]);
}
export async function listTrips({ offset = 0, ownershipEnabled = false } = {}, options = {}) {
  if (!Number.isInteger(offset) || offset < 0 || offset > 10000) throw new PlannerRequestError(failure(400));
  const body = await requestJson(`/trips?limit=20&offset=${offset}`, { ...options, failure });
  if (!body || body.scope !== (ownershipEnabled ? 'authenticated-user-saved-trips' : 'local-project-saved-trips') || body.limit !== 20 || body.offset !== offset || typeof body.hasMore !== 'boolean'
    || !Array.isArray(body.trips) || body.trips.length > 20 || !body.trips.every(validTripRecord)
    || new Set(body.trips.map(t => String(t.id))).size !== body.trips.length) throw new PlannerRequestError(failure(502));
  return body;
}
export async function getTrip(id, options = {}) {
  if (!isConfirmedTripId(id)) throw new PlannerRequestError(failure(400));
  const body = await requestJson(`/trips/${encodeURIComponent(id)}`, { ...options, failure });
  if (!validTripRecord(body?.trip) || String(body.trip.id) !== String(id)) throw new PlannerRequestError(failure(502));
  return body.trip;
}
