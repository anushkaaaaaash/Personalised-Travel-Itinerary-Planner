import {sessionFetch} from './session.js';
import {adaptiveId} from './adaptivePlanning.js';
import {adaptiveTravelDates,validAdaptiveSectionItinerary} from './adaptiveItineraryValidation.js';
import {readPublicResearch,researchTimestamp} from './groundedPlanning.js';
import {CURRENCIES,isRealIsoDate,validateTripPreferences} from '../../../shared/tripPreferences.mjs';

const integer=(value,min=0)=>Number.isSafeInteger(value)&&value>=min;
const text=(value,max)=>typeof value==='string'&&value.trim().length>0&&Array.from(value).length<=max&&!/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(value);
const pick=(value,keys)=>Object.fromEntries(keys.map(key=>[key,value[key]]));
const summaryKeys=['id','requestId','title','version','createdAt','updatedAt','format','persisted','sourcePlanId','sourceVersion','totalDays','sectionCount','spentCents','totalBudgetCents','currency','startDate','endDate','destination'];
const errors={
  SAVED_ADAPTIVE_CONFLICT:'This trip cannot be saved in its current state. Check the completed version before saving again.',
  SAVED_ADAPTIVE_INVALID_SNAPSHOT:'This complete snapshot could not be verified for saving. The retained trip is unchanged; download it instead.',
  SAVED_ADAPTIVE_QUOTA_EXCEEDED:'Your account-save storage allowance is full. Download the retained plan instead.',
  SAVED_ADAPTIVE_FORBIDDEN:'This account cannot access this saved trip.',
  SAVED_ADAPTIVE_INVALID_REQUEST:'Check the trip name and try saving again. No save was started.',
  SAVED_ADAPTIVE_NOT_COMPLETE:'Only a fully completed trip can be saved to your account. Your retained sections are unchanged.',
  SAVED_ADAPTIVE_VERSION_CONFLICT:'This trip version changed. Reopen the completed trip before choosing which version to save.',
  SAVED_ADAPTIVE_REQUEST_CONFLICT:'This save identity belongs to a different snapshot. Check the original save; do not submit another copy yet.',
  SAVED_ADAPTIVE_QUOTA_REACHED:'Your account-save allowance is full. Download the retained plan instead; no budget or date change is needed.',
  SAVED_ADAPTIVE_SOURCE_EXPIRED:'The temporary trip expired during saving. Check this save’s status; an unfinished copy is not an account-saved trip.',
  SAVED_ADAPTIVE_TOO_LARGE:'This trip exceeds the current account-save storage limit. Download the retained plan instead; your trip dates have not been changed.',
  PERSISTENCE_FORBIDDEN:'This account cannot access this saved trip.',
  SAVED_ADAPTIVE_REQUEST_NOT_FOUND:'The save could not be found yet. Its outcome is still unconfirmed; check again before another save.',
  SAVED_ADAPTIVE_NOT_FOUND:'This saved trip is not available to your account.',
  AUTH_REQUIRED:'Sign in again to check your saved trips.',
  SAVED_ADAPTIVE_UNAVAILABLE:'Account saving is temporarily unavailable. Your retained trip is unchanged.',
  SAVED_ADAPTIVE_INVALID_RESPONSE:'The saved-trip response could not be verified. Check this same save before trying another write.',
  SAVED_ADAPTIVE_UNCONFIRMED:'The saved-trip update could not be confirmed. Check its status before trying another write.',
};
export class SavedAdaptiveError extends Error {
  constructor(code,{confirmed=false}={}){super(errors[code]||errors.SAVED_ADAPTIVE_UNCONFIRMED);this.code=Object.hasOwn(errors,code)?code:'SAVED_ADAPTIVE_UNCONFIRMED';this.confirmed=confirmed;}
}
const invalid=()=>{throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_RESPONSE');};
export function validateSavedAdaptiveSummary(value,{id,requestId,sourcePlanId,sourceVersion}={}) {
  if(!value||value.format!=='adaptive-sections-v1'||value.persisted!==true||!['id','requestId','sourcePlanId'].every(key=>adaptiveId(value[key]))
    ||(id&&value.id!==id)||(requestId&&value.requestId!==requestId)||(sourcePlanId&&value.sourcePlanId!==sourcePlanId)||(sourceVersion&&value.sourceVersion!==sourceVersion)
    ||!integer(value.version,1)||!integer(value.sourceVersion,1)||!text(value.title,120)||!text(value.destination,200)||!CURRENCIES.includes(value.currency)
    ||!researchTimestamp(value.createdAt)||!researchTimestamp(value.updatedAt)||Date.parse(value.updatedAt)<Date.parse(value.createdAt)
    ||!isRealIsoDate(value.startDate)||!isRealIsoDate(value.endDate)||value.startDate>value.endDate||!integer(value.totalDays,1)
    ||value.totalDays!==(Date.parse(value.endDate)-Date.parse(value.startDate))/86400000+1
    ||!integer(value.sectionCount,1)||value.sectionCount>1024||value.sectionCount<Math.ceil(value.totalDays/3)||value.sectionCount>value.totalDays
    ||!integer(value.spentCents)||!integer(value.totalBudgetCents,1)||value.spentCents>value.totalBudgetCents)return invalid();
  return pick(value,summaryKeys);
}
export function validateSavedAdaptiveOperation(value,expected={}) {
  if(!value||!adaptiveId(value.requestId)||!adaptiveId(value.sourcePlanId)||!integer(value.sourceVersion,1)||!text(value.title,120)
    ||!['staging','complete','expired'].includes(value.status)||!integer(value.savedSections)||!integer(value.totalSections,1)||value.totalSections>1024||value.savedSections>value.totalSections
    ||Object.entries(expected).some(([key,v])=>v!==undefined&&value[key]!==v))return invalid();
  let saved=null;
  if(value.status==='complete'){
    if(value.persisted!==true||!adaptiveId(value.savedId)||value.savedSections!==value.totalSections||value.stagingExpiresAt!==null)return invalid();
    saved=validateSavedAdaptiveSummary(value.saved,{id:value.savedId,requestId:value.requestId,sourcePlanId:value.sourcePlanId,sourceVersion:value.sourceVersion});
    if(saved.title!==value.title||saved.sectionCount!==value.totalSections)return invalid();
  }else if(value.persisted!==false||value.savedId!==null||value.saved!==null||(value.status==='staging'?!researchTimestamp(value.stagingExpiresAt):value.stagingExpiresAt!==null&&!researchTimestamp(value.stagingExpiresAt)))return invalid();
  return {...pick(value,['requestId','sourcePlanId','sourceVersion','title','status','persisted','savedId','savedSections','totalSections','stagingExpiresAt']),saved};
}
const strategy=(value,prefs)=>{
  if(!adaptiveTravelDates(prefs,value)||!value)return invalid();
  return{summary:value.summary,stays:value.stays.map(stay=>pick(stay,['startDate','endDate','location']))};
};
export function validateHistoricalSources(value) {
  if(!value||Object.keys(value).sort().join(',')!=='applicability,citations,evidenceStatus,expiresAt,receivedAt,sources,text'||value.evidenceStatus!=='historical_unverified'||value.applicability!=='unknown')return invalid();
  let checked;try{checked=readPublicResearch({...value,status:'succeeded',toolCallsReserved:0,toolCallLimit:6,errorCode:null});}catch{return invalid();}
  if(Date.parse(checked.receivedAt)>Date.now())return invalid();
  return{...pick(checked,['receivedAt','expiresAt','text','sources','citations','applicability']),evidenceStatus:'historical_unverified'};
}
function itinerary(value){
  return {...pick(value,['source','saved','provider','model','status','vibe','destination','currency','travelStyle','travelPace','explanation','warnings','estimatedTotalGroupCost','remainingBudget']),days:value.days.map(day=>({...pick(day,['date','morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest','mainActivityCount','interestTags']),costs:pick(day.costs,['accommodation','meals','localTransport','activities','departureTravel']),activities:day.activities.map(a=>pick(a,['id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind']))}))};
}
export function validateSavedAdaptivePage(value,{id,afterSequence=0}={}) {
  const saved=validateSavedAdaptiveSummary(value?.saved,{id}),p=validateTripPreferences(value.preferences);
  if(!p.valid||p.value.destination!==saved.destination||p.value.currency!==saved.currency||p.value.startDate!==saved.startDate||p.value.endDate!==saved.endDate||Math.round(p.value.budget*100)!==saved.totalBudgetCents
    ||!integer(afterSequence)||afterSequence>=saved.sectionCount||!Array.isArray(value.sections)||value.sections.length!==Math.min(3,saved.sectionCount-afterSequence))return invalid();
  const route=strategy(value.journeyStrategy,p.value),ids=new Set();let sequence=afterSequence,previousEnd=null,previousLocation=null,pageSpent=0;
  const sections=value.sections.map(s=>{
    const c=s?.checkpoint;
    if(!s||!adaptiveId(s.id)||ids.has(s.id)||s.sequence!==sequence+1||s.sequence>saved.sectionCount||!isRealIsoDate(s.startDate)||!isRealIsoDate(s.endDate)||s.endDate<s.startDate||s.startDate<saved.startDate||s.endDate>saved.endDate||(Date.parse(s.endDate)-Date.parse(s.startDate))/86400000>=3
      ||(previousEnd&&Date.parse(s.startDate)!==Date.parse(previousEnd)+86400000)||!c||!integer(c.spentCents)||!text(c.startLocation,200)||!text(c.endLocation,200)
      ||(previousLocation&&c.startLocation!==previousLocation)||!c.itinerary||c.itinerary.status!=='planned'||!Number.isFinite(c.itinerary.remainingBudget))return invalid();
    const cpRoute=strategy(c.journeyStrategy,p.value),budget=c.itinerary.estimatedTotalGroupCost+c.itinerary.remainingBudget;
    if(!Number.isFinite(budget)||budget<=0||budget>p.value.budget||JSON.stringify(cpRoute)!==JSON.stringify(route)||!validAdaptiveSectionItinerary(c.itinerary,{...p.value,startDate:s.startDate,endDate:s.endDate,budget},p.value,route)
      ||Math.abs(c.itinerary.estimatedTotalGroupCost*100-c.spentCents)>.001||c.provenance?.provider!=='openai'||c.provenance?.model!=='gpt-6-luna'||c.provenance?.validationVersion!=='adaptive-section-v1')return invalid();
    if((s.sequence===1&&(s.startDate!==saved.startDate||c.startLocation!==p.value.departureCity))||(s.sequence===saved.sectionCount&&(s.endDate!==saved.endDate||c.endLocation!==p.value.departureCity)))return invalid();
    if(!['none_recorded','linked_historical'].includes(s.sourceAssociation)||!Array.isArray(s.historicalSources)||s.historicalSources.length>1||(s.sourceAssociation==='none_recorded'?s.historicalSources.length!==0:s.historicalSources.length!==1))return invalid();
    ids.add(s.id);sequence=s.sequence;previousEnd=s.endDate;previousLocation=c.endLocation;pageSpent+=c.spentCents;
    return {...pick(s,['id','sequence','startDate','endDate','sourceAssociation']),checkpoint:{...pick(c,['startLocation','endLocation','spentCents']),journeyStrategy:route,provenance:pick(c.provenance,['provider','model','validationVersion']),itinerary:itinerary(c.itinerary)},historicalSources:s.historicalSources.map(validateHistoricalSources)};
  });
  if(pageSpent>saved.spentCents||(afterSequence===0&&sequence===saved.sectionCount&&pageSpent!==saved.spentCents)||(sequence===saved.sectionCount?value.nextCursor!==null:value.nextCursor!==sequence))return invalid();
  return{saved,preferences:p.value,journeyStrategy:route,sections,nextCursor:value.nextCursor};
}
export function createSavedAdaptiveClient({fetchImpl=sessionFetch,baseUrl=(import.meta.env?.VITE_API_BASE_URL||'/api'),timeoutMs=30000}={}) {
  async function request(path,{method='GET',payload,signal}={}){
    const controller=new AbortController(),abort=()=>controller.abort();if(signal?.aborted)abort();signal?.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,timeoutMs);
    try{
      if(controller.signal.aborted)throw Error();
      const response=await fetchImpl(`${baseUrl.replace(/\/$/,'')}${path}`,{method,signal:controller.signal,headers:{Accept:'application/json',...(payload?{'Content-Type':'application/json'}:{})},...(payload?{body:JSON.stringify(payload)}:{})});
      let value;try{value=await response.json();}catch{throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_RESPONSE');}if(controller.signal.aborted)throw Error();
      if(![200,201,202].includes(response.status)){
        const code=value?.error?.code;
        const allowed={400:['SAVED_ADAPTIVE_INVALID_REQUEST'],409:['SAVED_ADAPTIVE_NOT_COMPLETE','SAVED_ADAPTIVE_VERSION_CONFLICT','SAVED_ADAPTIVE_REQUEST_CONFLICT','SAVED_ADAPTIVE_QUOTA_REACHED','SAVED_ADAPTIVE_CONFLICT','SAVED_ADAPTIVE_INVALID_SNAPSHOT'],410:['SAVED_ADAPTIVE_SOURCE_EXPIRED'],413:['SAVED_ADAPTIVE_TOO_LARGE','SAVED_ADAPTIVE_QUOTA_EXCEEDED'],403:['PERSISTENCE_FORBIDDEN','SAVED_ADAPTIVE_FORBIDDEN'],404:['SAVED_ADAPTIVE_REQUEST_NOT_FOUND','SAVED_ADAPTIVE_NOT_FOUND']};
        if(response.status===401)throw new SavedAdaptiveError('AUTH_REQUIRED',{confirmed:true});
        if(allowed[response.status]?.includes(code))throw new SavedAdaptiveError(code,{confirmed:true});
        throw new SavedAdaptiveError(method==='GET'?'SAVED_ADAPTIVE_UNAVAILABLE':'SAVED_ADAPTIVE_UNCONFIRMED');
      }
      if(JSON.stringify(value).length>2*1024*1024)return invalid();return value;
    }catch(error){if(signal?.aborted)throw new DOMException('Aborted','AbortError');if(error instanceof SavedAdaptiveError)throw error;throw new SavedAdaptiveError(method==='GET'?'SAVED_ADAPTIVE_UNAVAILABLE':'SAVED_ADAPTIVE_UNCONFIRMED');}
    finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  }
  const id=value=>{if(!adaptiveId(value))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_REQUEST',{confirmed:true});return value;};
  return{
    async save(sourcePlanId,{requestId,title,expectedVersion},options={}){id(sourcePlanId);id(requestId);if(!text(title,120)||!integer(expectedVersion,1))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_REQUEST',{confirmed:true});return validateSavedAdaptiveOperation(await request(`/adaptive-plans/${sourcePlanId}/save`,{...options,method:'POST',payload:{requestId,title,expectedVersion}}),{sourcePlanId,requestId,sourceVersion:expectedVersion,title});},
    async remove(identity,version,options={}){id(identity);if(!integer(version,1))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_REQUEST',{confirmed:true});const value=await request(`/saved-adaptive-trips/${identity}`,{...options,method:'DELETE',payload:{version}});if(!value||value.id!==identity||value.deleted!==true||value.version!==version)return invalid();return{id:identity,deleted:true,version};},
    async check(requestId,options={}){return validateSavedAdaptiveOperation(await request(`/saved-adaptive-trips/requests/${id(requestId)}`,options),{requestId});},
    async list(offset=0,options={}){if(!integer(offset)||offset>10000)throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_REQUEST',{confirmed:true});const value=await request(`/saved-adaptive-trips?offset=${offset}`,options);if(!value||value.offset!==offset||typeof value.hasMore!=='boolean'||!Array.isArray(value.items)||value.items.length>20)return invalid();const items=value.items.map(item=>validateSavedAdaptiveSummary(item));if(new Set(items.map(item=>item.id)).size!==items.length)return invalid();return{items,hasMore:value.hasMore,offset};},
    async get(identity,{afterSequence=0,...options}={}){if(!integer(afterSequence))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_REQUEST',{confirmed:true});return validateSavedAdaptivePage(await request(`/saved-adaptive-trips/${id(identity)}?afterSequence=${afterSequence}`,options),{id:identity,afterSequence});},
  };
}
