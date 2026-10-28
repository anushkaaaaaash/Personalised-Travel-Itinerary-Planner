import PlanningWaitGuidance from './PlanningWaitGuidance.jsx';
import {tripDayLabel,visibleDayRange} from '../utils/dayLabels.js';
import AdaptiveCostSummary from './AdaptiveCostSummary.jsx';
import { COST_LABELS } from '../services/itineraries.js';
import { useId, useState } from 'react';
import DestinationLoading from './DestinationLoading.jsx';
import { tripFailureRecovery } from '../utils/travelMessages.js';
import { hasProposedConstraintDetails } from '../services/adaptivePlanning.js';

const adviceSteps = {budget:1,travelPace:1,destination:0,departureCity:0,mobilityConcerns:1,dietaryNeeds:1};
const money = (currency,value) => `${currency} ${(value/100).toLocaleString(undefined,{maximumFractionDigits:2})}`;
const terminal = status => ['completed','cancelled','expired'].includes(status);
const pauseCategory = plan => plan?.pauseReason==='SECTION_FAILED' ? ({SECTION_CONSTRAINT_CONFLICT:'CONSTRAINT_CONFLICT',SECTION_BUDGET_EXHAUSTED:'BUDGET_EXHAUSTED'}[plan.activeSection?.errorCode] || plan.pauseReason) : plan?.pauseReason;
const sectionFailures = {
  SECTION_AUTO_RETRYABLE_FAILURE: ['Automatic recovery couldn’t finish these days.', 'Automatic recovery could not complete these days within the available allowance. Your completed days are kept. Planning is paused rather than repeating requests indefinitely.'],
  SECTION_AUTO_RETRYABLE_INCOMPLETE: ['Automatic recovery returned an incomplete plan.', 'The remaining days could not be completed within the current recovery limit. Your finished days are kept; no dates or preferences were changed.'],
  SECTION_RESPONSE_UNAVAILABLE: ['The planning response is no longer available.', 'The service could not retrieve this response. No replacement request was started automatically. Your completed days are kept; you can decide whether to try again within the available allowance.'],
  SECTION_RESEARCH_REQUESTED: ['Checking details for this section.', 'The planner requested outside information before continuing. This is not a problem with your trip preferences.'],
  SECTION_RESEARCH_UNAVAILABLE: ['Current research is not available for this section.', 'The planner could not use up-to-date research notes, so this section was not added. Your dates and budget have not been identified as a problem.'],
  SECTION_PROVIDER_REJECTED: ['The planning service couldn’t start this section.', 'The service rejected this section request. This does not show that your trip preferences are invalid.'],
  SECTION_DEADLINE_REACHED: ['This section reached its time limit.', 'The section did not finish within the service’s processing time limit. Your trip dates have not been shortened.'],
  SECTION_PROVIDER_FAILED: ['The planning service couldn’t finish this section.', 'The service failed while producing this section. Your trip preferences have not been identified as a problem.'],
  SECTION_PROVIDER_INCOMPLETE: ['The returned section was incomplete.', 'The service stopped before returning a complete section, so it was not added to your plan.'],
  SECTION_OUTPUT_LIMIT: ['The returned section was incomplete.', 'This section exceeded the service’s output allowance. It was not added to your plan; your full trip dates are unchanged.'],
  SECTION_INVALID_RESULT: ['This section didn’t pass its checks.', 'The returned section was not usable, so it was not added to your plan. This does not mean you need to change your preferences.'],
  SECTION_CONTINUITY_CONFLICT: ['This section didn’t connect to the previous one.', 'The returned section did not start where the preceding section ended. It was not added to your plan.'],
  SECTION_RETURN_MISSING: ['The returned section missed the return journey.', 'The final section did not include the required return journey. It was not added to your plan.'],
  SECTION_REST_CONFLICT: ['The returned section left too little rest.', 'The generated schedule did not leave the required rest between sections. It was not added to your plan; this is a problem with the returned schedule, not proof that your chosen pace is wrong.'],
  SECTION_TRAVEL_DOUBLE_COUNT: ['The returned section counted travel twice.', 'The cost checks found duplicate journey costs. The section was not added to your plan; increasing your budget is not the fix for this error.'],
  SECTION_BUDGET_EXCEEDED: ['The returned section exceeded its budget.', 'The generated costs exceeded the available trip budget, so the section was not added. This does not prove that your trip is impossible at your chosen budget.'],
  SECTION_INVALID_COST: ['This section’s costs didn’t pass their checks.', 'The returned cost estimates were not usable, so the section was not added to your plan. Your budget has not been changed.'],
  SECTION_CHECKPOINT_INVALID: ['This section couldn’t be safely retained.', 'The service could not verify the section checkpoint, so it was not added to your plan. Your trip preferences have not been identified as a problem.'],
  SECTION_RESPONSE_MISMATCH: ['The service returned an unexpected section.', 'The response did not match the section being planned, so it was not added to your trip. Your preferences have not been identified as a problem.'],
  SECTION_STRATEGY_CONFLICT: ['This section didn’t follow the trip route.', 'The generated section did not preserve the planned journey between locations, so it was not added to your trip.'],
  SECTION_STRATEGY_INVALID: ['The returned trip route didn’t pass its checks.', 'The generated route did not cover your full dates correctly, so the section was not added to your trip.'],
  SECTION_TRANSFER_MISSING: ['The returned section missed a transfer.', 'The generated schedule changed locations without including the required transfer, so it was not added to your trip.'],
  SECTION_REPEAT_CONFLICT: ['The returned section repeated an activity.', 'The generated schedule repeated a recent activity instead of continuing the trip, so it was not added. Your interests do not need to change because of this error.'],
};

