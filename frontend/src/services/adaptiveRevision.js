import { sessionFetch } from './session.js';
import { adaptiveId } from './adaptivePlanning.js';
import { validAdaptiveSectionItinerary } from './adaptiveItineraryValidation.js';
import { isRealIsoDate } from '../../../shared/tripPreferences.mjs';
const statuses=new Set(['queued','submitting','running','candidate','failed','submission_unknown','rejected','accepted']);
const errorCodes=new Set(['REVISION_REQUEST_FAILED','REVISION_BASE_CHANGED','REVISION_BASE_EXPIRED','REVISION_BUDGET_EXCEEDED','REVISION_BUDGET_EXHAUSTED','REVISION_CONSTRAINT_CONFLICT','REVISION_DEADLINE_REACHED','REVISION_FIXED_COMMITMENT_CONFLICT','REVISION_INSUFFICIENT_RETENTION','REVISION_INVALID_BASE','REVISION_INVALID_RESULT','REVISION_ALLOWANCE_REACHED','REVISION_POLL_UNCONFIRMED','REVISION_PROVIDER_FAILED','REVISION_PROVIDER_REJECTED','REVISION_REPEAT_CONFLICT','REVISION_RESPONSE_MISMATCH','REVISION_REST_CONFLICT','REVISION_RESULT_INVALID','REVISION_RETURN_CONFLICT','REVISION_ROUTE_CONFLICT','REVISION_STORAGE_LIMIT','REVISION_STORAGE_UNCONFIRMED','REVISION_SUBMISSION_UNCONFIRMED','REVISION_TARGET_INVALID','REVISION_UNCHANGED_DAY_MODIFIED','REVISION_WARNING_CAPACITY']);
const integer=value=>Number.isSafeInteger(value)&&value>=0;
export const validRevisionInput=(targetDate,instruction,preferences)=>isRealIsoDate(targetDate)&&targetDate>=preferences.startDate&&targetDate<=preferences.endDate&&typeof instruction==='string'&&Boolean(instruction.trim())&&instruction.length<=4000&&Array.from(instruction).length<=2000&&!/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(instruction);
export class RevisionError extends Error {constructor(code,{confirmed=false}={}){super('The revision status could not be confirmed. Check this same revision before trying another change.');this.code=code;this.confirmed=confirmed;}}
export function validateRevision(body,{basePlanId,preferences,id,requestId,targetDate,expiresAt}={}) {
  const r=body?.revision,invalid=()=>{throw new RevisionError('REVISION_INVALID_RESPONSE');};
  if(!r||!adaptiveId(r.id)||!adaptiveId(r.requestId)||r.basePlanId!==basePlanId||(id&&r.id!==id)||(requestId&&r.requestId!==requestId)||(targetDate&&r.targetDate!==targetDate)||!isRealIsoDate(r.targetDate)||r.targetDate<preferences.startDate||r.targetDate>preferences.endDate||!statuses.has(r.status)||r.accepted!==(r.status==='accepted')||!Number.isFinite(Date.parse(r.expiresAt))||(expiresAt&&Date.parse(r.expiresAt)!==Date.parse(expiresAt))||!integer(r.remainingCreates)||r.remainingCreates>12||!(r.errorCode===null||typeof r.errorCode==='string'&&r.errorCode.length<=100))return invalid();
  if(r.status==='accepted'?(!adaptiveId(r.acceptedPlanId)||r.acceptedPlanId===basePlanId):r.acceptedPlanId!==null)return invalid();
  let candidate=null;
  if(r.status==='candidate'){
    const c=r.candidate,cp=c?.checkpoint,it=cp?.itinerary,days=it?.days;
    if(!c||c.status!=='candidate'||c.accepted!==false||c.targetDate!==r.targetDate||!integer(c.totalSpentCents)||c.totalSpentCents>Math.round(preferences.budget*100)||!cp||!integer(cp.spentCents)||!Array.isArray(days)||days.length<1||days.length>3||days.filter(day=>day.date===r.targetDate).length!==1||days[0].date<preferences.startDate||days.at(-1).date>preferences.endDate||typeof cp.startLocation!=='string'||cp.startLocation.length>200||typeof cp.endLocation!=='string'||cp.endLocation.length>200||cp.provenance?.provider!=='openai'||cp.provenance?.model!=='gpt-6-luna'||cp.provenance?.validationVersion!=='adaptive-section-v1')return invalid();
    const budget=it.estimatedTotalGroupCost+it.remainingBudget;
    if(!validAdaptiveSectionItinerary(it,{...preferences,startDate:days[0].date,endDate:days.at(-1).date,budget},preferences,cp.journeyStrategy)||Math.abs(it.estimatedTotalGroupCost*100-cp.spentCents)>.001)return invalid();
    const pick=(value,keys)=>Object.fromEntries(keys.map(key=>[key,value[key]]));
    const publicDays=days.map(day=>({...pick(day,['date','morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest','mainActivityCount']),interestTags:[...day.interestTags],costs:pick(day.costs,['accommodation','meals','localTransport','activities','departureTravel']),activities:day.activities.map(activity=>pick(activity,['id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind']))}));
    const publicItinerary={...pick(it,['source','saved','provider','model','status','vibe','destination','currency','travelStyle','travelPace','explanation','estimatedTotalGroupCost','remainingBudget']),warnings:[...it.warnings],days:publicDays};
    candidate={checkpoint:{itinerary:publicItinerary,startLocation:cp.startLocation,endLocation:cp.endLocation,spentCents:cp.spentCents,provenance:pick(cp.provenance,['provider','model','validationVersion'])},totalSpentCents:c.totalSpentCents,targetDate:c.targetDate,status:'candidate',accepted:false};
  }else if(r.candidate!==null)return invalid();
  return {id:r.id,requestId:r.requestId,basePlanId,targetDate:r.targetDate,status:r.status,accepted:r.accepted,expiresAt:r.expiresAt,errorCode:r.errorCode===null?null:errorCodes.has(r.errorCode)?r.errorCode:'REVISION_REQUEST_FAILED',remainingCreates:r.remainingCreates,candidate,acceptedPlanId:r.acceptedPlanId};
}
export function createRevisionClient({fetchImpl=sessionFetch,timeoutMs=15000}={}) {
  async function request(path,method,payload,expected,{signal,expiresAt}={}){
    const controller=new AbortController(),abort=()=>controller.abort(),timer=setTimeout(abort,timeoutMs);if(signal?.aborted)abort();signal?.addEventListener('abort',abort,{once:true});
    try{const response=await fetchImpl(`${(import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/,'')}/adaptive-plans/${expected.basePlanId}${path}`,{method,signal:controller.signal,headers:{Accept:'application/json',...(payload?{'Content-Type':'application/json'}:{})},...(payload?{body:JSON.stringify(payload)}:{})});
      if(![200,201,202].includes(response.status)){let raw;try{raw=(await response.json())?.error?.code;}catch{}let code=response.status===401?'AUTH_REQUIRED':'REVISION_REQUEST_UNCONFIRMED',confirmed=false;
        if(method==='GET'&&response.status===404&&raw==='REVISION_NOT_FOUND'){if(path==='/revisions/current'){code='REVISION_CURRENT_NOT_FOUND';confirmed=true;}else if(expected.id&&path===`/revisions/${expected.id}`){code='REVISION_UNAVAILABLE';confirmed=true;}}
        if(method==='POST'&&path==='/revisions'){if(response.status===400&&raw==='REVISION_INVALID_REQUEST'){code='REVISION_INPUT_REJECTED';confirmed=true;}else if((response.status===409&&['REVISION_ALLOWANCE_REACHED','REVISION_INSUFFICIENT_RETENTION','REVISION_OWNER_BUSY'].includes(raw))||(response.status===410&&raw==='REVISION_BASE_EXPIRED')||(response.status===413&&raw==='REVISION_STORAGE_LIMIT')){code=raw;confirmed=true;}}
        throw new RevisionError(code,{confirmed});}
      const body=await response.json();if(controller.signal.aborted)throw Error();if(expected.availabilityOnly){if(body?.revision?.id!==expected.id||body.revision.basePlanId!==expected.basePlanId)throw new RevisionError('REVISION_INVALID_RESPONSE');return{available:true};}return validateRevision(body,{...expected,expiresAt});
    }catch(error){if(error instanceof RevisionError)throw error;throw new RevisionError('REVISION_REQUEST_UNCONFIRMED');}finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  }
  const expected=(basePlanId,preferences,extra={})=>{if(!adaptiveId(basePlanId))throw new RevisionError('REVISION_INPUT_REJECTED',{confirmed:true});return{basePlanId,preferences,...extra};};
  const identity=id=>{if(!adaptiveId(id))throw new RevisionError('REVISION_INPUT_REJECTED',{confirmed:true});return id;};
  return{
    availability:(base,id,options)=>request(`/revisions/${identity(id)}`,'GET',null,expected(base,null,{id,availabilityOnly:true}),options),
    current:(base,p,options)=>request('/revisions/current','GET',null,expected(base,p),options),
    lookup:(base,p,requestId,options)=>request(`/revision-requests/${identity(requestId)}`,'GET',null,expected(base,p,{requestId}),options),
    get:(base,p,id,options)=>request(`/revisions/${identity(id)}`,'GET',null,expected(base,p,{id}),options),
    start:(base,p,input,options)=>{if(!validRevisionInput(input.targetDate,input.instruction,p))throw new RevisionError('REVISION_INPUT_REJECTED',{confirmed:true});identity(input.requestId);return request('/revisions','POST',input,expected(base,p,{requestId:input.requestId,targetDate:input.targetDate}),options);},
    retry:(base,p,id,requestId,options)=>request(`/revisions/${identity(id)}/retry`,'POST',{requestId:identity(requestId)},expected(base,p,{requestId}),options),
    accept:(base,p,id,options)=>request(`/revisions/${identity(id)}/accept`,'POST',{},expected(base,p,{id}),options),
    reject:(base,p,id,options)=>request(`/revisions/${identity(id)}/reject`,'POST',{},expected(base,p,{id}),options),
  };
}
