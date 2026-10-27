import { CURRENCIES, INTEREST_OPTIONS, isRealIsoDate } from '../../../shared/tripPreferences.mjs';
import { COST_LABELS, validActivities } from './itineraries.js';

const statuses=new Set(['queued','submitting','running','succeeded','failed','submission_unknown','cancelled']);
const text=(value,max,multiline=false)=>typeof value==='string'&&value.trim().length>0&&value.length<=max*2&&Array.from(value).length<=max&&!/[\uD800-\uDFFF]/u.test(value)&&!(multiline?/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/:/[\u0000-\u001f\u007f]/).test(value);
export const researchTimestamp=value=>typeof value==='string'&&value.length<=64&&isRealIsoDate(value.slice(0,10))&&/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)&&Number.isFinite(Date.parse(value));
export function researchSourceUrl(value) {
  if(!text(value,2048)||/[\u0000-\u0020\u007f]/.test(value))return null;
  try{
    const url=new URL(value),host=url.hostname.toLowerCase().replace(/\.+$/,'');
    const reserved=['local','internal','localhost','test','invalid','example','localdomain','lan','home','home.arpa','onion'];
    const dns=/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
    return url.protocol==='https:'&&(!url.port||url.port==='443')&&!url.username&&!url.password&&host.length<=253&&dns.test(host)&&!/^\d+$/.test(host.split('.').at(-1))&&!reserved.some(suffix=>host===suffix||host.endsWith(`.${suffix}`))?url.href:null;
  }catch{return null;}
}
export function validResearchDisplay(value) {
  if(!value||!statuses.has(value.status)||value.toolCallLimit!==6||!Number.isSafeInteger(value.toolCallsReserved)||value.toolCallsReserved<0||value.toolCallsReserved>6||!Array.isArray(value.sources)||value.sources.length>48)return false;
  if(!value.sources.every(source=>source&&researchSourceUrl(source.url)&&typeof source.title==='string'&&source.title.length<=600&&Array.from(source.title).length<=300&&!/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(source.title)))return false;
  if(value.text!=null&&value.text!==''&&!text(value.text,24000,true))return false;
  if(value.receivedAt!=null&&!researchTimestamp(value.receivedAt))return false;
  if(value.expiresAt!=null&&(!researchTimestamp(value.expiresAt)||!researchTimestamp(value.receivedAt)||Date.parse(value.expiresAt)<=Date.parse(value.receivedAt)||Date.parse(value.expiresAt)-Date.parse(value.receivedAt)>86400000))return false;
  return value.status!=='succeeded'||Boolean(value.sources.length&&text(value.text,24000,true)&&researchTimestamp(value.receivedAt)&&researchTimestamp(value.expiresAt));
}

export function validDraftDisplay(draft,currency,sectionStart,sectionEnd) {
  if(!draft||draft.status!=='draft'||draft.accepted!==false||!CURRENCIES.includes(currency)||!isRealIsoDate(sectionStart)||!isRealIsoDate(sectionEnd)||sectionEnd<sectionStart||!Array.isArray(draft.days)||draft.days.length>3)return false;
  const start=Date.parse(`${sectionStart}T00:00:00Z`),length=(Date.parse(`${sectionEnd}T00:00:00Z`)-start)/86400000+1;
  if(length<1||length>3||draft.days.length>length)return false;
  return draft.days.every((day,index)=>day&&day.date===new Date(start+index*86400000).toISOString().slice(0,10)&&validActivities(day.activities)
    &&['morning','afternoon','evening','dining'].every(field=>text(day[field],700))&&['transitAndRest','dietaryNotes','mobilityNotes'].every(field=>text(day[field],500))
    &&Number.isInteger(day.mainActivityCount)&&day.mainActivityCount>=0&&day.mainActivityCount<=4&&day.mainActivityCount===day.activities.filter(activity=>activity.kind==='main').length
    &&Array.isArray(day.interestTags)&&day.interestTags.length<=8&&new Set(day.interestTags).size===day.interestTags.length&&day.interestTags.every(tag=>INTEREST_OPTIONS.some(option=>option.id===tag))
    &&day.costs&&Object.keys(day.costs).length===5&&Object.keys(COST_LABELS).every(key=>typeof day.costs[key]==='number'&&Number.isFinite(day.costs[key])&&day.costs[key]>=0&&day.costs[key]<=Number.MAX_SAFE_INTEGER/100));
}

