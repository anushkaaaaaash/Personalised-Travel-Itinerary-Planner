import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { itineraryDates } from './itineraries.js';
import { getSession, subscribeSession } from './session.js';
import { createPlanningJobsClient } from './planningJobs.js';
export const PLANNING_JOB_STORAGE_KEY = 'travel.planning-job.v1';
const uuid = value => typeof value === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const terminal = status => ['succeeded','failed','cancelled','expired'].includes(status);
const defaultStorage = () => { try { return globalThis.sessionStorage; } catch { return null; } };
const empty = () => ({job:null,loading:false,error:'',preferences:null,result:null,evidence:null,resumable:false,needsCheck:false,rejected:false,cancelRequested:false,checking:false,cancelling:false});
function read(storage, owner) {
  try {
    const raw=storage?.getItem(PLANNING_JOB_STORAGE_KEY);if(!raw)return null;
    const value=JSON.parse(raw);
    if(!owner || value.owner!==owner || !uuid(value.requestId) || (value.jobId!==null && !uuid(value.jobId)) || Object.keys(value).sort().join(',')!=='jobId,owner,requestId') { storage?.removeItem(PLANNING_JOB_STORAGE_KEY);return null; }
    return value;
  } catch { try{storage?.removeItem(PLANNING_JOB_STORAGE_KEY);}catch{} return null; }
}
// Also clear the default handle when logout happens while the planner is unmounted.
subscribeSession(session => { const storage=defaultStorage();read(storage,session?.user?.id || null); });

