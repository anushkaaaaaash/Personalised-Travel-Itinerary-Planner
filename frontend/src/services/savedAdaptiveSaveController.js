import {getSession as sessionNow,subscribeSession} from './session.js';
import {adaptiveId} from './adaptivePlanning.js';
import {createSavedAdaptiveClient,SavedAdaptiveError} from './savedAdaptiveTrips.js';
export const ADAPTIVE_SAVE_STORAGE_KEY='travel.adaptive-save.v1';
const terminal=value=>value&&['complete','expired'].includes(value.status);
const safeStorage=()=>{try{return globalThis.sessionStorage;}catch{return null;}};
const initial=()=>({operation:null,loading:false,pending:false,checked:false,needsCheck:false,error:'',errorCode:null,ownerChanged:false});
const definiteRejection=new Set(['SAVED_ADAPTIVE_INVALID_REQUEST']);
export function createAdaptiveSaveController({plan,client=createSavedAdaptiveClient(),storage=safeStorage(),onStateChange=()=>{},getSession=sessionNow,subscribe=subscribeSession,randomUUID=()=>crypto.randomUUID()}={}) {
  let session=getSession(),owner=session?.user?.id,handle=null,state=initial(),active=null,disposed=false,titleForRequest=null;
  const publish=patch=>{state={...state,...patch};if(!disposed)onStateChange(state);};
  const persist=()=>{try{if(handle)storage?.setItem(ADAPTIVE_SAVE_STORAGE_KEY,JSON.stringify(handle));else storage?.removeItem(ADAPTIVE_SAVE_STORAGE_KEY);}catch{}};
  try{const raw=storage?.getItem(ADAPTIVE_SAVE_STORAGE_KEY);if(raw){const value=JSON.parse(raw);if(!owner||value.owner!==owner||Object.keys(value).sort().join(',')!=='owner,requestId,sourcePlanId,sourceVersion'||!adaptiveId(value.requestId)||!adaptiveId(value.sourcePlanId)||!Number.isSafeInteger(value.sourceVersion)||value.sourceVersion<1)throw Error();handle=value;}}catch{try{storage?.removeItem(ADAPTIVE_SAVE_STORAGE_KEY);}catch{}}
  state={...state,pending:Boolean(handle),checked:!handle};
  const valid=op=>!disposed&&active===op&&!op.controller.signal.aborted&&getSession()===session&&owner===getSession()?.user?.id;
  function identityChanged(next=getSession()){
    if(next===session)return false;active?.controller.abort();active=null;const changed=next?.user?.id!==owner;session=next;owner=next?.user?.id;
    if(changed){handle=null;titleForRequest=null;persist();publish({...initial(),checked:true,ownerChanged:true});}
    else publish({loading:false,needsCheck:Boolean(handle),error:handle?'Your session changed. Check this same save before continuing.':'',checked:!handle});
    return true;
  }
  const unsubscribe=subscribe(identityChanged);
  function accept(value){
    if(!handle||value.requestId!==handle.requestId||value.sourcePlanId!==handle.sourcePlanId||value.sourceVersion!==handle.sourceVersion)throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_RESPONSE');
    if((titleForRequest!==null&&value.title!==titleForRequest)||(state.operation&&(value.totalSections!==state.operation.totalSections||value.savedSections<state.operation.savedSections)))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_RESPONSE');
    if(value.saved&&value.sourcePlanId===plan.id&&value.sourceVersion===plan.version&&(value.saved.totalDays!==plan.totalDays||value.saved.spentCents!==plan.spentCents||value.saved.totalBudgetCents!==plan.totalBudgetCents))throw new SavedAdaptiveError('SAVED_ADAPTIVE_INVALID_RESPONSE');
    titleForRequest=value.title;publish({operation:value,checked:true,pending:!terminal(value),needsCheck:false,error:'',errorCode:null});
  }
  async function run(kind,work){
    if(disposed||identityChanged()||!owner||active)return{ignored:true};
    const op={controller:new AbortController()};active=op;publish({loading:true,error:'',errorCode:null});
    try{return await work(op);}catch(error){
      if(!valid(op))return{ignored:true};
      if(kind==='start'&&!state.operation&&error instanceof SavedAdaptiveError&&error.confirmed&&definiteRejection.has(error.code)){handle=null;persist();publish({...initial(),checked:true,error:error.message,errorCode:error.code});}
      else publish({needsCheck:Boolean(handle),checked:false,pending:Boolean(handle),error:error instanceof SavedAdaptiveError?error.message:'The save outcome is unconfirmed. Check this same save before trying another write.',errorCode:error instanceof SavedAdaptiveError?error.code:'SAVED_ADAPTIVE_UNCONFIRMED'});
      return{error:true};
    }finally{if(active===op){active=null;publish({loading:false});}}
  }
  async function copy(op,title,previous=0){
    for(let requests=0;requests<1026;requests++){
      if(!valid(op)||!handle)return{ignored:true};
      const value=await client.save(handle.sourcePlanId,{requestId:handle.requestId,title,expectedVersion:handle.sourceVersion},{signal:op.controller.signal});
      if(!valid(op))return{ignored:true};accept(value);
      if(terminal(value))return value;
      if(value.savedSections<=previous||Date.parse(value.stagingExpiresAt)<=Date.now()){
        publish({needsCheck:true,checked:false,error:'Saving has paused because progress or the save window needs to be checked. Check this same save before continuing.'});return{paused:true};
      }
      previous=value.savedSections;
    }
    publish({needsCheck:true,checked:false,error:'Saving has paused at its request limit. Check this same save before continuing.'});return{paused:true};
  }
  return{
    snapshot:()=>state,
    async start(title){
      if(disposed||identityChanged()||!owner||active||state.ownerChanged||state.needsCheck||(handle&&!terminal(state.operation)))return{ignored:true};
      if(plan?.status!=='completed'||!adaptiveId(plan.id)||!Number.isSafeInteger(plan.version)||plan.version<1||!Number.isFinite(Date.parse(plan.expiresAt))||Date.parse(plan.expiresAt)<=Date.now()||typeof title!=='string'||!title.trim()||title.trim().length>120||/[\u0000-\u001f\u007f]/.test(title)){publish({error:'Choose a complete, available trip version and a name of up to 120 characters.'});return{rejected:true};}
      const requestId=randomUUID();if(!adaptiveId(requestId))throw Error('Invalid save request identity');
      handle={owner,requestId,sourcePlanId:plan.id,sourceVersion:plan.version};titleForRequest=title.trim();persist();
      try{if(storage?.getItem(ADAPTIVE_SAVE_STORAGE_KEY)!==JSON.stringify(handle))throw Error();}catch{handle=null;titleForRequest=null;publish({error:'This browser cannot keep the save request identity safely. Allow session storage or download the trip instead.'});return{rejected:true};}
      publish({...initial(),pending:true});return run('start',op=>copy(op,title.trim()));
    },
    check(){if(!handle||disposed||identityChanged()||active)return Promise.resolve({ignored:true});return run('check',async op=>{const value=await client.check(handle.requestId,{signal:op.controller.signal});if(!valid(op))return{ignored:true};accept(value);return value;});},
    resume(){if(!handle||state.needsCheck||!state.checked||state.operation?.status!=='staging'||Date.parse(state.operation.stagingExpiresAt)<=Date.now())return Promise.resolve({ignored:true});const {title,savedSections}=state.operation;return run('resume',op=>copy(op,title,savedSections));},
    pause(){if(!active)return;active.controller.abort();active=null;publish({loading:false,needsCheck:true,checked:false,error:'Browser continuation is paused. An in-flight save may still finish; check this same save before continuing.'});},
    clear(){if(active||(handle&&!terminal(state.operation)))return false;handle=null;titleForRequest=null;persist();publish({...initial(),checked:true});return true;},
    dispose(){disposed=true;active?.controller.abort();active=null;unsubscribe();},
  };
}
