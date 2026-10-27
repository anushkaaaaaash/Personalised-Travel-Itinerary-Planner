import { useDestinationTheme } from '../themes/DestinationTheme.jsx';
import { motion, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { FINAL_STEP, firstErrorStep, nextPlannerStep, validatePlannerStep } from '../utils/plannerSteps.js';
import DestinationDiscovery from '../components/DestinationDiscovery.jsx';
import GeneratedItinerary from '../components/GeneratedItinerary.jsx';
import SavedItineraries from '../components/SavedItineraries.jsx';
import { createReadRequest } from '../services/readRequest.js';
import { generateItinerary, refineItinerary } from '../services/itineraries.js';
import SiteHeader from '../components/SiteHeader.jsx';
import PlannerForm from '../components/PlannerForm.jsx';
import PlanningJobStatus from '../components/PlanningJobStatus.jsx';
import { createPlanningJobsClient } from '../services/planningJobs.js';
import { createPlanningJobController } from '../services/planningJobController.js';
import { buildTripPayload, createInitialForm } from '../utils/tripPreferences.js';
const emptyRead = { loading: false, error: '', result: null };
export default function PlannerPage({ signedIn = false, jobsEnabled = false, jobClient, jobStorage, jobPollMs }) {
  const reducedMotion = useReducedMotion();
  const useJobs = jobsEnabled && signedIn;
  const [jobState,setJobState] = useState({loading:false,resumable:false,job:null,error:'',needsCheck:false});
  const jobRef = useRef(null);
  const [step,setStep] = useState(0), [form,setForm] = useState(createInitialForm);
  useDestinationTheme(form.destination);
  const [fieldErrors,setFieldErrors] = useState({}), [generation,setGeneration] = useState(emptyRead);
  const [refinement,setRefinement] = useState(emptyRead), [edited,setEdited] = useState(false);
  const [viewingPreferences,setViewingPreferences] = useState(false);
  const generationRef = useRef(null), refinementRef = useRef(null), mainRef = useRef(null);
  const jobActive = useJobs && Boolean(jobState.loading || jobState.resumable || jobState.job || jobState.needsCheck || jobState.error);
  const jobWaiting = jobActive && !generation.result;
  const jobBusy = useJobs && Boolean(jobState.loading || jobState.needsCheck || (jobState.job && !['succeeded','failed','cancelled','expired'].includes(jobState.job.status)));
  const showPlan = !viewingPreferences && Boolean(jobActive || generation.loading || generation.result || generation.error);
  const valid = buildTripPayload(form);
  useEffect(()=>{ if(showPlan)mainRef.current?.focus(); },[showPlan]);
  useEffect(() => {
    const generationController = createReadRequest({ request: generateItinerary, onStateChange: setGeneration });
    const refinementController = createReadRequest({ request: refineItinerary, onStateChange: setRefinement });
    generationRef.current = generationController; refinementRef.current = refinementController;
    return () => { generationController.dispose(); refinementController.dispose(); };
  }, []);
  useEffect(()=>{
    if(!useJobs)return;
    const controller=createPlanningJobController({client:jobClient || createPlanningJobsClient({enabled:jobsEnabled}),storage:jobStorage,pollMs:jobPollMs,onStateChange:state=>{
      setJobState(state);
      if(state.preferences){setForm({...createInitialForm(),...state.preferences});setStep(FINAL_STEP);}
      if(state.result){setGeneration({loading:false,error:'',result:state.result,evidence:state.evidence || null});setViewingPreferences(false);}
    }});
    jobRef.current=controller;
    void controller.resume();
    return ()=>{controller.dispose();jobRef.current=null;};
  },[useJobs,jobClient,jobStorage,jobPollMs]);
  function clearResult() { jobRef.current?.clear(); generationRef.current?.reset(); refinementRef.current?.reset(); setEdited(false); setFieldErrors({}); }
  function handleChange(event) { if(jobBusy)return;const {name,value}=event.target; clearResult(); setForm(current=>({...current,[name]:value})); }
  function handleToggleInterest(id) { if(jobBusy)return;clearResult(); setForm(current=>({...current,interests:current.interests.includes(id)?current.interests.filter(item=>item!==id):[...current.interests,id]})); }
  function validatedPayload() { const validation=buildTripPayload(form);const errors=validatePlannerStep(form,FINAL_STEP);const valid=validation.valid && !Object.keys(errors).length;setFieldErrors(errors);if(!valid){setStep(firstErrorStep(errors));setViewingPreferences(true);}return valid?validation.value:null; }
  function handleSubmit(event) { event.preventDefault(); if(step===FINAL_STEP)return;const next=nextPlannerStep(form,step);setFieldErrors(next.errors);setStep(next.step); }
  function handleGenerateItinerary() { if(jobBusy || step!==FINAL_STEP || generationRef.current?.isBusy() || refinementRef.current?.isBusy())return;const payload=validatedPayload();if(!payload){generationRef.current?.reset();refinementRef.current?.reset();return;}if(payload){refinementRef.current?.reset();setEdited(false);setViewingPreferences(false);if(useJobs){setGeneration(emptyRead);void jobRef.current?.start(payload);}else void generationRef.current?.submit(payload);} }
  async function handleRefine({feedback,vibe,targetDate,maxMainActivitiesPerDay}) { if(generationRef.current?.isBusy() || refinementRef.current?.isBusy())return;const preferences=validatedPayload();if(!preferences || !generation.result)return;const outcome=await refinementRef.current?.submit({preferences,previous:generation.result,feedback,vibe,targetDate,maxMainActivitiesPerDay});if(outcome?.result){setGeneration({loading:false,error:'',result:outcome.result,evidence:null});setEdited(false);} }
  function handleEditDay(day) { refinementRef.current?.reset();setEdited(true);setGeneration(current=>({...current,evidence:null,result:{...current.result,refinementSummary:null,days:current.result.days.map(d=>d.date===day.date?day:d)}})); }
  return <motion.div className="page" initial={reducedMotion?false:{opacity:0}} animate={{opacity:1}} transition={{duration:reducedMotion?0:.2}}>
    <a className="skip-link" href="#trip-planner">Skip to trip planner</a>
    <SiteHeader />
    <main id="trip-planner" ref={mainRef} tabIndex={-1} className={`layout journey-layout ${showPlan?'journey-layout--plan':''}`}>
      {showPlan && <div className="journey-toolbar"><span className="eyebrow">{form.destination}</span><button className="back-btn" disabled={refinement.loading || jobBusy} onClick={()=>{if(generation.loading)generationRef.current?.reset();setViewingPreferences(true);}}>← Trip preferences</button></div>}
      {!showPlan && <>
        <DestinationDiscovery destination={form.destination} onSelect={destination=>handleChange({target:{name:'destination',value:destination}})} />
        <div><PlannerForm form={form} onChange={handleChange} onToggleInterest={handleToggleInterest} step={step} onSubmit={handleSubmit} onBack={()=>{setFieldErrors({});setStep(current=>Math.max(0,current-1));}} onGenerateItinerary={handleGenerateItinerary} itineraryLoading={generation.loading || jobBusy} loading={jobBusy} errors={fieldErrors}/>
        {generation.result && <button className="preview-btn return-to-plan" onClick={()=>setViewingPreferences(false)}>Return to your itinerary →</button>}</div>
      </>}
      <div className="results-wrap" aria-label="Trip results">
        {showPlan && jobWaiting && <PlanningJobStatus state={jobState} destination={form.destination} onCheck={()=>jobRef.current?.check()} onCancel={()=>jobRef.current?.cancel()} onNewPlan={()=>{jobRef.current?.clear();setGeneration(emptyRead);setViewingPreferences(true);}}/>}
        {showPlan && !jobWaiting && <GeneratedItinerary preferences={valid.valid?valid.value:null} {...generation} edited={edited} refinement={refinement} onEditDay={handleEditDay} onRefine={handleRefine} onCancelRefine={()=>refinementRef.current?.reset()} onEditPreferences={()=>{generationRef.current?.reset();setStep(0);setViewingPreferences(true);}} onRetry={handleGenerateItinerary} onCancel={()=>generationRef.current?.reset()}/>}
        {signedIn && !generation.loading && !jobBusy && <SavedItineraries signedIn={signedIn} preferences={valid.valid?valid.value:null} itinerary={generation.result} plannerBusy={generation.loading || refinement.loading || jobBusy} onLoad={record=>{clearResult();setForm({...createInitialForm(),...record.preferences});setGeneration({loading:false,error:'',result:record.itinerary});setStep(FINAL_STEP);setViewingPreferences(false);}}/>}
      </div>
    </main>
  </motion.div>;
}