export function adaptiveRecovery(plan) {
  if (pauseCategory(plan) === 'BUDGET_EXHAUSTED') return {
    code:'TRIP_BUDGET_EXHAUSTED',title:'The remaining days need a budget review.',
    message:'The estimates for completed sections have used the available trip budget. The remaining days have not been planned, and no budget or dates have been changed.',
    retryable:false,editStep:1,recommendations:[{field:'budget',reason:'There is no remaining budget available for the unplanned days.',suggestion:'Review the completed-section estimates and your total group budget. Choose whether to revise the budget or your trip preferences before starting a revised plan.'}],
  };
  const details=plan?.activeSection?.failureDetails;
  if(pauseCategory(plan)==='CONSTRAINT_CONFLICT') {
    const recommendations=(Array.isArray(details?.recommendations)?details.recommendations:[]).slice(0,3).filter(item=>Object.hasOwn(adviceSteps,item?.field)&&typeof item.suggestion==='string'&&typeof item.reason==='string').map(({field,reason,suggestion})=>({field,reason:reason.slice(0,500),suggestion:suggestion.slice(0,500)}));
    return {code:'CONSTRAINT_CONFLICT',title:recommendations.length?'Suggestions for this part of your trip.':'This section needs a review.',message:typeof details?.explanation==='string'?details.explanation.slice(0,1000):'The service reported conflicting preferences but did not provide specific changes to review. Your entries are kept; no changes have been made.',retryable:false,editStep:recommendations.length?Math.min(...recommendations.map(item=>adviceSteps[item.field])):0,recommendations,proposed:true};
  }
  const code=plan?.activeSection?.errorCode;
  if(Object.hasOwn(sectionFailures,code)) {
    const [title,message]=sectionFailures[code];
    return {code,title,message,retryable:true,editStep:null,recommendations:[]};
  }
  const recovery=tripFailureRecovery({code});
  return recovery.code==='REQUEST_FAILED' ? {...recovery,title:'This section couldn’t be completed.'} : recovery;
}

