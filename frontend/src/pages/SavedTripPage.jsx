import { travelError } from '../utils/travelMessages.js';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowLeft, RefreshCw, Save } from 'lucide-react';
import { createDetailController, detailRefinementState, isAiAction } from '../services/savedTripDetail.js';
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
    <Link to="/" onClick={e=>{if(state.dirty&&!window.confirm('Leave this page and discard your current edits?'))e.preventDefault();}}><ArrowLeft size={16} aria-hidden="true"/> Back to planner</Link>
    <section className="card"><h1>Your saved trip</h1><p>Only you can open this trip. Use a summary to share your plans.</p>
    {state.busy&&<p role="status">Getting your trip ready…</p>}{state.error&&<p role="alert">{travelError(state.error)}</p>}{state.notice&&<p role="status">{state.notice.startsWith('Updated') ? 'Your changes are saved.' : state.notice.startsWith('New local') ? 'Your new plan is ready.' : state.notice.includes('canceled') ? 'Your previous plan is ready to explore.' : state.notice}</p>}
    {!state.record&&!state.busy&&<button onClick={()=>controller.current?.run('load')}>Retry loading saved itinerary</button>}
    {state.record&&<><p>Saved revision {state.record.version}{state.dirty?' · editing':''}</p><label className="field">Itinerary title<input maxLength={120} value={state.title} disabled={state.busy} onChange={e=>edit({title:e.target.value})}/></label>
      <div className="step-actions"><button disabled={state.busy} onClick={()=>setConfirm('update')}><Save size={16} aria-hidden="true"/> Update this saved itinerary</button><button disabled={state.busy} onClick={()=>setConfirm('generate')}><RefreshCw size={16} aria-hidden="true"/> Build a fresh plan</button><button disabled={state.busy} onClick={()=>setConfirm('load')}>Reload saved revision</button></div>
      {confirm&&<div role="group" aria-label="Confirm detail operation"><p>{confirm==='generate'?'Build a fresh plan with these trip preferences?':confirm==='load'?'Reload the saved revision and discard current local edits?':'Save your changes to this trip?'}</p><button disabled={state.busy} onClick={commit}>Confirm {confirm}</button><button disabled={state.busy} onClick={()=>setConfirm(null)}>Cancel</button></div>}
    </>}
    </section>
    {state.plan&&<GeneratedItinerary result={state.plan} preferences={state.record.preferences} edited={state.dirty} refinement={detailRefinementState(state)} onCancelRefine={isAiAction(state.activeAction)?()=>controller.current?.cancel():undefined} onRefine={input=>controller.current?.run('refine',input)} onEditDay={day=>edit({plan:{...state.plan,refinementSummary:null,days:state.plan.days.map(d=>d.date===day.date?day:d)}})}/>}
  </motion.main>;
}
