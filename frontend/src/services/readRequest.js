import { sessionFetch } from './session.js';
/** Cancellable, duplicate-safe read/generation request. Never writes preferences. */
export class PlannerRequestError extends Error {
  constructor(message, { status, code } = {}) {
    super(message);
    if (Number.isInteger(status) && status >= 400 && status <= 599) this.status = status;
    if (['VALIDATION_ERROR','REQUEST_TOO_LARGE'].includes(code)) this.code = code;
  }
}
export function createReadRequest({ request, onStateChange }) {
  let active = null;
  let disposed = false;
  const publish = (state) => { if (!disposed) onStateChange(state); };
  const empty = () => ({ loading: false, error: '', result: null });
  return {
    isBusy: () => Boolean(active),
    reset() { active?.abort(); active = null; publish(empty()); },
    async submit(payload) {
      if (disposed || active) return { ignored: true };
      const controller = new AbortController(); active = controller;
      publish({ loading: true, error: '', result: null });
      try {
        const result = await request(payload, { signal: controller.signal });
        if (disposed || controller.signal.aborted || active !== controller) return { ignored: true };
        publish({ loading: false, error: '', result });
        return { result };
      } catch (error) {
        if (disposed || controller.signal.aborted || active !== controller) return { ignored: true };
        const message = error instanceof PlannerRequestError ? error.message : 'The response could not be verified. Please try again.';
        publish({ loading: false, error: message, result: null });
        return { error: message };
      } finally { if (active === controller) active = null; }
    },
    dispose() { disposed = true; active?.abort(); active = null; },
  };
}

const DIAGNOSTIC_CODES = new Set(['AI_SCHEMA_REJECTED', 'AI_INVALID_RESPONSE', 'AI_OUTPUT_TRUNCATED', 'AI_RATE_LIMITED', 'REFINEMENT_PACE_CONFLICT', 'REFINEMENT_FIXED_CONFLICT', 'VALIDATION_ERROR', 'REQUEST_TOO_LARGE']);
const DIAGNOSTIC_REASONS = new Set(['FORMAT_SCHEMA', 'PREFERENCE_MISMATCH', 'DATE_COVERAGE', 'PACE', 'BUDGET', 'TIMELINE', 'VIBE_MISMATCH', 'FIXED_COMMITMENT']);
// Only these enums cross the transport boundary. Never pass through server messages,
// provider output, arbitrary fields, or unknown codes/reasons to the UI.
function safeDiagnostic(body) {
  const error = body?.error;
  const code = DIAGNOSTIC_CODES.has(error?.code) ? error.code : undefined;
  const reason = code === 'AI_INVALID_RESPONSE' && DIAGNOSTIC_REASONS.has(error?.reason) ? error.reason : undefined;
  return { kind: 'http', ...(code ? { code } : {}), ...(reason ? { reason } : {}) };
}

export async function requestJson(path, { method = 'GET', payload, fetchImpl = sessionFetch,
  baseUrl = (import.meta.env?.VITE_API_BASE_URL || '/api'), signal, timeoutMs = 15000, failure } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; abort(); }, timeoutMs);
  try {
    if (controller.signal.aborted) throw new Error('Canceled');
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}${path}`, {
      method, headers: { Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json' } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {}), signal: controller.signal,
    });
    if (response.status !== 200) {
      let diagnostic = { kind: 'http' };
      try { diagnostic = safeDiagnostic(await response.json()); } catch { /* Unknown error body stays masked. */ }
      if (controller.signal.aborted) throw new Error('Canceled');
      throw new PlannerRequestError(failure(response.status, diagnostic), { status: response.status, code: diagnostic.code });
    }
    let body;
    try { body = await response.json(); }
    catch { throw new PlannerRequestError(failure(502, { kind: 'invalid_json' })); }
    if (controller.signal.aborted) throw new Error('Canceled');
    return body;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timedOut) throw new PlannerRequestError(failure(504, { kind: 'timeout' }));
    if (error instanceof PlannerRequestError) throw error;
    throw new PlannerRequestError(failure(502, { kind: 'network' }));
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}
