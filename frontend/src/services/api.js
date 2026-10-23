import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';

const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export class TripApiError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'TripApiError';
    this.code = code;
  }
}

export function isConfirmedTripId(id) {
  return (
    (typeof id === 'string' && id.trim() === id && id.length > 0 && id.length <= 200 && !/[\u0000-\u001f\u007f]/.test(id)) ||
    (Number.isSafeInteger(id) && id > 0)
  );
}

function statusError(status) {
  if (status === 400 || status === 422) {
    return new TripApiError('Please check your trip details and try again.', 'VALIDATION_ERROR');
  }
  if (status === 413) {
    return new TripApiError('These trip details are too large. Please shorten them and try again.', 'REQUEST_TOO_LARGE');
  }
  if (status === 401 || status === 403 || status === 503) {
    return new TripApiError('Trip saving is not ready. Please check the backend setup and try again.', 'STORAGE_UNAVAILABLE');
  }
  return new TripApiError('We could not confirm your preferences were saved. Please check before trying again.', 'SAVE_UNCONFIRMED');
}

/** Save preference data only; this endpoint does not generate an itinerary. */
export async function createTrip(payload, {
  fetchImpl = globalThis.fetch,
  baseUrl = API_BASE_URL,
  signal,
  timeoutMs = 15000,
} = {}) {
  const validation = validateTripPreferences(payload);
  if (!validation.valid) {
    throw new TripApiError('Please check your trip details and try again.', 'VALIDATION_ERROR');
  }
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    if (controller.signal.aborted) throw new DOMException('Canceled', 'AbortError');
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/trips`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(validation.value),
      signal: controller.signal,
    });
    if (response.status !== 201) throw statusError(response.status);
    let body;
    try {
      body = await response.json();
    } catch {
      throw statusError(500);
    }
    if (controller.signal.aborted) throw new DOMException('Canceled', 'AbortError');
    if (!body || !body.trip || !isConfirmedTripId(body.trip.id)) {
      throw statusError(500);
    }
    return { id: body.trip.id };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timedOut) {
      throw new TripApiError('The save request timed out. It may have been saved; please check before trying again.', 'TIMEOUT');
    }
    if (error instanceof TripApiError) throw error;
    throw new TripApiError('The planner service could not be reached. Start the backend, then check whether this trip was saved before retrying.', 'NETWORK_ERROR');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

// Retained for explicit diagnostics, not as a substitute for saving a trip.
export async function getHealth() {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) throw new Error('Health check failed');
  return response.json();
}
