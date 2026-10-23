const { getSupabase: defaultGetSupabase } = require('../config/supabase');
const tripPreferences = import('../../../shared/tripPreferences.mjs');

function storageError(code = 'TRIP_SAVE_FAILED') {
  const error = new Error(code === 'TRIP_STORAGE_NOT_CONFIGURED'
    ? 'Trip storage has not been configured.'
    : 'Trip saving could not be confirmed.');
  error.code = code;
  return error;
}

function isTripIdentity(id) {
  if (typeof id === 'number') return Number.isSafeInteger(id) && id > 0;
  // A bigint delivered as decimal text must remain text to avoid precision loss.
  return typeof id === 'string' && /^[1-9]\d{0,18}$/.test(id)
    && BigInt(id) <= 9223372036854775807n;
}

/**
 * Mapping confirmed against the existing public.trips table; no schema changes.
 * `preferences` is text, not jsonb. Identity id and created_at use DB defaults.
 * The client is requested only when a validated trip is actually being saved.
 */
function createTripService({ getSupabase = defaultGetSupabase } = {}) {
  return async function saveTrip(preferences) {
    const { validateTripPreferences } = await tripPreferences;
    const validated = validateTripPreferences(preferences);
    if (!validated.valid) {
      const error = new Error('Trip preferences are invalid.');
      error.code = 'INVALID_TRIP_PREFERENCES';
      throw error;
    }

    const value = validated.value;
    const row = {
      destination: value.destination,
      start_date: value.startDate,
      end_date: value.endDate,
      budget: value.budget,
      travelers: value.travelers,
      preferences: JSON.stringify({
        departureCity: value.departureCity,
        currency: value.currency,
        interests: value.interests,
        dietaryNeeds: value.dietaryNeeds,
        travelPace: value.travelPace,
      }),
    };

    try {
      const { data, error } = await getSupabase()
        .from('trips')
        .insert(row)
        .select('id')
        .single();

      if (error || !data || !isTripIdentity(data.id)) throw storageError();
      return { id: data.id };
    } catch (error) {
      // Never forward a raw database/network error, SQL detail, or secret.
      if (error && error.code === 'TRIP_STORAGE_NOT_CONFIGURED') {
        throw storageError('TRIP_STORAGE_NOT_CONFIGURED');
      }
      throw storageError();
    }
  };
}

const saveTrip = createTripService();

module.exports = { saveTrip, createTripService };