export function adaptiveRequestRecovery(code) {
  if(code==='SECTION_MONEY_INVALID')return {code,title:'Check the budget’s number format.',message:'The planner could not represent this budget in whole cents. This is a number-format limit, not a judgment that your trip budget is too low. Planning has not started.',retryable:false,editStep:1,recommendations:[{field:'budget',reason:'The planner stores money in whole cents within a supported numeric range.',suggestion:'Enter a total group budget greater than zero, with at most two decimal places and no more than 90,071,992,547,409.91 in the selected currency.'}]};
  if(code==='AUTH_REQUIRED')return tripFailureRecovery({code});
  if(code==='VALIDATION_ERROR')return tripFailureRecovery({code});
  const categories={
    SECTION_OWNER_PLAN_EXISTS:['You already have an unfinished trip.','An unfinished trip is still retained for your account. Open that trip before deciding whether to continue it or stop it. Your new trip details do not need to change.'],
    SECTION_CAPACITY_LIMIT:['Planning is temporarily full.','The service has reached its current planning capacity. No new plan was started. Wait and try again later; changing your dates or budget will not resolve this limit.'],
    ADAPTIVE_RATE_LIMITED:['Please wait before trying again.','The service is limiting new requests for now. No new plan was started. Your trip details are unchanged; wait before submitting again.'],
    ADAPTIVE_UNAVAILABLE:['We couldn’t check the planning service.','The service could not be reached or is temporarily unavailable. Check this same trip before starting another planning request.'],
    ADAPTIVE_INVALID_RESPONSE:['The planning status couldn’t be verified.','The service returned an unusable checkpoint response. Check this same trip; no replacement request has been started.'],
    ADAPTIVE_NOT_FOUND:['This planning session couldn’t be found.','The service could not locate this planning session. Its outcome is not confirmed; check again before starting another request.'],
    ADAPTIVE_CONFLICT:['The planning state needs to be checked.','The service reported a conflicting planning state. Check this same trip before trying another change.'],
    ADAPTIVE_REJECTED:['This planning request was rejected.','The service did not accept this request, but did not identify a specific preference to change. Your entries are kept; no budget or date adjustment has been inferred.'],
  };
  const [title,message]=categories[code] || ['Let’s check where planning stopped.','The last request could not be confirmed. Check this same trip before starting another planning request. Your completed sections have not been replaced.'];
  return {code,title,message,retryable:false,editStep:null,recommendations:[]};
}

export function researchQueryRecovery() {
  return {code:'RESEARCH_QUERY_INVALID',title:'Use public place names for research.',message:'This research request did not start because a destination or departure-city entry was not suitable for a public search. This is a place-name format check, not a problem with your dates or budget.',retryable:false,editStep:0,recommendations:[{field:'destination',reason:'Only public place names can be sent for research.',suggestion:'Review the destination: use a city, region or country name, without a URL, email address or contact details.'},{field:'departureCity',reason:'Transport research may also need a public departure-city name.',suggestion:'Review the departure city: use its place name only, without a URL, email address or contact details.'}]};
}

