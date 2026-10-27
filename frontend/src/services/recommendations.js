import { AI_REQUEST_TIMEOUT_MS } from './aiRequest.js';
import { sessionFetch } from './session.js';
import { validateTripPreferences, INTEREST_OPTIONS } from '../../../shared/tripPreferences.mjs';
const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
export class RecommendationError extends Error {}
// Pydantic response bounds count Unicode code points, not UTF-16 units.
const text = (value, max, empty = false) => typeof value === 'string' && Array.from(value).length <= max
  && !/[\uD800-\uDFFF]/u.test(value)
  && (empty || value.trim().length > 0) && !/[\u0000-\u001f\u007f]/.test(value);
export function validRecommendations(body, prefs) {
  if (!body || body.source !== 'ai' || !text(body.provider, 100) || !text(body.model, 100)
    || body.destination !== prefs.destination || body.currency !== prefs.currency
    || !Array.isArray(body.recommendations) || body.recommendations.length < 3 || body.recommendations.length > 12
    || !Array.isArray(body.warnings) || body.warnings.length > 8 || !body.warnings.every((w) => text(w, 500))) return false;
  if (!['attraction', 'activity', 'dining'].every((category) => body.recommendations.some((item) => item?.category === category))) return false;
  const ids = new Set();
  return body.recommendations.every((item) => {
    if (!item || !text(item.id, 80) || ids.has(item.id)) return false;
    ids.add(item.id);
    return ['attraction', 'activity', 'dining'].includes(item.category)
      && text(item.name, 160) && text(item.description, 800) && text(item.whyRecommended, 500)
      && typeof item.estimatedGroupCost === 'number' && Number.isFinite(item.estimatedGroupCost)
      && item.estimatedGroupCost >= 0 && item.estimatedGroupCost <= prefs.budget
      && ['', 'budget', 'comfort', 'luxury'].includes(item.travelStyle)
      && (!prefs.travelStyle || item.travelStyle === prefs.travelStyle)
      && Array.isArray(item.interestTags) && item.interestTags.length <= 8
      && new Set(item.interestTags).size === item.interestTags.length
      && item.interestTags.every((tag) => INTEREST_OPTIONS.some(({ id }) => id === tag))
      && (!prefs.interests.length || item.interestTags.some((tag) => prefs.interests.includes(tag)))
      && text(item.dietaryNotes, 500) && text(item.mobilityNotes, 500);
  });
}
const failure = (status) => new RecommendationError(status === 503
  ? 'AI recommendations are not configured yet. Your saved trip is unchanged.'
  : status === 504 ? 'AI recommendations timed out. Try again later; your saved trip is unchanged.'
  : status === 400 || status === 422 ? 'Check your trip preferences before generating recommendations.'
  : 'AI recommendations could not be verified. Please try again later.');
export async function getRecommendations(payload, { fetchImpl = sessionFetch, baseUrl = API_BASE_URL, signal, timeoutMs = AI_REQUEST_TIMEOUT_MS } = {}) {
  const validated = validateTripPreferences(payload);
  if (!validated.valid) throw failure(400);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  let timeout = false;
  const timer = setTimeout(() => { timeout = true; controller.abort(); }, timeoutMs);
  try {
    if (controller.signal.aborted) throw new Error('Aborted');
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/recommendations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(validated.value), signal: controller.signal,
    });
    if (response.status !== 200) throw failure(response.status);
    const body = await response.json();
    if (controller.signal.aborted) throw new Error('Aborted');
    if (!validRecommendations(body, validated.value)) throw failure(502);
    return body;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timeout) throw failure(504);
    if (error instanceof RecommendationError) throw error;
    throw failure(502);
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}