const researchErrors=new Set(['RESEARCH_QUERY_INVALID','RESEARCH_PROVIDER_REJECTED','RESEARCH_DEADLINE_REACHED','RESEARCH_SOURCES_UNCONFIRMED','RESEARCH_SUBMISSION_UNCONFIRMED','RESEARCH_POLL_UNCONFIRMED','RESEARCH_PROVIDER_FAILED','RESEARCH_RESPONSE_MISMATCH']);
const invalid=()=>{throw new Error('Invalid public research or draft.');};
const pick=(value,keys)=>Object.fromEntries(keys.map(key=>[key,value[key]]));
const dayKeys=['date','morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest','mainActivityCount','interestTags'];
const activityKeys=['id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind'];

/** Shape and source binding only: this never establishes a travel fact as verified. */
export function readPublicResearch(value) {
  if(value==null)return null;
  if(!validResearchDisplay(value)||value.applicability!=='unknown'||!Array.isArray(value.citations)||value.citations.length>48
    ||typeof value.text!=='string'||!(value.errorCode===null||text(value.errorCode,100)))return invalid();
  const sources=value.sources.map(source=>({url:researchSourceUrl(source.url),title:source.title}));
  const byUrl=new Map(sources.map(source=>[source.url,source.title]));
  if(byUrl.size!==sources.length)return invalid();
  const length=Array.from(value.text).length,cited=new Set();
  const citations=value.citations.map(citation=>{
    const url=researchSourceUrl(citation?.url);
    if(!url||!byUrl.has(url)||citation.title!==byUrl.get(url)||!Number.isSafeInteger(citation.start)||!Number.isSafeInteger(citation.end)
      ||citation.start<0||citation.start>=citation.end||citation.end>length)return invalid();
    cited.add(url);return{start:citation.start,end:citation.end,url,title:citation.title};
  });
  if(value.status==='succeeded'){
    if(!citations.length||cited.size!==sources.length||value.errorCode!==null)return invalid();
  }else if(value.text!==''||sources.length||citations.length||value.receivedAt!==null||value.expiresAt!==null)return invalid();
  return {status:value.status,toolCallsReserved:value.toolCallsReserved,toolCallLimit:6,errorCode:value.errorCode===null?null:researchErrors.has(value.errorCode)?value.errorCode:'REQUEST_FAILED',receivedAt:value.receivedAt,expiresAt:value.expiresAt,sources,citations,text:value.text,applicability:'unknown'};
}

/** Only complete bounded draft days for the next section, never a raw stream cursor. */
export function readPublicDraft(value,plan,preferences) {
  if(value==null)return null;
  if(plan.status!=='active'||plan.activeSection?.status!=='running'||plan.completedDays>=plan.totalDays
    ||value.currency!==preferences.currency||!validDraftDisplay(value,value.currency,value.sectionStart,value.sectionEnd))return invalid();
  const start=Date.parse(`${preferences.startDate}T00:00:00Z`)+plan.completedDays*86400000;
  const end=Math.min(start+2*86400000,Date.parse(`${preferences.endDate}T00:00:00Z`));
  if(value.sectionStart!==new Date(start).toISOString().slice(0,10)||value.sectionEnd>new Date(end).toISOString().slice(0,10))return invalid();
  const days=value.days.map(day=>{
    if(day.activities.some(activity=>!['unknown','main','rest','transfer','meal','accommodation'].includes(activity.kind)))return invalid();
    return {...pick(day,dayKeys),interestTags:[...day.interestTags],costs:pick(day.costs,Object.keys(COST_LABELS)),activities:day.activities.map(activity=>pick(activity,activityKeys))};
  });
  return{status:'draft',accepted:false,sectionStart:value.sectionStart,sectionEnd:value.sectionEnd,currency:value.currency,days};
}

export const validGroundedPolicy=value=>value?.researchEnabled===true&&value.maxWebSearchCalls===6&&value.researchMode==='on_demand'&&typeof value.provisionalDayPreviews==='boolean'&&value.responseDeadlineMinutes===8;