function ExistingPlanningRecovery({state,onResumeExisting,onCancelExisting,onCheck}) {
  const [confirmStop,setConfirmStop]=useState(false);
  const confirmationId=useId();
  const {plan,preferences}=state.existingPlan;
  const busy=state.loading || state.cancelling;
  const stopUnconfirmed=state.cancelUnconfirmed;
  const uncertain=stopUnconfirmed || state.needsCheck;
  const finished=terminal(plan.status),expired=plan.status==='expired';
  const title={completed:'Your trip has finished planning.',cancelled:'Planning for this trip has stopped.',expired:'Your previous planning session has expired.'}[plan.status] || 'You have an unfinished trip.';
  const message={completed:'All requested days have a completed plan. Open it to review the result; no new planning request is needed.',cancelled:'Open the retained completed sections to review them. No further sections are being planned.',expired:'The temporary checkpoints are no longer available. Review this session to return to your trip details.'}[plan.status] || 'Open your existing trip to review what is already planned. A new plan cannot start while this trip is unfinished.';
  const openLabel={completed:'Open completed trip',cancelled:'Open retained trip',expired:'Review expired session'}[plan.status] || 'Resume existing trip';
  return <section className="adaptive-planning" aria-label="Unfinished trip recovery">
    <article className="card adaptive-progress">
      <p className="eyebrow">{preferences.destination}</p><h2>{title}</h2>
      <p role="status">{state.cancelling?'Stopping this unfinished trip…':state.reconnecting?'Reconnecting automatically to this trip. No replacement is being started.':stopUnconfirmed?'We couldn’t confirm that planning stopped. Check this trip’s status before trying again.':uncertain?'We couldn’t verify this trip’s latest status. Check it before continuing.':message}</p>
      <p>Your trip · <time dateTime={preferences.startDate}>{preferences.startDate}</time> to <time dateTime={preferences.endDate}>{preferences.endDate}</time></p>
      {!expired&&<p><strong>{plan.completedDays} of {plan.totalDays} days planned</strong></p>}
      <p className="hint">This is a temporary plan kept for 24 hours, not an account-saved itinerary.{!expired&&Number.isFinite(Date.parse(plan.expiresAt))&&<> Available until <time dateTime={plan.expiresAt}>{new Date(plan.expiresAt).toLocaleString()}</time>.</>}</p>
      <div className="step-actions">
        {uncertain?(onCheck&&!state.reconnecting?<button className="generate-btn" disabled={busy} onClick={onCheck}>Check existing trip</button>:null):onResumeExisting&&<button className="generate-btn" disabled={busy||uncertain} onClick={onResumeExisting}>{openLabel}</button>}
        {onCancelExisting&&!uncertain&&!finished&&<button className="preview-btn" disabled={busy} aria-expanded={confirmStop} aria-controls={confirmationId} onClick={()=>setConfirmStop(value=>!value)}>Stop existing trip</button>}
      </div>
      {confirmStop&&!uncertain&&!finished&&<section id={confirmationId} className="adaptive-export" aria-label="Confirm stopping this trip">
        <h3>Stop this unfinished trip?</h3>
        <p>This stops further planning for {preferences.destination}. Completed sections stay available until this temporary plan expires. It does not delete an account-saved itinerary or start a new plan.</p>
        <div className="step-actions"><button className="preview-btn" disabled={busy} onClick={()=>setConfirmStop(false)}>Keep this trip</button><button className="generate-btn" disabled={busy} onClick={onCancelExisting}>Yes, stop this trip</button></div>
      </section>}
    </article>
  </section>;
}

