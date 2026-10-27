/** Default-off async planning contract. Never retries a create automatically. */
import { sessionFetch } from './session.js';
import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { validItinerary, itineraryDates } from './itineraries.js';
export const planningJobsEnabled = import.meta.env?.DEV === true && import.meta.env?.VITE_PLANNING_JOBS_PREVIEW === 'true';
const uuid = value => typeof value === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const states = new Set(['queued', 'submitting', 'running', 'succeeded', 'failed', 'submission_unknown', 'cancelled', 'expired']);
export class PlanningJobError extends Error {
  constructor(code, message) { super(message); this.name = 'PlanningJobError'; this.code = code; }
}
export function validateJobSnapshot(value, preferences, { id, requestId } = {}) {
  if (!value || !uuid(value.id) || !uuid(value.requestId) || !states.has(value.status)
    || (id && value.id !== id) || (requestId && value.requestId !== requestId)
    || !Number.isFinite(Date.parse(value.createdAt)) || !Number.isFinite(Date.parse(value.expiresAt))
    || Date.parse(value.expiresAt) <= Date.parse(value.createdAt)
    || (value.status === 'succeeded' ? !validItinerary(value.result, preferences) : value.result !== null)) {
    throw new PlanningJobError('JOB_INVALID_RESPONSE', 'This plan could not be checked. Please check again shortly.');
  }
  // Whitelist fields and safe codes; never display server error messages.
  return { id: value.id, requestId: value.requestId, status: value.status,
    result: value.result, createdAt: value.createdAt, expiresAt: value.expiresAt,
    error: ['failed', 'submission_unknown', 'expired'].includes(value.status)
      ? { code: value.status === 'failed' && value.error?.code === 'JOB_TRAVEL_CONFLICT' ? 'JOB_TRAVEL_CONFLICT' : value.status === 'expired' ? 'JOB_EXPIRED' : value.status === 'submission_unknown' ? 'JOB_SUBMISSION_UNCONFIRMED' : 'JOB_FAILED' } : null };
}
export async function itineraryEvidenceDigest(result) {
  const canonical = value => {
    if (value === null) return ['null'];
    if (typeof value === 'boolean') return ['bool', value];
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new PlanningJobError('JOB_INVALID_EVIDENCE', 'These travel checks could not be confirmed.');
      const buffer = new ArrayBuffer(8); new DataView(buffer).setFloat64(0, value, false);
      return ['number', [...new Uint8Array(buffer)].map(n => n.toString(16).padStart(2, '0')).join('')];
    }
    if (typeof value === 'string') return ['string', value];
    if (Array.isArray(value)) return ['array', value.map(canonical)];
    if (value && typeof value === 'object') return ['object', Object.keys(value).sort().map(key => [key, canonical(value[key])])];
    throw new PlanningJobError('JOB_INVALID_EVIDENCE', 'These travel checks could not be confirmed.');
  };
  const hash = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(result))));
  return [...new Uint8Array(hash)].map(n => n.toString(16).padStart(2, '0')).join('');
}

export async function validateBoundEvidence(envelope, result) {
  if (envelope === null || envelope === undefined) return null;
  const fail = () => { throw new PlanningJobError('JOB_INVALID_EVIDENCE', 'These travel checks could not be confirmed.'); };
  if (!result || envelope.version !== 1 || typeof envelope.destinationId !== 'string' || !envelope.destinationId
    || typeof envelope.timeZone !== 'string' || !Array.isArray(envelope.assessments) || envelope.assessments.length > 448
    || !/^[a-f0-9]{64}$/.test(envelope.itineraryDigest)) return fail();
  try { new Intl.DateTimeFormat('en', { timeZone: envelope.timeZone }); } catch { return fail(); }
  const hash = await itineraryEvidenceDigest(result);
  if (hash !== envelope.itineraryDigest) return fail();
  const subjects = new Set(result.days.flatMap(day => day.activities.map(activity => `${day.date}/${activity.id}`)));
  const kinds = new Set(['opening_hours','closure','route','weather','transit','booking']);
  for (const item of envelope.assessments) {
    const scope = item?.scope;
    if (!scope || scope.destinationId !== envelope.destinationId || scope.timeZone !== envelope.timeZone
      || !subjects.has(`${scope.localDate}/${scope.subjectId}`) || !kinds.has(scope.kind)
      || !['verified','unverified','stale','unavailable'].includes(item.status)
      || !['unknown','none','caution','blocker'].includes(item.severity)
      || typeof item.summary !== 'string' || typeof item.fallback !== 'string') return fail();
    if (item.status === 'verified') {
      let source; try { source = new URL(item.sourceURL); } catch { return fail(); }
      if (source.protocol !== 'https:' || source.username || source.password || !Number.isFinite(Date.parse(item.checkedAt))
        || !Number.isFinite(Date.parse(item.expiresAt)) || Date.parse(item.checkedAt) > Date.now()
        || !item.validFrom || !item.validUntil || scope.localDate < item.validFrom || scope.localDate > item.validUntil) return fail();
    }
  }
  return structuredClone(envelope);
}

