import { savedRequest, snapshot } from './savedItineraries.js';
import { generateItinerary, refineItinerary } from './itineraries.js';
import { getSession } from './session.js';
import { PlannerRequestError } from './readRequest.js';
export const validTripId=id=>typeof id==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(id);
export const isAiAction=action=>action==='generate'||action==='refine';
export function detailRefinementState(state) {
  return {loading:state.busy,canCancel:state.busy&&isAiAction(state.activeAction),
    loadingLabel:state.activeAction==='update'?'Saving revision.':state.activeAction==='load'?'Loading saved revision.':'Regenerating.'};
}
// This facade deliberately does not change the legacy preference-only tripsAPI.get.
export const savedTripsAPI={
  get:(id,options)=>savedRequest({action:'load',id},options),
  update:(id,version,record,options)=>savedRequest({action:'update',id,expectedVersion:version,record},options),
  generate:generateItinerary,refine:refineItinerary,
};
export function createDetailController(id,onState,{api=savedTripsAPI,session=getSession}={}) {
  let disposed=false,active=null,activeAction=null,state={record:null,plan:null,title:'',dirty:false,busy:false,activeAction:null,error:'',notice:''};
  const publish=patch=>{state={...state,...patch};if(!disposed)onState(state);};
  async function run(action,input) {
    if(disposed||active)return {ignored:true};
    if(!validTripId(id)){publish({error:'Invalid saved itinerary ID.'});return;}
    const owner=session();if(!owner){publish({record:null,plan:null,error:'Sign in to open this private saved itinerary.'});return;}
    const controller=new AbortController();active=controller;activeAction=action;publish({busy:true,activeAction:action,error:'',notice:''});
    try{
      let result;const options={signal:controller.signal};
      if(action==='load')result=await api.get(id,options);
      else if(action==='update')result=await api.update(id,state.record.version,snapshot(state.title,state.record.preferences,state.plan),options);
      else if(action==='generate')result=await api.generate(state.record.preferences,options);
      else if(action==='refine')result=await api.refine({preferences:state.record.preferences,previous:state.plan,...input},options);
      else throw new Error('Unsupported action');
      if(disposed||controller.signal.aborted||session()!==owner)return {ignored:true};
      if(action==='load')publish({record:result,plan:result.itinerary,title:result.title,dirty:false});
      else if(action==='update')publish({record:result,dirty:false,notice:'Updated the same saved itinerary. The revision is confirmed.'});
      else publish({plan:result,dirty:true,notice:'New local plan accepted. Review it, then explicitly update the saved revision if wanted.'});
      return {result};
    }catch(e){if(disposed||controller.signal.aborted||session()!==owner)return {ignored:true};publish({error:e instanceof PlannerRequestError?e.message:'The request could not be verified. Your open plan was retained.'});return {error:true};}
    finally{if(active===controller){active=null;activeAction=null;if(!disposed&&session()===owner)publish({busy:false,activeAction:null});}}
  }
  return {run,edit(patch){if(disposed||active||!state.record)return;publish({...patch,dirty:true,notice:''});},
    cancel(){
      // Canceling a PUT cannot prove it did not commit. Only AI operations are cancelable here.
      if(disposed||!active||!isAiAction(activeAction))return false;
      active.abort();active=null;activeAction=null;
      publish({busy:false,activeAction:null,notice:'AI request canceled locally. The open plan was retained; no storage request was made by this AI action.'});return true;
    },dispose(){disposed=true;active?.abort();active=null;activeAction=null;}};
}
