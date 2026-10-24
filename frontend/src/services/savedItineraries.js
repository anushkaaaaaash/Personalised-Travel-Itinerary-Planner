import { requestJson, PlannerRequestError } from './readRequest.js';
import { validItinerary } from './itineraries.js';
import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const version = value => Number.isSafeInteger(value) && value > 0 && value < 2147483647;
const failure = status => status === 401 ? 'Sign in to access your saved full itineraries.'
  : status === 403 ? 'You do not have access to this saved itinerary.'
  : status === 404 ? 'This saved itinerary is not available.'
  : status === 409 ? 'This saved record changed or was deleted elsewhere. Reload before updating or deleting.'
  : status === 503 ? 'Full itinerary storage requires approved database and account setup.'
  : status === 400 || status === 413 || status === 422 ? 'Check the complete plan, title and preferences before saving.'
  : 'The storage outcome is unconfirmed. Check saved history before retrying. Your local plan is retained.';
const invalid = () => new PlannerRequestError('The saved record could not be verified. Your local plan is retained.');
const fields = ['status','destination','currency','travelStyle','travelPace','explanation','days','warnings','vibe'];
export function snapshot(title, preferences, itinerary) {
  const p = validateTripPreferences(preferences);
  if (!p.valid || !validItinerary(itinerary,p.value) || itinerary.status !== 'planned'
    || typeof title !== 'string' || !title.trim() || title.trim().length > 120 || /[\u0000-\u001f\u007f]/.test(title)) throw invalid();
  return { title: title.trim(), preferences: p.value, itinerary: Object.fromEntries(fields.filter(k => itinerary[k] !== undefined).map(k => [k,itinerary[k]])) };
}
function meta(item) {
  return item && uuid(item.id) && version(item.version) && typeof item.title === 'string' && item.title.trim().length > 0 && item.title.length <= 120
    && typeof item.createdAt === 'string' && Number.isFinite(Date.parse(item.createdAt)) && typeof item.updatedAt === 'string' && Number.isFinite(Date.parse(item.updatedAt));
}
function detail(item) {
  const p = validateTripPreferences(item?.preferences);
  if (!meta(item) || item.persisted !== true || !p.valid || !validItinerary(item.itinerary,p.value) || item.itinerary.status !== 'planned') throw invalid();
  return item;
}
export async function savedRequest({ action, id, record, expectedVersion, offset = 0 }, options = {}) {
  if (action !== 'list' && !uuid(id)) throw invalid();
  let path='/saved-itineraries', method='GET', payload;
  if (action === 'list') {
    if (!Number.isInteger(offset) || offset < 0 || offset > 10000) throw invalid();
    path += `?offset=${offset}`;
  } else if (action === 'load') path += `/${id}`;
  else if (action === 'create') { method='POST'; payload={...record,id}; }
  else if (action === 'update' || action === 'delete') {
    if (!version(expectedVersion)) throw invalid();
    path += `/${id}`; method=action === 'update' ? 'PUT' : 'DELETE';
    payload={...(action === 'update' ? record : {}),version:expectedVersion};
  } else throw invalid();
  if (action === 'create' || action === 'update') {
    // The caller must construct a validated snapshot, not send session or provider metadata.
    if (!record || Object.keys(record).sort().join() !== 'itinerary,preferences,title') throw invalid();
  }
  const body=await requestJson(path,{...options,method,payload,failure});
  if (action === 'list') {
    if (!body || !Array.isArray(body.items) || body.items.length > 20 || !body.items.every(meta) || new Set(body.items.map(i=>i.id)).size !== body.items.length || typeof body.hasMore !== 'boolean' || body.offset !== offset) throw invalid();
    return body;
  }
  if (action === 'delete') {
    if (!body || body.deleted !== true || body.id !== id || body.version !== expectedVersion) throw invalid();
    return body;
  }
  detail(body);
  if (body.id !== id || (action === 'create' && body.version !== 1) || (action === 'update' && body.version !== expectedVersion + 1)) throw invalid();
  return body;
}

export function createSavedOperation(onState, request = savedRequest) {
  let active=null, disposed=false;
  return {
    busy:()=>Boolean(active),
    async run(input) {
      if (disposed || active) return {ignored:true};
      const controller=new AbortController(); active=controller;
      onState({busy:true,error:''});
      try {
        const result=await request(input,{signal:controller.signal});
        if (disposed || active!==controller || controller.signal.aborted) return {ignored:true};
        onState({busy:false,error:''}); return {result};
      } catch(error) {
        if (disposed || active!==controller || controller.signal.aborted) return {ignored:true};
        const message=error instanceof PlannerRequestError ? error.message : failure(502);
        onState({busy:false,error:message}); return {error:message};
      } finally { if(active===controller)active=null; }
    },
    dispose(){disposed=true;active?.abort();active=null;},
  };
}
