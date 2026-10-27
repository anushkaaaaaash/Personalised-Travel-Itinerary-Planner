import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
import { getSession, subscribeSession } from './session.js';
import { adaptiveId, createAdaptivePlanningClient, hasProposedConstraintDetails } from './adaptivePlanning.js';
export const ADAPTIVE_STORAGE_KEY='travel.adaptive-plan.v1';
const terminal=status=>['completed','cancelled','expired'].includes(status);
const initial=()=>({plan:null,preferences:null,attemptedPreferences:null,existingPlan:null,discoveryPending:false,retainedTerminalHandle:false,sections:[],nextCursor:null,pageCursor:0,loading:false,error:'',errorCode:null,needsCheck:false,resumable:false,checking:false,cancelling:false,cancelRequested:false,cancelUnconfirmed:false});
const safeErrorCode=error=>['AUTH_REQUIRED','VALIDATION_ERROR','ADAPTIVE_REJECTED','ADAPTIVE_NOT_FOUND','ADAPTIVE_CONFLICT','ADAPTIVE_UNAVAILABLE','ADAPTIVE_INVALID_RESPONSE','ADAPTIVE_OUTCOME_UNCONFIRMED','SECTION_MONEY_INVALID','SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT','ADAPTIVE_RATE_LIMITED','ADAPTIVE_CURRENT_NOT_FOUND'].includes(error?.code)?error.code:'ADAPTIVE_OUTCOME_UNCONFIRMED';
const defaultStorage=()=>{try{return globalThis.sessionStorage;}catch{return null;}};
function read(storage,owner) {
  try {const raw=storage?.getItem(ADAPTIVE_STORAGE_KEY);if(!raw)return null;const value=JSON.parse(raw);
    if(!owner||value.owner!==owner||!adaptiveId(value.requestId)||(value.planId!==null&&!adaptiveId(value.planId))||Object.keys(value).sort().join(',')!=='owner,planId,requestId')throw Error();
    return value;
  }catch{try{storage?.removeItem(ADAPTIVE_STORAGE_KEY);}catch{}return null;}
}
subscribeSession(session=>read(defaultStorage(),session?.user?.id || null));
/** Sequential server checkpoints; polls are reads only. Every spend action is explicit. */
export function createAdaptivePlanningController({client=createAdaptivePlanningClient(),onStateChange=()=>{},getOwner=()=>getSession()?.user?.id||null,storage=defaultStorage(),subscribe=subscribeSession,pollMs=2000,randomUUID=()=>crypto.randomUUID()}={}) {
  let owner=getOwner(),handle=read(storage,owner),state={...initial(),resumable:Boolean(handle)},active=null,timer=null,epoch=0,disposed=false,wantsCancel=false,cancellingExisting=false,previousStart=null;
  const publish=patch=>{state={...state,...patch};if(!disposed)onStateChange(state);};
  const stop=()=>{clearTimeout(timer);timer=null;};
  const persist=()=>{try{if(handle)storage?.setItem(ADAPTIVE_STORAGE_KEY,JSON.stringify(handle));else storage?.removeItem(ADAPTIVE_STORAGE_KEY);}catch{}};
  function resetOwner(){if(owner===getOwner())return false;owner=getOwner();epoch++;active?.controller.abort();active=null;stop();handle=null;wantsCancel=false;cancellingExisting=false;previousStart=null;persist();publish(initial());return true;}
  const unsubscribe=subscribe(resetOwner);
  function schedule(){stop();if(!disposed&&handle&&!state.existingPlan&&!state.discoveryPending&&!state.needsCheck&&state.plan?.status==='active')timer=setTimeout(()=>{timer=null;void check();},pollMs);}
  const current=op=>!disposed&&active===op&&epoch===op.epoch&&owner===getOwner()&&!op.controller.signal.aborted;
  function accept(value,cursor,kind){
    if(cancellingExisting){
      if(['cancelled','expired'].includes(value.plan.status)){
        const draft=state.attemptedPreferences || state.preferences;
        handle=null;cancellingExisting=false;wantsCancel=false;persist();publish({...initial(),preferences:draft});return;
      }
      if(kind==='check'||value.plan.status==='completed')cancellingExisting=false;
      publish({existingPlan:value,loading:false,checking:false,cancelling:false,cancelRequested:false,needsCheck:cancellingExisting,cancelUnconfirmed:cancellingExisting,error:'',errorCode:null});return;
    }

    if(terminal(value.plan.status))wantsCancel=false;
    handle={owner,requestId:value.plan.requestId || handle.requestId,planId:value.plan.id};persist();
    publish({...value,existingPlan:null,discoveryPending:false,retainedTerminalHandle:false,preferences:value.plan.status==='expired'?(value.preferences || state.preferences):value.preferences,pageCursor:cursor,loading:false,error:'',errorCode:null,needsCheck:value.plan.activeSection?.status==='submission_unknown',resumable:true,checking:false,cancelling:wantsCancel,cancelRequested:wantsCancel,cancelUnconfirmed:false});
  }
  async function run(kind,action,cursor=0) {
    if(disposed||resetOwner()||!owner||active)return{ignored:true};stop();
    const op={kind,controller:new AbortController(),epoch};active=op;publish({loading:true,error:'',errorCode:null,checking:kind==='check',cancelling:kind==='cancel'||wantsCancel,cancelRequested:wantsCancel});
    try{const value=await action(op.controller.signal);if(!current(op))return{ignored:true};if(kind==='discover'){publish({existingPlan:value,discoveryPending:true,loading:false,checking:false,error:'',errorCode:'SECTION_OWNER_PLAN_EXISTS',resumable:true,needsCheck:false});}else accept(value,cursor,kind);return value;}
    catch(error){if(!current(op))return{ignored:true};
      if(error?.code==='AUTH_REQUIRED'){handle=null;wantsCancel=false;cancellingExisting=false;previousStart=null;persist();publish({...initial(),error:'Sign in again to check your trip.',errorCode:'AUTH_REQUIRED'});}
      else if(kind==='discover'&&error?.confirmed&&error.code==='ADAPTIVE_CURRENT_NOT_FOUND'){
        publish({existingPlan:null,discoveryPending:false,loading:false,checking:false,error:'',errorCode:null,needsCheck:false,resumable:Boolean(handle)&&!state.retainedTerminalHandle});
      }
      // These are confirmed no-create admissions; retain the attempted draft and prior handle.
      else if(kind==='start'&&error?.confirmed&&['SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT','ADAPTIVE_RATE_LIMITED'].includes(error.code)){
        const draft=state.preferences;handle=previousStart?.handle || null;persist();
        publish({...initial(),preferences:draft,attemptedPreferences:draft,retainedTerminalHandle:Boolean(handle),loading:false,error:'This planning request was not started.',errorCode:error.code,discoveryPending:error.code==='SECTION_OWNER_PLAN_EXISTS',resumable:error.code==='SECTION_OWNER_PLAN_EXISTS',needsCheck:false});
      }
      else if(kind==='start'&&error?.confirmed&&['VALIDATION_ERROR','ADAPTIVE_REJECTED','SECTION_MONEY_INVALID'].includes(error.code)){handle=null;persist();publish({...initial(),error:error.code==='SECTION_MONEY_INVALID'?'Check your budget format.':'Check your trip details.',errorCode:safeErrorCode(error)});}
      else if(['check','page'].includes(kind)&&handle?.planId&&error?.confirmed&&error.code==='ADAPTIVE_PLAN_UNAVAILABLE'){
        // Keep the opaque identity until the user acknowledges this terminal state.
        // In particular, request-ID-only ambiguity must never take this branch.
        wantsCancel=false;
        if(cancellingExisting){const draft=state.attemptedPreferences || state.preferences;handle=null;cancellingExisting=false;persist();publish({...initial(),preferences:draft});return{unavailable:true};}
        publish({...initial(),plan:{id:handle.planId,requestId:handle.requestId,status:'expired',activeSection:null},preferences:state.preferences,resumable:true,errorCode:'ADAPTIVE_PLAN_UNAVAILABLE'});
      }
      else publish({errorCode:safeErrorCode(error),loading:false,checking:false,cancelling:false,cancelRequested:false,needsCheck:true,resumable:Boolean(handle)||state.discoveryPending||Boolean(state.existingPlan),cancelUnconfirmed:kind==='cancel'||state.cancelUnconfirmed,error:kind==='cancel'?'The stop could not be confirmed. Check this trip before trying again.':kind==='check'||kind==='page'?'This trip could not be checked. Your saved checkpoints have not been replaced.':'The change could not be confirmed. Check this trip before continuing; no automatic retry was made.'});
      return{error:true};
    }finally{if(active===op){active=null;if(!disposed){if(kind==='start'&&state.errorCode==='SECTION_OWNER_PLAN_EXISTS')void discoverCurrent();else if(wantsCancel&&handle?.planId&&!terminal(state.plan?.status)&&(!state.needsCheck||(state.plan?.activeSection?.status==='submission_unknown'&&!state.cancelUnconfirmed)))void cancelKnown();else schedule();}}}
  }
  // Discovery is read-only and cannot supersede an unresolved create identity.
  async function discoverCurrent(){if(disposed||resetOwner()||!owner||active||!client.current||(handle&&!state.discoveryPending&&!terminal(state.plan?.status)&&!state.retainedTerminalHandle))return{ignored:true};publish({discoveryPending:true});return run('discover',signal=>client.current({signal}));}
  async function check(){if(state.discoveryPending&&!cancellingExisting)return discoverCurrent();if(!handle)return discoverCurrent();if(disposed||resetOwner()||!handle||active)return{ignored:true};const identity={...handle};return run('check',signal=>identity.planId?client.get(identity.planId,{signal,afterSequence:state.pageCursor}):client.findRequest(identity.requestId,{signal}),state.pageCursor);}
  async function cancelKnown(){wantsCancel=false;return run('cancel',signal=>client.cancel(handle.planId,{signal}));}
  const controller={
    snapshot:()=>state,isBusy:()=>Boolean(active||state.existingPlan||state.discoveryPending||(handle&&!terminal(state.plan?.status)&&!state.retainedTerminalHandle)),
    async start(preferences){
      if(disposed||resetOwner()||!owner||active||state.existingPlan||state.discoveryPending||(handle&&!terminal(state.plan?.status)&&!state.retainedTerminalHandle))return{ignored:true};
      const checked=validateTripPreferences(preferences);if(!checked.valid){publish({...initial(),error:'Check your trip details.'});return{rejected:true};}
      const requestId=randomUUID();if(!adaptiveId(requestId))throw Error('Invalid request identifier');
      previousStart={handle:handle?{...handle}:null,state};handle={owner,requestId,planId:null};wantsCancel=false;persist();publish({...initial(),preferences:checked.value,resumable:true});
      return run('start',signal=>client.start(checked.value,requestId,{signal}));
    },
    check,resume:check,
    resumeExisting(){if(disposed||resetOwner()||active||state.needsCheck||cancellingExisting||!state.existingPlan)return{ignored:true};const value=state.existingPlan;accept(value,0);schedule();return{resumed:true};},
    cancelExisting(){if(disposed||resetOwner()||active||state.needsCheck||cancellingExisting||!state.existingPlan||terminal(state.existingPlan.plan.status))return Promise.resolve({ignored:true});const value=state.existingPlan;handle={owner,requestId:value.plan.requestId,planId:value.plan.id};cancellingExisting=true;persist();return run('cancel',signal=>client.cancel(handle.planId,{signal}));},
    continue(){if(active||state.needsCheck||state.plan?.status!=='paused'||!(state.plan.pauseReason==='RESOURCE_ALLOWANCE_REACHED'||(state.plan.pauseReason==='SECTION_FAILED'&&state.plan.remainingCreates===0)||(state.plan.pauseReason==='STORAGE_LIMIT'&&state.plan.storagePauseScope==='global')))return Promise.resolve({ignored:true});return run('continue',signal=>client.continue(handle.planId,randomUUID(),{signal}));},
    retry(){const section=state.plan?.activeSection;if(active||state.needsCheck||state.plan?.status!=='paused'||state.plan.remainingCreates<1||section?.status!=='failed'||(section.errorCode==='SECTION_BUDGET_EXHAUSTED'||(section.errorCode==='SECTION_CONSTRAINT_CONFLICT'&&!hasProposedConstraintDetails(section))))return Promise.resolve({ignored:true});return run('retry',signal=>client.retry(handle.planId,randomUUID(),section.id,{signal}));},
    loadPage(afterSequence=0){if(active||!handle?.planId||!Number.isSafeInteger(afterSequence)||afterSequence<0)return Promise.resolve({ignored:true});return run('page',signal=>client.get(handle.planId,{signal,afterSequence}),afterSequence);},
    async cancel(){
      if(disposed||resetOwner()||!handle||terminal(state.plan?.status))return{ignored:true};
      wantsCancel=true;publish({cancelRequested:true,cancelling:true});stop();
      if(active&& !['check','page'].includes(active.kind))return{pending:true};
      if(active){epoch++;active.controller.abort();active=null;}
      if(handle.planId&&(!state.needsCheck||(state.plan?.activeSection?.status==='submission_unknown'&&!state.cancelUnconfirmed)))return cancelKnown();
      return check();
    },
    clear(){if(active||state.existingPlan||state.discoveryPending||(handle&&!terminal(state.plan?.status)&&!state.retainedTerminalHandle))return false;stop();handle=null;wantsCancel=false;cancellingExisting=false;previousStart=null;persist();publish(initial());return true;},
    dispose(){disposed=true;epoch++;active?.controller.abort();active=null;stop();unsubscribe?.();},
  };
  publish({});return controller;
}
