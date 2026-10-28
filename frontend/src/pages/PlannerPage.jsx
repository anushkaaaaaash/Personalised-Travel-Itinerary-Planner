import AdaptiveSaveTrip from '../components/AdaptiveSaveTrip.jsx';
import AdaptiveRevision from '../components/AdaptiveRevision.jsx';
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
import { createAdaptiveExportController } from '../services/adaptiveExport.js';
import GroundedPlanningProgress from '../components/GroundedPlanningProgress.jsx';
import AdaptivePlanningStatus from '../components/AdaptivePlanningStatus.jsx';
import { createAdaptivePlanningClient, validAdaptivePolicy } from '../services/adaptivePlanning.js';
import { createAdaptivePlanningController } from '../services/adaptivePlanningController.js';
import PlanningJobStatus from '../components/PlanningJobStatus.jsx';
import { createPlanningJobsClient } from '../services/planningJobs.js';
import { createPlanningJobController } from '../services/planningJobController.js';
import { buildTripPayload, createInitialForm } from '../utils/tripPreferences.js';
const emptyRead = { loading: false, error: '', result: null };
export default function PlannerPage({ signedIn = false, jobsEnabled = false, jobClient, jobStorage, jobPollMs, adaptiveEnabled = false, adaptivePolicy = null, adaptiveClient, adaptiveStorage, adaptivePollMs, revisionClient, revisionStorage, revisionPollMs, adaptiveSavedTripsEnabled=false, adaptiveSaveClient, adaptiveSaveStorage }) {
  const reducedMotion = useReducedMotion();
  const useAdaptive = adaptiveEnabled === true && validAdaptivePolicy(adaptivePolicy) && signedIn;
  const useJobs = !useAdaptive && jobsEnabled && signedIn;
  const [adaptiveState,setAdaptiveState] = useState({loading:false,resumable:false,plan:null,error:'',needsCheck:false,sections:[],nextCursor:null,pageCursor:0});
  const [revisionBusy,setRevisionBusy]=useState(false),[previousCompletedPlanId,setPreviousCompletedPlanId]=useState(null),[retainedVersions,setRetainedVersions]=useState([]);
  const [exportState,setExportState]=useState({exporting:false,exportError:''});
  const exportRef=useRef(null),revisionControllerRef=useRef(null);
  const adaptiveRef = useRef(null), pendingRecovery = useRef(null);
  const [jobState,setJobState] = useState({loading:false,resumable:false,job:null,error:'',needsCheck:false});
  const jobRef = useRef(null);
  const [step,setStep] = useState(0), [form,setForm] = useState(createInitialForm);
  useDestinationTheme(form.destination);
  const [fieldErrors,setFieldErrors] = useState({}), [generation,setGeneration] = useState(emptyRead);
  const [refinement,setRefinement] = useState(emptyRead), [edited,setEdited] = useState(false);
  const [viewingPreferences,setViewingPreferences] = useState(false);
  const [recovery,setRecovery] = useState(null);
  const generationRef = useRef(null), refinementRef = useRef(null), mainRef = useRef(null);
  const jobActive = useJobs && Boolean(jobState.loading || jobState.resumable || jobState.job || jobState.needsCheck || jobState.error);
  const jobWaiting = jobActive && !generation.result;
  const adaptiveActive = useAdaptive && Boolean(adaptiveState.resumable || adaptiveState.loading || adaptiveState.plan || adaptiveState.error);
  const adaptiveBusy = revisionBusy || useAdaptive && Boolean(adaptiveState.loading || adaptiveState.needsCheck || (adaptiveState.resumable && !['completed','cancelled','expired'].includes(adaptiveState.plan?.status)));
  const jobBusy = adaptiveBusy || useJobs && Boolean(jobState.loading || jobState.needsCheck || (jobState.job && !['succeeded','failed','cancelled','expired'].includes(jobState.job.status)));
  const showPlan = !viewingPreferences && Boolean(adaptiveActive || jobActive || generation.loading || generation.result || generation.error);
  const valid = buildTripPayload(form);
  const otherVersion=retainedVersions.find(id=>id!==adaptiveState.plan?.id);
  useEffect(()=>{if(adaptiveState.plan?.status==='completed')setRetainedVersions(current=>current.includes(adaptiveState.plan.id)?current:[...current,adaptiveState.plan.id].slice(-2));},[adaptiveState.plan?.id,adaptiveState.plan?.status]);
  async function openRetainedVersion(id,beforeAdopt){const original=adaptiveState.plan?.status==='completed'?adaptiveState.plan.id:null;const value=await adaptiveRef.current?.openCompleted(id,{beforeAdopt:()=>{beforeAdopt?.();revisionControllerRef.current?.clear();}});if(value?.plan?.id===id){if(original&&original!==id)setRetainedVersions(current=>current.includes(original)&&current.includes(id)?current:[original,id]);setViewingPreferences(false);}return value;}
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
  useEffect(()=>{
    if(!useAdaptive)return;
    const controller=createAdaptivePlanningController({client:adaptiveClient || createAdaptivePlanningClient(),storage:adaptiveStorage,pollMs:adaptivePollMs,onStateChange:state=>{
      setAdaptiveState(state);
      if(state.preferences && !state.existingPlan){setForm({...createInitialForm(),...state.preferences});setStep(FINAL_STEP);}
      if(pendingRecovery.current && state.plan?.status==='cancelled'){
        const advice=pendingRecovery.current;pendingRecovery.current=null;
        setRecovery(advice);setStep(advice.editStep===1?1:0);setViewingPreferences(true);
      }
    }});
    adaptiveRef.current=controller;void controller.resume();
    return ()=>{controller.dispose();adaptiveRef.current=null;pendingRecovery.current=null;};
  },[useAdaptive,adaptiveClient,adaptiveStorage,adaptivePollMs]);
  useEffect(()=>{const controller=createAdaptiveExportController({onStateChange:setExportState});exportRef.current=controller;return()=>{controller.dispose();exportRef.current=null;};},[]);
  useEffect(()=>{exportRef.current?.cancel();},[adaptiveState.plan?.id]);
  useEffect(()=>{if(!showPlan)exportRef.current?.cancel();},[showPlan]);
  function reviewAdaptiveChanges(advice){
    if(!advice)return;
    if((!adaptiveState.resumable && !adaptiveState.plan) || ['completed','cancelled','expired'].includes(adaptiveState.plan?.status)){setRecovery(advice);setStep(advice.editStep===1?1:0);setViewingPreferences(true);return;}
    pendingRecovery.current=advice;void adaptiveRef.current?.cancel();
  }
  function clearResult({preserveRecovery=false}={}) { exportRef.current?.cancel(); if(!previousCompletedPlanId)adaptiveRef.current?.clear(); pendingRecovery.current=null; jobRef.current?.clear(); generationRef.current?.reset(); refinementRef.current?.reset(); setEdited(false); setFieldErrors({}); if(!preserveRecovery)setRecovery(null); }
  function handleChange(event) { if(jobBusy)return;const {name,value}=event.target; clearResult({preserveRecovery:true}); setForm(current=>({...current,[name]:value})); }
  function handleToggleInterest(id) { if(jobBusy)return;clearResult({preserveRecovery:true}); setForm(current=>({...current,interests:current.interests.includes(id)?current.interests.filter(item=>item!==id):[...current.interests,id]})); }
  function validatedPayload() { const validation=buildTripPayload(form);const errors=validatePlannerStep(form,FINAL_STEP,{adaptiveEnabled:useAdaptive});const valid=validation.valid && !Object.keys(errors).length;setFieldErrors(errors);if(!valid){setStep(firstErrorStep(errors));setViewingPreferences(true);}return valid?validation.value:null; }
  function handleSubmit(event) { event.preventDefault(); if(step===FINAL_STEP)return;const next=nextPlannerStep(form,step,{adaptiveEnabled:useAdaptive});setFieldErrors(next.errors);setStep(next.step); }
  function handleGenerateItinerary() { if(jobBusy || step!==FINAL_STEP || generationRef.current?.isBusy() || refinementRef.current?.isBusy())return;const payload=validatedPayload();if(!payload){generationRef.current?.reset();refinementRef.current?.reset();return;}if(payload){refinementRef.current?.reset();setEdited(false);setViewingPreferences(false);if(useAdaptive){setGeneration(emptyRead);void adaptiveRef.current?.start(payload);}else if(useJobs){setGeneration(emptyRead);void jobRef.current?.start(payload);}else void generationRef.current?.submit(payload);} }
  async function handleRefine({feedback,vibe,targetDate,maxMainActivitiesPerDay}) { if(generationRef.current?.isBusy() || refinementRef.current?.isBusy())return;const preferences=validatedPayload();if(!preferences || !generation.result)return;const outcome=await refinementRef.current?.submit({preferences,previous:generation.result,feedback,vibe,targetDate,maxMainActivitiesPerDay});if(outcome?.result){setGeneration({loading:false,error:'',result:outcome.result,evidence:null});setEdited(false);} }
  function handleEditDay(day) { refinementRef.current?.reset();setEdited(true);setGeneration(current=>({...current,evidence:null,result:{...current.result,refinementSummary:null,days:current.result.days.map(d=>d.date===day.date?day:d)}})); }
  return <motion.div className="page" initial={reducedMotion?false:{opacity:0}} animate={{opacity:1}} transition={{duration:reducedMotion?0:.2}}>
    <a className="skip-link" href="#trip-planner">Skip to trip planner</a>
    <SiteHeader showSavedTrips={signedIn}/>
    <main id="trip-planner" ref={mainRef} tabIndex={-1} className={`layout journey-layout ${showPlan?'journey-layout--plan':''}`}>
      {showPlan && <div className="journey-toolbar"><span className="eyebrow">{form.destination}</span><button className="back-btn" disabled={refinement.loading || jobBusy} onClick={()=>{if(generation.loading)generationRef.current?.reset();setViewingPreferences(true);}}>← Trip preferences</button>{otherVersion&&<button className="preview-btn" disabled={jobBusy} onClick={()=>openRetainedVersion(otherVersion)}>{retainedVersions.indexOf(otherVersion)===0?'Open previous version':'Open newer version'}</button>}</div>}
      {!showPlan && <>
        <DestinationDiscovery destination={form.destination} onSelect={destination=>handleChange({target:{name:'destination',value:destination}})} />
        <div><PlannerForm adaptivePolicy={adaptivePolicy} adaptiveEnabled={useAdaptive} form={form} onChange={handleChange} onToggleInterest={handleToggleInterest} step={step} onSubmit={handleSubmit} onBack={()=>{setFieldErrors({});setStep(current=>Math.max(0,current-1));}} onGenerateItinerary={handleGenerateItinerary} itineraryLoading={generation.loading || jobBusy} loading={jobBusy} errors={fieldErrors} recovery={recovery} onDismissRecovery={()=>setRecovery(null)}/>
        {previousCompletedPlanId&&<button className="preview-btn return-to-plan" disabled={jobBusy} onClick={async()=>{const value=await adaptiveRef.current?.openCompleted(previousCompletedPlanId);if(value?.plan?.id===previousCompletedPlanId){setPreviousCompletedPlanId(null);setViewingPreferences(false);}}}>Return to the previous retained trip</button>}
        {(generation.result || adaptiveActive) && <button className="preview-btn return-to-plan" onClick={()=>setViewingPreferences(false)}>Return to your itinerary →</button>}</div>
      </>}
      <div className="results-wrap" aria-label="Trip results">
        {showPlan && adaptiveActive && <AdaptivePlanningStatus onResumeExisting={()=>{const result=adaptiveRef.current?.resumeExisting();if(result?.resumed)setViewingPreferences(false);}} onCancelExisting={()=>adaptiveRef.current?.cancelExisting()} {...exportState} onExport={()=>exportRef.current?.download(adaptiveState.plan?.id)} state={adaptiveState} researchEnabled={adaptivePolicy?.researchEnabled===true&&adaptivePolicy?.researchMode==='on_demand'} destination={form.destination} onCheck={()=>adaptiveRef.current?.check()} onCancel={()=>{pendingRecovery.current=null;void adaptiveRef.current?.cancel();}} onContinue={()=>adaptiveRef.current?.continue()} onRetry={()=>adaptiveRef.current?.retry()} onRetryResearch={()=>adaptiveRef.current?.retryResearch()} onLoadPage={cursor=>adaptiveRef.current?.loadPage(cursor)} onEditPreferences={reviewAdaptiveChanges} onNewPlan={()=>{if(adaptiveRef.current?.clear()){setGeneration(emptyRead);setViewingPreferences(true);}}}/> }
        {showPlan && adaptiveActive && !adaptiveState.existingPlan && <GroundedPlanningProgress research={adaptiveState.research} draft={adaptiveState.draft} currency={adaptiveState.draft?.currency} sectionStart={adaptiveState.draft?.sectionStart} sectionEnd={adaptiveState.draft?.sectionEnd}/>}
        {showPlan && adaptiveActive && !adaptiveState.existingPlan && adaptiveState.plan?.status==='completed' && <AdaptiveSaveTrip key={`${adaptiveState.plan.id}:${adaptiveState.plan.version}`} plan={adaptiveState.plan} preferences={adaptiveState.preferences} enabled={adaptiveSavedTripsEnabled===true} client={adaptiveSaveClient} storage={adaptiveSaveStorage} onDownload={()=>exportRef.current?.download(adaptiveState.plan.id)} downloading={exportState.exporting}/>}
        {showPlan && adaptiveActive && adaptiveState.plan?.status==='completed' && adaptivePolicy?.selectedDayRevisions===true && <AdaptiveRevision key={adaptiveState.plan.id} plan={adaptiveState.plan} preferences={adaptiveState.preferences} client={revisionClient} storage={revisionStorage} pollMs={revisionPollMs} onController={controller=>{revisionControllerRef.current=controller;}} onBusyChange={setRevisionBusy} onOpenPlan={openRetainedVersion} onEditWholeTrip={()=>{if(adaptiveRef.current?.prepareNewVersion()){setPreviousCompletedPlanId(adaptiveState.plan.id);setStep(0);setRecovery(null);setViewingPreferences(true);}}}/>}
        {showPlan && !adaptiveActive && jobWaiting && <PlanningJobStatus state={jobState} destination={form.destination} onCheck={()=>jobRef.current?.check()} onCancel={()=>jobRef.current?.cancel()} onNewPlan={()=>{jobRef.current?.clear();setGeneration(emptyRead);setViewingPreferences(true);}}/>}
        {showPlan && !adaptiveActive && !jobWaiting && <GeneratedItinerary preferences={valid.valid?valid.value:null} {...generation} edited={edited} refinement={refinement} onEditDay={handleEditDay} onRefine={handleRefine} onCancelRefine={()=>refinementRef.current?.reset()} onEditPreferences={advice=>{generationRef.current?.reset();setRecovery(advice || null);setStep(advice?.editStep===1?1:0);setViewingPreferences(true);}} onRetry={handleGenerateItinerary} onCancel={()=>generationRef.current?.reset()}/>}
        {signedIn && !adaptiveActive && !generation.loading && !jobBusy && <SavedItineraries signedIn={signedIn} preferences={valid.valid?valid.value:null} itinerary={generation.result} plannerBusy={generation.loading || refinement.loading || jobBusy} onLoad={record=>{clearResult();setForm({...createInitialForm(),...record.preferences});setGeneration({loading:false,error:'',result:record.itinerary});setStep(FINAL_STEP);setViewingPreferences(false);}}/>}
      </div>
    </main>
  </motion.div>;
}
