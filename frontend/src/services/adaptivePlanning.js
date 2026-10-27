import { sessionFetch } from './session.js';
import { validateTripPreferences, isRealIsoDate } from '../../../shared/tripPreferences.mjs';
import { validItinerary } from './itineraries.js';
export const adaptiveId = value => typeof value === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const knownErrors = new Set(['SECTION_SUBMISSION_UNCONFIRMED','SECTION_PROVIDER_REJECTED','SECTION_DEADLINE_REACHED','SECTION_POLL_UNCONFIRMED','SECTION_RESPONSE_MISMATCH','SECTION_OUTPUT_LIMIT','SECTION_PROVIDER_INCOMPLETE','SECTION_PROVIDER_FAILED','SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED','SECTION_INVALID_RESULT','SECTION_CONTINUITY_CONFLICT','SECTION_RETURN_MISSING','SECTION_REST_CONFLICT','SECTION_TRAVEL_DOUBLE_COUNT','SECTION_BUDGET_EXCEEDED','SECTION_INVALID_COST','SECTION_CHECKPOINT_INVALID','SECTION_STRATEGY_INVALID','SECTION_STRATEGY_CONFLICT','SECTION_TRANSFER_MISSING','SECTION_REPEAT_CONFLICT']);
export const validAdaptivePolicy = value => value?.sectionDays === 3 && Number.isInteger(value.maxSubmissionsPerRun) && value.maxSubmissionsPerRun >= 1 && value.maxSubmissionsPerRun <= 12;
const integer = value => Number.isSafeInteger(value) && value >= 0;
const safeText = (value, max=500) => typeof value === 'string' && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value);
export class AdaptivePlanningError extends Error {
  constructor(code, message, { confirmed=false }={}) { super(message); this.code=code; this.confirmed=confirmed; }
}
const invalid = () => { throw new AdaptivePlanningError('ADAPTIVE_INVALID_RESPONSE','This planning checkpoint could not be verified. Check again before continuing.'); };
/** Verify each bounded page, never construct an unbounded whole-trip itinerary. */
export function validateAdaptivePage(body, { id, requestId, afterSequence=0 }={}) {
  const p=body?.plan;
  if(p?.status==='expired' && body.preferences===null && adaptiveId(p.id) && adaptiveId(p.requestId) && (!id || p.id===id) && (!requestId || p.requestId===requestId) && Array.isArray(body.sections) && body.sections.length===0 && body.nextCursor===null) return {plan:{id:p.id,requestId:p.requestId,status:'expired',activeSection:null},preferences:null,sections:[],nextCursor:null};
  const checked=validateTripPreferences(body?.preferences);
  if(!checked.valid || !p || !adaptiveId(p.id) || !adaptiveId(p.requestId) || (id && id!==p.id) || (requestId && requestId!==p.requestId)
    || !['active','paused','completed','cancelled','expired'].includes(p.status)
    || !['completedDays','totalDays','remainingCreates','spentCents','totalBudgetCents'].every(key=>integer(p[key]))
    || p.completedDays>p.totalDays || p.remainingCreates>12 || !Number.isInteger(p.runAllowance) || p.runAllowance<1 || p.runAllowance>12 || p.remainingCreates>p.runAllowance || p.spentCents>p.totalBudgetCents
    || !Number.isFinite(Date.parse(p.expiresAt)) || !(p.pauseReason===null || safeText(p.pauseReason,100))) return invalid();
  const expectedDays=(Date.parse(`${checked.value.endDate}T00:00:00Z`)-Date.parse(`${checked.value.startDate}T00:00:00Z`))/86400000+1;
  if(p.estimatedSections!==Math.ceil(expectedDays/3) || p.totalBudgetCents!==Math.round(checked.value.budget*100) || p.totalDays!==expectedDays || (p.status==='completed' && p.completedDays!==p.totalDays)) return invalid();
  for(const field of ['storageLimitBytes','storageUsedBytes','globalStorageLimitBytes']) if(p[field]!==undefined&&!integer(p[field]))return invalid();
  if(p.storagePauseScope!==undefined && ![null,'plan','global'].includes(p.storagePauseScope))return invalid();
  let activeSection=null;
  if(p.activeSection!==null) {
    const s=p.activeSection;
    if(!s || !adaptiveId(s.id) || !['queued','submitting','running','succeeded','failed','submission_unknown','cancelled'].includes(s.status)
      || !(s.errorCode===null || safeText(s.errorCode,100))) return invalid();
    activeSection={id:s.id,status:s.status,errorCode:s.errorCode===null?null:knownErrors.has(s.errorCode)?s.errorCode:'REQUEST_FAILED',failureDetails:null};
    if(s.failureDetails) {
      const details=s.failureDetails;
      if(details.applicability!=='proposed' || !safeText(details.explanation,1000) || !details.explanation.trim() || !Array.isArray(details.recommendations) || !details.recommendations.length || details.recommendations.length>3) return invalid();
      const fields=['budget','travelPace','destination','departureCity','mobilityConcerns','dietaryNeeds'];
      if(!details.recommendations.every(r=>fields.includes(r?.field)&&safeText(r.reason)&&r.reason.trim()&&safeText(r.suggestion)&&r.suggestion.trim())) return invalid();
      activeSection.failureDetails={applicability:'proposed',explanation:details.explanation || '',recommendations:details.recommendations.map(({field,reason,suggestion})=>({field,reason,suggestion}))};
    }
  }
  if(!Array.isArray(body.sections)||body.sections.length>3) return invalid();
  let sequence=afterSequence;
  const ids=new Set();
  const sections=body.sections.map(s=>{
    if(!s || !adaptiveId(s.id) || ids.has(s.id) || !integer(s.sequence) || s.sequence<=sequence
      || !isRealIsoDate(s.startDate)||!isRealIsoDate(s.endDate)||s.startDate>s.endDate
      || s.startDate<checked.value.startDate || s.endDate>checked.value.endDate) return invalid();
    const days=(Date.parse(s.endDate)-Date.parse(s.startDate))/86400000+1;
    const c=s.checkpoint;
    if(days>3 || !c || !integer(c.spentCents) || c.spentCents>p.totalBudgetCents || !safeText(c.startLocation,200)||!safeText(c.endLocation,200)
      || !c.itinerary || !Number.isFinite(c.itinerary.remainingBudget)) return invalid();
    const budget=c.itinerary.estimatedTotalGroupCost+c.itinerary.remainingBudget;
    if(!validItinerary(c.itinerary,{...checked.value,startDate:s.startDate,endDate:s.endDate,budget})
      || Math.abs(c.itinerary.estimatedTotalGroupCost*100-c.spentCents)>.001
      || c.provenance?.provider!=='openai'||c.provenance?.model!=='gpt-6-luna'||c.provenance?.validationVersion!=='adaptive-section-v1') return invalid();
    if(c.journeyStrategy!==undefined){
      const strategy=c.journeyStrategy;
      if(!strategy || Object.keys(strategy).sort().join(',')!=='stays,summary' || !safeText(strategy.summary,1500) || !strategy.summary.trim() || !Array.isArray(strategy.stays) || strategy.stays.length<1 || strategy.stays.length>12)return invalid();
      let cursor=Date.parse(checked.value.startDate);
      for(const stay of strategy.stays){
        if(!stay || Object.keys(stay).sort().join(',')!=='endDate,location,startDate' || !isRealIsoDate(stay.startDate)||!isRealIsoDate(stay.endDate)||Date.parse(stay.startDate)!==cursor||stay.endDate<stay.startDate||!safeText(stay.location,200)||!stay.location.trim())return invalid();
        cursor=Date.parse(stay.endDate)+86400000;
      }
      if(cursor!==Date.parse(checked.value.endDate)+86400000)return invalid();
    }
    sequence=s.sequence;ids.add(s.id);
    return structuredClone({id:s.id,sequence:s.sequence,startDate:s.startDate,endDate:s.endDate,checkpoint:c});
  });
  if(body.nextCursor!==null && (!integer(body.nextCursor)||body.nextCursor<=afterSequence||body.nextCursor<sequence)) return invalid();
  return {preferences:checked.value,plan:{id:p.id,requestId:p.requestId,status:p.status,completedDays:p.completedDays,totalDays:p.totalDays,remainingCreates:p.remainingCreates,runAllowance:p.runAllowance,estimatedSections:p.estimatedSections,storageLimitBytes:p.storageLimitBytes,storageUsedBytes:p.storageUsedBytes,globalStorageLimitBytes:p.globalStorageLimitBytes,storagePauseScope:p.storagePauseScope,spentCents:p.spentCents,totalBudgetCents:p.totalBudgetCents,pauseReason:p.pauseReason,expiresAt:p.expiresAt,activeSection},sections,nextCursor:body.nextCursor};
}
export function createAdaptivePlanningClient({fetchImpl=sessionFetch,baseUrl=(import.meta.env?.VITE_API_BASE_URL || '/api'),timeoutMs=15000}={}) {
  async function request(path,method,payload,{signal,id,requestId,afterSequence=0}={}) {
    const controller=new AbortController(),abort=()=>controller.abort();
    if(signal?.aborted)abort();signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(abort,timeoutMs);
    try {
      if(controller.signal.aborted)throw Error('aborted');
      const response=await fetchImpl(`${baseUrl.replace(/\/$/,'')}/adaptive-plans${path}`,{method,signal:controller.signal,headers:{Accept:'application/json',...(payload?{'Content-Type':'application/json'}:{})},...(payload?{body:JSON.stringify(payload)}:{})});
      if(![200,201,202].includes(response.status)) {
        let code=response.status===401?'AUTH_REQUIRED':response.status===404?'ADAPTIVE_NOT_FOUND':response.status===409?'ADAPTIVE_CONFLICT':response.status===503?'ADAPTIVE_UNAVAILABLE':'ADAPTIVE_REJECTED';
        let money=false;
        if(response.status===400){try{money=(await response.json())?.error?.code==='SECTION_MONEY_INVALID';}catch{}}
        if(money)code='SECTION_MONEY_INVALID';
        throw new AdaptivePlanningError(code,money?'Enter a budget with at most two decimal places in the supported monetary range. This is a number-format check, not a minimum trip budget.':response.status===401?'Sign in again to check this trip.':'This planning request could not be completed. Check its status before trying again.',{confirmed:[400,401,403,404,409,413,422,429].includes(response.status)});
      }
      const body=await response.json();if(controller.signal.aborted)throw Error('aborted');
      return validateAdaptivePage(body,{id,requestId,afterSequence});
    } catch(error) {
      if(signal?.aborted)throw new DOMException('Aborted','AbortError');
      if(error instanceof AdaptivePlanningError)throw error;
      throw new AdaptivePlanningError(method==='POST'?'ADAPTIVE_OUTCOME_UNCONFIRMED':'ADAPTIVE_UNAVAILABLE','The response could not be confirmed. Check this trip before trying again.');
    } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  }
  const identity=value=>{if(!adaptiveId(value))throw new AdaptivePlanningError('VALIDATION_ERROR','This planning identifier is invalid.',{confirmed:true});return value;};
  return {
    start(preferences,requestId,options={}) {const c=validateTripPreferences(preferences);if(!c.valid)throw new AdaptivePlanningError('VALIDATION_ERROR','Check your trip details.',{confirmed:true});return request('','POST',{preferences:c.value,requestId:identity(requestId)},{...options,requestId});},
    get(id,{afterSequence=0,...options}={}) {identity(id);if(!integer(afterSequence))throw new AdaptivePlanningError('VALIDATION_ERROR','Invalid page.');return request(`/${id}?afterSequence=${afterSequence}`,'GET',null,{...options,id,afterSequence});},
    findRequest(requestId,options={}) {return request(`/requests/${identity(requestId)}`,'GET',null,{...options,requestId});},
    continue(id,requestId,options={}) {return request(`/${identity(id)}/continue`,'POST',{requestId:identity(requestId)},{...options,id});},
    retry(id,requestId,sectionId,options={}) {return request(`/${identity(id)}/retry`,'POST',{requestId:identity(requestId),sectionId:identity(sectionId)},{...options,id});},
    cancel(id,options={}) {return request(`/${identity(id)}/cancel`,'POST',{}, {...options,id});},
  };
}