export function jobMessage(job) {
  if (job.error?.code === 'JOB_TRAVEL_CONFLICT') return 'A checked travel restriction conflicts with this plan. Try different dates or stops.';
  return { queued: 'Your trip is in line.', submitting: 'Starting your trip plan.', running: 'Putting your trip together.',
    succeeded: 'Your trip is ready.', failed: 'We could not finish this plan. You can try again.',
    submission_unknown: 'We could not confirm whether planning started. Check again before starting another plan.',
    cancelled: 'Planning stopped.', expired: 'This planning session has expired. Start a new plan when you are ready.' }[job.status] || '';
}
export function createPlanningJobsClient({ enabled = planningJobsEnabled, fetchImpl = sessionFetch,
  baseUrl = (import.meta.env?.VITE_API_BASE_URL || '/api'), timeoutMs = 15000 } = {}) {
  async function request(path, method, payload, preferences, expected, signal) {
    if (!enabled) throw new PlanningJobError('JOB_DISABLED', 'This planning option is not available.');
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, timeoutMs);
    try {
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/planning-jobs${path}`, {
        method, headers: { Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json' } : {}) },
        ...(payload ? { body: JSON.stringify(payload) } : {}), signal: controller.signal,
      });
      if (![200, 202].includes(response.status)) {
        const [code, message] = [400,403,413,422,429].includes(response.status) ? ['JOB_REJECTED', response.status === 429 ? 'Please wait a moment before starting another plan.' : 'Check your trip details before starting a new plan.']
          : response.status === 401 ? ['AUTH_REQUIRED', 'Sign in again to check your trip.']
          : response.status === 404 ? ['JOB_NOT_FOUND', 'This planning session is no longer available.']
          : response.status === 409 ? ['JOB_CONFLICT', 'These details changed. Start a new planning session.']
          : ['JOB_UNAVAILABLE', 'Your plan could not be checked. Please check again shortly.'];
        throw new PlanningJobError(code, message);
      }
      const body = await response.json();
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (expected.context) {
        const checked = body?.preferences === null && body?.job?.status === 'expired'
          ? { valid: true, value: null } : validateTripPreferences(body?.preferences || {});
        if (!checked.valid) throw new PlanningJobError('JOB_INVALID_RESPONSE', 'This planning session could not be checked.');
        const job = validateJobSnapshot(body.job, checked.value, expected);
        job.evidence = await validateBoundEvidence(body.job?.evidence, job.result);
        return { preferences: checked.value, job };
      }
      const job = validateJobSnapshot(body, preferences, expected);
      job.evidence = await validateBoundEvidence(body.evidence, job.result);
      return job;
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (error instanceof PlanningJobError) throw error;
      throw new PlanningJobError(method === 'POST' ? 'JOB_OUTCOME_UNCONFIRMED' : 'JOB_UNAVAILABLE',
        method === 'POST' ? 'We could not confirm that change. Check this planning session before trying again.'
          : 'Your plan could not be checked. Please check again shortly.');
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
  return {
    start(preferences, requestId, { signal } = {}) {
      const checked = validateTripPreferences(preferences);
      if (!checked.valid || !uuid(requestId) || !itineraryDates(checked.value).length) throw new PlanningJobError('VALIDATION_ERROR', 'Check your trip details.');
      return request('', 'POST', { requestId, preferences: checked.value }, checked.value, { requestId }, signal);
    },
    resume(id, { signal } = {}) {
      if (!uuid(id)) throw new PlanningJobError('VALIDATION_ERROR', 'This planning session is not valid.');
      return request(`/${id}/context`, 'GET', null, null, { id, context: true }, signal);
    },
    resumeRequest(requestId, { signal } = {}) {
      if (!uuid(requestId)) throw new PlanningJobError('VALIDATION_ERROR', 'This planning session is not valid.');
      return request(`/requests/${requestId}/context`, 'GET', null, null, { requestId, context: true }, signal);
    },
    findRequest(requestId, preferences, { signal } = {}) {
      if (!uuid(requestId)) throw new PlanningJobError('VALIDATION_ERROR', 'This planning session is not valid.');
      return request(`/requests/${requestId}`, 'GET', null, preferences, { requestId }, signal);
    },
    get(id, preferences, { signal } = {}) {
      if (!uuid(id)) throw new PlanningJobError('VALIDATION_ERROR', 'This planning session is not valid.');
      return request(`/${id}`, 'GET', null, preferences, { id }, signal);
    },
    cancel(id, preferences, { signal } = {}) {
      if (!uuid(id)) throw new PlanningJobError('VALIDATION_ERROR', 'This planning session is not valid.');
      return request(`/${id}/cancel`, 'POST', {}, preferences, { id }, signal);
    },
  };
}