/** Only opaque account-bound handles leave memory. POST is never retried implicitly. */
export function createPlanningJobController({ client=createPlanningJobsClient(), onStateChange=()=>{},
  getOwner=()=>getSession()?.user?.id || null, storage=defaultStorage(), pollMs=2000,
  subscribe=subscribeSession, randomUUID=()=>crypto.randomUUID() }={}) {
  let owner=getOwner(), handle=read(storage,owner), state={...empty(),resumable:Boolean(handle)};
  let disposed=false, active=null, timer=null, epoch=0, cancelRequested=false;
  const publish=patch=>{state={...state,...patch};if(!disposed)onStateChange(state);};
  const stopTimer=()=>{clearTimeout(timer);timer=null;};
  const persist=()=>{try{if(handle)storage?.setItem(PLANNING_JOB_STORAGE_KEY,JSON.stringify(handle));else storage?.removeItem(PLANNING_JOB_STORAGE_KEY);}catch{/* Planning remains usable without storage. */}};
  function resetOwner(){const next=getOwner();if(next===owner)return false;owner=next;epoch++;active?.controller.abort();active=null;stopTimer();handle=null;cancelRequested=false;persist();publish(empty());return true;}
  const unsubscribe=subscribe(()=>resetOwner());
  const current=(operation)=>!disposed && operation.epoch===epoch && operation.owner===getOwner() && active===operation && !operation.controller.signal.aborted;
  function schedule(){stopTimer();if(disposed || !handle || state.needsCheck || terminal(state.job?.status))return;timer=setTimeout(()=>{timer=null;void check();},pollMs);}
  function accept(job,preferences){if(terminal(job.status))cancelRequested=false;handle={owner,requestId:job.requestId,jobId:job.id};persist();const pending=job.status==='submission_unknown';publish({job,preferences:preferences || job.preferences || state.preferences,result:job.status==='succeeded'?job.result:null,evidence:job.status==='succeeded'?(job.evidence || null):null,error:'',loading:!terminal(job.status)&&!pending,resumable:true,needsCheck:pending,cancelRequested,checking:false,cancelling:cancelRequested});}
  async function run(kind, action){
    if(disposed || resetOwner() || !owner || active)return {ignored:true};
    stopTimer();const operation={kind,controller:new AbortController(),owner,epoch};active=operation;
    publish({loading:true,error:'',cancelRequested,checking:kind==='check',cancelling:kind==='cancel'||cancelRequested});
    try {const value=await action(operation.controller.signal);if(!current(operation))return {ignored:true};const job=value.job || value;accept(job,value.preferences);return {job};}
    catch(error){if(!current(operation))return {ignored:true};
      const auth=error?.code==='AUTH_REQUIRED';
      if(auth){handle=null;persist();publish({...empty(),error:'Sign in again to check your trip.'});}
      else if(kind==='start' && ['VALIDATION_ERROR','JOB_REJECTED'].includes(error?.code)){handle=null;cancelRequested=false;persist();publish({...empty(),rejected:true,error:'Check your trip details and try again.'});}
      else if(kind==='check' && handle?.jobId && error?.code==='JOB_NOT_FOUND'){
        // A confirmed job identity that is now absent may be purged/deleted.
        // This is NOT evidence that a request-ID-only uncertain create failed.
        cancelRequested=false;
        publish({...empty(),job:{id:handle.jobId,requestId:handle.requestId,status:'expired',result:null,error:{code:'JOB_NOT_FOUND'}},preferences:state.preferences,resumable:true,error:'This planning session is no longer available. Start a new plan when you’re ready.'});
      }
      else publish({loading:false,error:kind==='start'?'We couldn’t confirm whether planning started. Check your trip before starting another.':kind==='cancel'?'We couldn’t confirm the stop. Check your trip before trying again.':'Your trip could not be checked. Please check again shortly.',needsCheck:true,resumable:Boolean(handle),cancelRequested,checking:false,cancelling:false});
      return {error:true};
    } finally {if(active===operation){active=null;if(!disposed){if(cancelRequested && handle?.jobId && !terminal(state.job?.status) && !state.needsCheck)void cancelKnown();else schedule();}}}
  }
  async function check(){
    if(disposed || resetOwner() || !handle || active)return {ignored:true};
    const identity={...handle};
    return run('check',signal=>state.preferences ? (identity.jobId?client.get(identity.jobId,state.preferences,{signal}):client.findRequest(identity.requestId,state.preferences,{signal})) : (identity.jobId?client.resume(identity.jobId,{signal}):client.resumeRequest(identity.requestId,{signal}))); 
  }
  async function cancelKnown(){
    if(!handle?.jobId || terminal(state.job?.status))return {ignored:true};
    const identity=handle.jobId;
    cancelRequested=false;
    return run('cancel',signal=>client.cancel(identity,state.preferences,{signal}));
  }
  const controller={
    snapshot:()=>state,
    isBusy:()=>Boolean(active || (handle && !terminal(state.job?.status))),
    async start(preferences){
      if(disposed || resetOwner() || !owner || active || (handle && !terminal(state.job?.status)))return {ignored:true};
      const checked=validateTripPreferences(preferences);
      if(!checked.valid || !itineraryDates(checked.value).length){handle=null;persist();publish({...empty(),rejected:true,error:'Choose a trip of 1–14 days and check your trip details.'});return {rejected:true};}
      const requestId=randomUUID();if(!uuid(requestId))throw new Error('A valid planning request identifier is required.');
      cancelRequested=false;handle={owner,requestId,jobId:null};persist();publish({...empty(),preferences,resumable:true});
      return run('start',signal=>client.start(preferences,requestId,{signal}));
    },
    resume:check,check,
    async cancel(){
      if(disposed || resetOwner() || !handle || terminal(state.job?.status))return {ignored:true};
      cancelRequested=true;publish({cancelRequested:true,cancelling:true});stopTimer();
      if(active?.kind==='start' || active?.kind==='cancel')return {pending:true};
      if(active){epoch++;active.controller.abort();active=null;}
      if(handle.jobId && !state.needsCheck)return cancelKnown();
      // A lost POST is reconciled read-only before any cancellation is attempted.
      return check();
    },
    clear(){if(active || (handle && !terminal(state.job?.status)))return false;stopTimer();handle=null;cancelRequested=false;persist();publish(empty());return true;},
    dispose(){disposed=true;epoch++;active?.controller.abort();active=null;stopTimer();unsubscribe?.();},
  };
  publish({});return controller;
}