function CompletedSection({section,currency,tripStart}) {
  const itinerary=section.checkpoint.itinerary;
  return <section className="adaptive-day-group" aria-label={`Trip days ${section.startDate} to ${section.endDate}`}>
    {itinerary.days.map((day,index)=><details className="card adaptive-day" key={day.date}>
      <summary><strong>{tripDayLabel(day.date,tripStart)}</strong> · <time dateTime={day.date}>{day.date}</time> · {day.mainActivityCount} main activities</summary>
      <ol className="activity-list timeline">{day.activities.map(activity=><li key={activity.id}><div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} min</span>{activity.fixedTime&&<span className="tag">Fixed time</span>}</div><strong>{activity.title}</strong><p>{activity.notes}</p></li>)}</ol>
      <div className="day-notes"><p><strong>Dining</strong><br/>{day.dining}</p><p><strong>Getting around & taking a break</strong><br/>{day.transitAndRest}</p><p><strong>Dietary arrangements · confirm with venues</strong><br/>{day.dietaryNotes}</p><p><strong>Access · confirm with venues</strong><br/>{day.mobilityNotes}</p></div>
      <details className="secondary-tools"><summary>Day outline</summary><p><strong>Morning</strong><br/>{day.morning}</p><p><strong>Afternoon</strong><br/>{day.afternoon}</p><p><strong>Evening</strong><br/>{day.evening}</p></details>
      <details className="secondary-tools"><summary>Day expense breakdown</summary><p className="hint">Estimated costs for the whole group, not per person.</p><ul className="budget-list">{Object.entries(COST_LABELS).map(([key,label])=><li key={key}><span>{label}</span><span>{money(currency,Math.round(day.costs[key]*100))}</span></li>)}</ul></details>
      {index===0&&<details className="secondary-tools"><summary>Route &amp; costs · {section.startDate} to {section.endDate}</summary>
      <p>{section.checkpoint.startLocation} → {section.checkpoint.endLocation}</p>
      <p className="hint">Estimate for these dates · {money(currency,section.checkpoint.spentCents)} for the whole group.</p>
      {itinerary.explanation && <p>{itinerary.explanation}</p>}
      <ul className="budget-list">{Object.entries(COST_LABELS).map(([key,label])=><li key={key}><span>{label}</span><span>{money(currency,itinerary.days.reduce((total,day)=>total+Math.round(day.costs[key]*100),0))}</span></li>)}</ul>
      {itinerary.warnings.length>0 && <><h3>Things to check</h3><ul>{itinerary.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></>}
    </details>}
    </details>)}
  </section>;
}

function ConfirmResearchRun({allowance,disabled,onContinue}) {
  const [confirm,setConfirm]=useState(false),id=useId();
  return <div><button className="generate-btn" disabled={disabled} aria-expanded={confirm} aria-controls={id} onClick={()=>setConfirm(value=>!value)}>Continue with another run</button>
    {confirm&&<section id={id} className="adaptive-export" aria-label="Confirm another planning run"><h3>Allow another bounded run?</h3><p>This allows up to {allowance} more model requests, including research and retries, plus a fresh allowance of up to 6 search/tool requests. Earlier usage is not refunded. Your dates and completed days stay unchanged.</p><div className="step-actions"><button className="preview-btn" disabled={disabled} onClick={()=>setConfirm(false)}>Not now</button><button className="generate-btn" disabled={disabled} onClick={onContinue}>Yes, continue this trip</button></div></section>}
  </div>;
}

