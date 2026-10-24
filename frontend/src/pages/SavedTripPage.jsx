import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowLeft, RefreshCw, Save } from 'lucide-react';
import { createDetailController } from '../services/savedTripDetail.js';
import GeneratedItinerary from '../components/GeneratedItinerary.jsx';
export default function SavedTripPage(){const {tripID}=useParams();return <SavedTripEditor key={tripID} tripID={tripID}/>;}
export function SavedTripEditor({tripID}) {
  const [state,setState]=useState({record:null,plan:null,title:'',dirty:false,busy:false,error:'',notice:''}),[confirm,setConfirm]=useState(null);
  const controller=useRef(null),reducedMotion=useReducedMotion();
  useEffect(()=>{const c=createDetailController(tripID,setState);controller.current=c;void c.run('load');return()=>c.dispose();},[tripID]);
  useEffect(()=>{if(!state.dirty)return;const warn=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[state.dirty]);
  function edit(patch){setConfirm(null);controller.current?.edit(patch);}
  async function commit(){const action=confirm;setConfirm(null);if(action)await controller.current?.run(action);}
  return <motion.main className="page" initial={reducedMotion?false:{opacity:0}} animate={{opacity:1}}>
    <Link to="/" onClick={e=>{if(state.dirty&&!window.confirm('Leave this page and discard unsaved local edits?'))e.preventDefault();}}><ArrowLeft size={16} aria-hidden="true"/> Back to planner</Link>
    <section className="card"><h1>Private saved itinerary</h1><p>This address requires the owning account. Sharing its URL does not grant access. Back/Forward navigation loads the saved revision; save local edits before navigating.</p>
    {state.busy&&<p role="status">Waiting for a validated response.</p>}{state.error&&<p role="alert">{state.error}</p>}{state.notice&&<p role="status">{state.notice}</p>}
    {!state.record&&!state.busy&&<button onClick={()=>controller.current?.run('load')}>Retry loading saved itinerary</button>}
    {state.record&&<><p>Saved revision {state.record.version}{state.dirty?' — local changes not saved':''}</p><label className="field">Itinerary title<input maxLength={120} value={state.title} disabled={state.busy} onChange={e=>edit({title:e.target.value})}/></label>
      <div className="step-actions"><button disabled={state.busy} onClick={()=>setConfirm('update')}><Save size={16} aria-hidden="true"/> Update this saved itinerary</button><button disabled={state.busy} onClick={()=>setConfirm('generate')}><RefreshCw size={16} aria-hidden="true"/> Regenerate local plan</button><button disabled={state.busy} onClick={()=>setConfirm('load')}>Reload saved revision</button></div>
      {confirm&&<div role="group" aria-label="Confirm detail operation"><p>{confirm==='generate'?'Request a new AI plan using the saved preferences? The current plan stays until a validated response arrives. Nothing is saved automatically.':confirm==='load'?'Reload the saved revision and discard current local edits?':'Replace this saved revision with the current plan and title? A conflict will keep your local edits.'}</p><button disabled={state.busy} onClick={commit}>Confirm {confirm}</button><button disabled={state.busy} onClick={()=>setConfirm(null)}>Cancel</button></div>}
    </>}
    </section>
    {state.plan&&<GeneratedItinerary result={state.plan} preferences={state.record.preferences} edited={state.dirty} refinement={{loading:state.busy}} onCancelRefine={()=>controller.current?.cancel()} onRefine={input=>controller.current?.run('refine',input)} onEditDay={day=>edit({plan:{...state.plan,refinementSummary:null,days:state.plan.days.map(d=>d.date===day.date?day:d)}})}/>}
  </motion.main>;
}
