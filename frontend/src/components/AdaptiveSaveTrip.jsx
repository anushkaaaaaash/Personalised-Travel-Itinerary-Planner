import {useEffect,useRef,useState} from 'react';
import {Link,useInRouterContext} from 'react-router-dom';
import {createAdaptiveSaveController} from '../services/savedAdaptiveSaveController.js';

export default function AdaptiveSaveTrip({plan,preferences,enabled=false,onDownload,downloading=false,client,storage}) {
  const [title,setTitle]=useState(`${preferences.destination} · ${preferences.startDate}`),[state,setState]=useState({loading:false,pending:false,checked:false,needsCheck:false,operation:null,error:''});
  const controller=useRef(null),inRouter=useInRouterContext();
  useEffect(()=>{
    if(enabled!==true)return;
    const current=createAdaptiveSaveController({plan,client,storage,onStateChange:setState});controller.current=current;setState(current.snapshot());
    if(current.snapshot().pending)void current.check();
    return()=>{current.dispose();if(controller.current===current)controller.current=null;};
  },[enabled,plan.id,plan.version,client,storage]);
  useEffect(()=>{if(state.ownerChanged)setTitle('');},[state.ownerChanged]);
  const operation=state.operation,finished=operation?.status==='complete',sameVersion=operation?.sourcePlanId===plan.id&&operation?.sourceVersion===plan.version;
  const expired=operation?.status==='expired',canStart=!expired&&!state.pending&&!state.needsCheck&&(!finished||!sameVersion)&&!state.ownerChanged;
  const identifiable=Number.isSafeInteger(plan.version)&&plan.version>0;
  return <section className="card adaptive-section" aria-label="Save completed trip"><p className="eyebrow">Keep this trip</p><h2>Save this version to your account</h2>
    <p>A confirmed account copy keeps every planned day, even after this temporary plan expires.</p>
    {enabled!==true?<p>Account saving is not available right now. Download the full retained plan before its temporary retention expires.</p>:state.ownerChanged?<p role="status">Sign in again to save a trip for your account.</p>:<>
      {!identifiable&&<p role="status">This trip’s save version could not be verified. Check the retained plan before saving; you can still download it.</p>}
      {state.error&&<p role="alert">{state.error}</p>}
      {state.loading&&<p role="status">{operation?.status==='staging'?'Saving your complete itinerary…':'Checking or saving this trip…'}</p>}
      {operation&&!sameVersion&&<p>This save belongs to an earlier trip version: <strong>{operation.title}</strong>. It does not save the trip currently shown above.</p>}
      {finished&&<><p role="status">{sameVersion?'This complete trip version is saved to your account.':'The earlier trip version is saved to your account.'}</p>{inRouter&&<Link className="preview-btn" to={`/saved-adaptive-trips/${operation.savedId}`}>Open saved trip</Link>}</>}
      {expired&&<p role="status">This unfinished save expired. It was not published as an account-saved trip.</p>}
      {canStart&&identifiable&&<form onSubmit={event=>{event.preventDefault();void controller.current?.start(title);}}><label className="field"><span>Trip name</span><input value={title} maxLength={120} onChange={event=>setTitle(event.target.value)} disabled={state.loading} required/></label><button className="generate-btn" type="submit" disabled={state.loading||!title.trim()||Date.parse(plan.expiresAt)<=Date.now()}>Save this trip</button></form>}
      <div className="step-actions">
        {state.needsCheck&&<button className="preview-btn" disabled={state.loading} onClick={()=>controller.current?.check()}>Check pending save</button>}
        {!state.loading&&!state.needsCheck&&operation?.status==='staging'&&<><p>Part of your trip has been copied. Resume to finish saving all days.</p><button className="generate-btn" disabled={Date.parse(operation.stagingExpiresAt)<=Date.now()} onClick={()=>controller.current?.resume()}>Resume this save</button><button className="preview-btn" onClick={()=>controller.current?.check()}>Check pending save</button></>}
        {state.loading&&<button className="preview-btn" onClick={()=>controller.current?.pause()}>Pause saving</button>}
        {expired&&<button className="preview-btn" onClick={()=>controller.current?.clear()}>Dismiss expired save</button>}
      </div>
      {operation?.status==='staging'&&<p className="hint">Unfinished copy available until <time dateTime={operation.stagingExpiresAt}>{new Date(operation.stagingExpiresAt).toLocaleString()}</time>. Pausing stops browser continuation; a request already sent may still finish. Check before resuming.</p>}
    </>}
    {onDownload&&<div className="step-actions"><button className="preview-btn" disabled={downloading} onClick={onDownload}>{downloading?'Preparing download…':'Download a PDF copy instead'}</button></div>}
  </section>;
}