export default function AdaptivePlanningStatus({state,dayFeed,destination,onCheck,onCancel,onContinue,onRetry,onRetryResearch,onLoadPage,onNewPlan,onEditPreferences,onResumeExisting,onCancelExisting,onExport,researchEnabled=false,exporting=false,exportError=''}) {
  if(state.existingPlan)return <ExistingPlanningRecovery key={state.existingPlan.plan.id} state={state} onResumeExisting={onResumeExisting} onCancelExisting={onCancelExisting} onCheck={onCheck}/>;
  const plan=state.plan;
  const shownSections=dayFeed?.sections.length?dayFeed.sections:state.sections || [];
  const shownDays=shownSections.reduce((sum,section)=>sum+(section.checkpoint?.itinerary?.days?.length || 0),0);
  const withResearch=researchEnabled===true||Boolean(state.research);
  const uncertain=state.needsCheck || plan?.activeSection?.status==='submission_unknown' || plan?.pauseReason==='SUBMISSION_UNKNOWN';
  const busy=state.loading || state.cancelling;
  const activeWait=plan?.status==='active'&&!uncertain&&!state.error&&state.research?.status!=='submission_unknown';
  const hasSession=Boolean(plan || state.resumable);
  const pauseReason=pauseCategory(plan);
  const requestRecovery=adaptiveRequestRecovery(state.errorCode);
  const needsBudgetEdit=!hasSession&&state.errorCode==='SECTION_MONEY_INVALID';
  const queryInvalid=plan?.status==='paused'&&plan.pauseReason==='RESEARCH_FAILED'&&state.research?.errorCode==='RESEARCH_QUERY_INVALID';
  const recovery=queryInvalid?researchQueryRecovery():needsBudgetEdit?requestRecovery:adaptiveRecovery(plan);
  if(!plan && !uncertain && !state.error) return <DestinationLoading destination={state.preferences?.destination || destination} title={state.discoveryPending?'Checking for an unfinished trip…':state.resumable?'Picking up your trip…':'Starting your trip plan…'} status={state.discoveryPending?'Looking for a retained plan in your account. No new plan is being started.':state.cancelling?'Stopping planning…':'Your dated itinerary will appear here as it is ready.'} onCancel={state.discoveryPending||busy&&state.cancelling?undefined:onCancel} cancelLabel="Stop planning"/>;
  const allowancePause=plan?.status==='paused' && (pauseReason==='RESOURCE_ALLOWANCE_REACHED' || (pauseReason==='SECTION_FAILED'&&plan.remainingCreates===0) || (pauseReason==='RESEARCH_ALLOWANCE_REACHED'&&state.research&&!['submitting','running','submission_unknown'].includes(state.research.status)));
  const researchNeedsCheck=plan?.status==='paused'&&pauseReason==='RESEARCH_FAILED'&&state.research?.status==='failed'&&(plan.remainingCreates<1||state.research.toolCallsReserved>4);
  const canRetryResearch=plan?.status==='paused'&&pauseReason==='RESEARCH_FAILED'&&state.research?.status==='failed'&&state.research.errorCode!=='RESEARCH_QUERY_INVALID'&&plan.remainingCreates>0&&state.research.toolCallsReserved<=4;
  const sharedStoragePause=plan?.status==='paused' && plan.pauseReason==='STORAGE_LIMIT' && plan.storagePauseScope==='global';
  const proposedRetry=plan?.status==='paused' && pauseReason==='CONSTRAINT_CONFLICT' && plan.remainingCreates>0 && plan.activeSection?.status==='failed' && hasProposedConstraintDetails(plan.activeSection);
  const canRetry=proposedRetry || plan?.status==='paused' && plan.pauseReason==='SECTION_FAILED' && plan.remainingCreates>0 && plan.activeSection?.status==='failed' && !['SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED'].includes(plan.activeSection.errorCode);
  const canReview=queryInvalid || needsBudgetEdit || plan?.status==='paused' && ['CONSTRAINT_CONFLICT','BUDGET_EXHAUSTED'].includes(pauseReason);
  const expired=plan?.status==='expired';
  const currency=state.preferences?.currency || 'USD';
  let title='Your trip is taking shape.', message='Planning your next days. You can explore the finished days below while you wait.';
  if(plan?.status==='completed'){title='Your trip is ready.';message='Explore your day-by-day itinerary below.';}
  else if(plan?.status==='cancelled'){title='Planning has stopped.';message='Planning has stopped. Your finished days are still available below.';}
  else if(expired){title='This planning session has expired.';message='These checkpoints are no longer available here. Return to your trip details to decide what to do next.';}
  else if(state.reconnecting){title='Reconnecting to your trip.';message='The connection was interrupted. We’re checking this same trip automatically. Your finished days are kept; no new plan is being started.';}
  else if(uncertain || state.error){title=requestRecovery.title;message=requestRecovery.message;}
  else if(allowancePause){title='Ready for the next part?';message=withResearch?'This run has reached a research or model-request allowance. Your full dates and completed days are kept. Continuing requires your confirmation of another bounded run.':`This run has reached its planning-request allowance. Your full trip dates are kept. ${Number.isSafeInteger(plan.runAllowance)&&plan.runAllowance>=1&&plan.runAllowance<=12?`Continue only when you want to allow up to ${plan.runAllowance} more planning requests.`:'Continue only when you want to allow another bounded run of planning requests.'}`;}
  else if(plan?.pauseReason==='STORAGE_LIMIT'){title=sharedStoragePause?'Planning storage is temporarily full.':'This plan has reached its storage allowance.';message=sharedStoragePause?'Shared planning storage is currently full. You can check capacity and resume this same session; if it is still full, no new section request will be started. Your existing request allowance and dates are unchanged.':'This plan has reached its temporary storage allowance. No further sections can be added in this session. Your dates and budget have not been changed.';}
  else if(queryInvalid){title=recovery.title;message=recovery.message;}
  else if(plan?.status==='paused'&&['RESEARCH_FAILED','RESEARCH_SUBMISSION_UNKNOWN','RESEARCH_ALLOWANCE_REACHED'].includes(plan.pauseReason)){title='Research needs attention.';message='This part of the trip is waiting for usable research. See the research status below. Your dates, budget and completed sections have not been changed.';}
  else if(plan?.status==='paused'){title=recovery.title;message=recovery.message;}
  else if(['queued','submitting','running'].includes(state.research?.status)){title='Researching your journey.';message='Checking travel details for your next days. Your finished days remain available below.';}
  return <section className="adaptive-planning" aria-label="Day-by-day trip planning">
    <article className="card adaptive-progress"><p className="eyebrow">{state.preferences?.destination || destination || 'Your trip'}</p><h2>{state.cancelling?'Stopping planning…':title}</h2>
      <p role="status">{plan?.status==='paused'&&'Planning is paused. '}{message}</p>
      {state.preferences&&<p className="hint">Your full trip · <time dateTime={state.preferences.startDate}>{state.preferences.startDate}</time> to <time dateTime={state.preferences.endDate}>{state.preferences.endDate}</time></p>}
      {plan?.pauseReason==='STORAGE_LIMIT'&&Number.isFinite(Date.parse(plan.expiresAt))&&<p className="hint">Finished days remain available until <time dateTime={plan.expiresAt}>{new Date(plan.expiresAt).toLocaleString()}</time>.</p>}
      {!expired&&Number.isSafeInteger(plan?.totalDays)&&plan.totalDays>0&&<div className="adaptive-progress__count"><strong>{plan.completedDays} of {plan.totalDays} days planned</strong><progress aria-label="Days with completed plans" max={plan.totalDays} value={plan.completedDays}/></div>}
      {plan&&<PlanningWaitGuidance key={plan.id} planId={plan.id} totalDays={plan.totalDays} expiresAt={plan.expiresAt} active={activeWait}/>}
      {plan&&<div hidden={!activeWait}><DestinationLoading key={`notes-${plan.id}`} notesOnly embedded active={activeWait} destination={state.preferences?.destination || destination}/></div>}
      {!expired&&plan&&<AdaptiveCostSummary plan={plan} currency={currency} travelers={state.preferences?.travelers}/>}
      {canReview&&recovery.proposed&&<p className="hint">These are planning suggestions to review, not verified prices, availability or travel restrictions.</p>}
      {canReview&&recovery.recommendations.length>0&&<ul className="recovery-recommendations">{recovery.recommendations.map((item,index)=><li key={`${item.field}-${index}`}><strong>{item.suggestion}</strong>{item.reason&&<p>{item.reason}</p>}</li>)}</ul>}
      {!uncertain&&proposedRetry&&<p className="hint">Retry this section without changing your preferences. Your completed days are kept; this uses one request from the current allowance.</p>}
      {!uncertain&&canRetryResearch&&<p className="hint">Retrying research uses one model request and reserves 2 search/tool requests from this run’s remaining allowance. Completed sections are kept; no preferences are changed.</p>}
      <div className="step-actions">
        {!uncertain&&state.errorCode==='SECTION_OWNER_PLAN_EXISTS'&&onCheck&&<button className="generate-btn" disabled={busy} onClick={onCheck}>Find my unfinished trip</button>}
        {(uncertain||researchNeedsCheck)&&!state.reconnecting&&onCheck&&<button className="generate-btn" disabled={busy} onClick={onCheck}>Check planning status</button>}
        {!uncertain&&allowancePause&&onContinue&&(withResearch?<ConfirmResearchRun key={`${plan.id}-${plan.remainingCreates}-${state.research?.toolCallsReserved ?? 0}`} allowance={plan.runAllowance} disabled={busy||state.cancelRequested} onContinue={onContinue}/>:<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onContinue}>Continue planning</button>)}
        {!uncertain&&canRetryResearch&&onRetryResearch&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onRetryResearch}>Retry research</button>}
        {!uncertain&&sharedStoragePause&&onContinue&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onContinue}>Check capacity and continue</button>}
        {!uncertain&&canRetry&&onRetry&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onRetry}>{proposedRetry?'Retry remaining section':'Try this section again'}</button>}
        {!uncertain&&canReview&&onEditPreferences&&<button className={proposedRetry?'preview-btn':'generate-btn'} disabled={busy||state.cancelRequested} onClick={()=>onEditPreferences(recovery)}>{needsBudgetEdit?'Review budget format':'Stop planning and review changes'}</button>}
        {hasSession&&!terminal(plan?.status)&&onCancel&&<button className="preview-btn" disabled={state.cancelling||state.cancelRequested} onClick={onCancel}>Stop planning</button>}
        {(terminal(plan?.status)||!hasSession)&&onNewPlan&&<button className="preview-btn" disabled={busy} onClick={onNewPlan}>Back to trip details</button>}
      </div>
      {!expired&&plan?.completedDays>0&&onExport&&<section className="adaptive-export" aria-label="Download retained trip snapshot" aria-busy={exporting}>
        <p className="hint"><strong>{plan.completedDays===plan.totalDays?'Full itinerary.':'Partly planned itinerary.'}</strong> Includes every finished day, not just this page.{plan.completedDays<plan.totalDays&&' Unplanned days are not included.'}</p>
        <p className="hint">You can return to this temporary plan for 24 hours. Save the finished trip to keep it in your account.{Number.isFinite(Date.parse(plan.expiresAt))&&<> Download before <time dateTime={plan.expiresAt}>{new Date(plan.expiresAt).toLocaleString()}</time>.</>}</p>
        <button type="button" className="preview-btn" disabled={exporting} onClick={onExport}>{exporting?'Preparing download…':'Download itinerary PDF'}</button>
        {exportError&&<p role="alert" className="field-error">{exportError}</p>}
      </section>}
    </article>
    {shownSections.map(section=><CompletedSection key={section.id} section={section} currency={currency} tripStart={state.preferences?.startDate}/>)}
    {dayFeed&&<div className="adaptive-pages" aria-label="All planned trip days"><p className="hint">{shownDays} of {plan?.completedDays || 0} planned days loaded.{dayFeed.loading?' Loading the remaining days…':dayFeed.complete?' All planned days are shown below the progress summary.':''}</p>{dayFeed.error&&<><p role="status">{dayFeed.error}</p><button className="preview-btn" disabled={dayFeed.loading||state.reconnecting} onClick={dayFeed.retry}>Check remaining days</button></>}</div>}
    {!dayFeed&&onLoadPage&&(!!state.sections?.length||state.pageCursor>0||state.nextCursor!==null&&state.nextCursor!==undefined)&&<nav className="adaptive-pages" aria-label="Completed day pages"><span className="hint">{visibleDayRange(state.sections,state.preferences?.startDate)}</span>{state.pageCursor>0&&<button className="preview-btn" disabled={state.loading} onClick={()=>onLoadPage(0)}>Earlier days</button>}{state.nextCursor!==null&&state.nextCursor!==undefined&&<button className="preview-btn" disabled={state.loading} onClick={()=>onLoadPage(state.nextCursor)}>Next days</button>}</nav>}
  </section>;
}
