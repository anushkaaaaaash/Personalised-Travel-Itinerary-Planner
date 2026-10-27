import DestinationLoading from './DestinationLoading.jsx';
import { tripFailureRecovery } from '../utils/travelMessages.js';

const adviceSteps = {budget:1,travelPace:1,destination:0,departureCity:0,mobilityConcerns:1,dietaryNeeds:1};
const money = (currency,value) => `${currency} ${(value/100).toLocaleString(undefined,{maximumFractionDigits:2})}`;
const terminal = status => ['completed','cancelled','expired'].includes(status);
const pauseCategory = plan => plan?.pauseReason==='SECTION_FAILED' ? ({SECTION_CONSTRAINT_CONFLICT:'CONSTRAINT_CONFLICT',SECTION_BUDGET_EXHAUSTED:'BUDGET_EXHAUSTED'}[plan.activeSection?.errorCode] || plan.pauseReason) : plan?.pauseReason;
const sectionFailures = {
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
    ADAPTIVE_UNAVAILABLE:['We couldn’t check the planning service.','The service could not be reached or is temporarily unavailable. Check this same trip before starting another planning request.'],
    ADAPTIVE_INVALID_RESPONSE:['The planning status couldn’t be verified.','The service returned an unusable checkpoint response. Check this same trip; no replacement request has been started.'],
    ADAPTIVE_NOT_FOUND:['This planning session couldn’t be found.','The service could not locate this planning session. Its outcome is not confirmed; check again before starting another request.'],
    ADAPTIVE_CONFLICT:['The planning state needs to be checked.','The service reported a conflicting planning state. Check this same trip before trying another change.'],
    ADAPTIVE_REJECTED:['This planning request was rejected.','The service did not accept this request, but did not identify a specific preference to change. Your entries are kept; no budget or date adjustment has been inferred.'],
  };
  const [title,message]=categories[code] || ['Let’s check where planning stopped.','The last request could not be confirmed. Check this same trip before starting another planning request. Your completed sections have not been replaced.'];
  return {code,title,message,retryable:false,editStep:null,recommendations:[]};
}

function CompletedSection({section,currency}) {
  const itinerary=section.checkpoint.itinerary;
  return <section className="card adaptive-section" aria-label={`Completed section ${section.sequence}`}>
    <header><p className="eyebrow">Completed section {section.sequence}</p><h3><time dateTime={section.startDate}>{section.startDate}</time> – <time dateTime={section.endDate}>{section.endDate}</time></h3>
      <p>{section.checkpoint.startLocation} → {section.checkpoint.endLocation}</p><p className="hint">Section estimate · {money(currency,section.checkpoint.spentCents)} for the whole group. Check prices and availability before booking.</p>
    </header>
    {itinerary.explanation && <p>{itinerary.explanation}</p>}
    {itinerary.warnings.length>0 && <details className="practical-checks"><summary>Things to check for this section</summary><ul>{itinerary.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></details>}
    {itinerary.days.map(day=><details className="adaptive-day" key={day.date}>
      <summary><time dateTime={day.date}>{day.date}</time> · {day.mainActivityCount} main activities</summary>
      <ol className="activity-list timeline">{day.activities.map(activity=><li key={activity.id}><div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} min</span>{activity.fixedTime&&<span className="tag">Fixed time</span>}</div><strong>{activity.title}</strong><p>{activity.notes}</p></li>)}</ol>
      <div className="day-notes"><p><strong>Getting around & taking a break</strong><br/>{day.transitAndRest}</p><p><strong>Dietary arrangements · confirm with venues</strong><br/>{day.dietaryNotes}</p><p><strong>Access · confirm with venues</strong><br/>{day.mobilityNotes}</p></div>
    </details>)}
  </section>;
}

export default function AdaptivePlanningStatus({state,destination,onCheck,onCancel,onContinue,onRetry,onLoadPage,onNewPlan,onEditPreferences,onExport,exporting=false,exportError=''}) {
  const plan=state.plan;
  const uncertain=state.needsCheck || plan?.activeSection?.status==='submission_unknown' || plan?.pauseReason==='SUBMISSION_UNKNOWN';
  const busy=state.loading || state.cancelling;
  const hasSession=Boolean(plan || state.resumable);
  const pauseReason=pauseCategory(plan);
  const requestRecovery=adaptiveRequestRecovery(state.errorCode);
  const needsBudgetEdit=!hasSession&&state.errorCode==='SECTION_MONEY_INVALID';
  const recovery=needsBudgetEdit?requestRecovery:adaptiveRecovery(plan);
  if(!plan && !uncertain && !state.error) return <DestinationLoading destination={state.preferences?.destination || destination} title={state.resumable?'Picking up your trip…':'Starting your trip plan…'} status={state.cancelling?'Stopping planning…':'Your full date range will be planned in small sections.'} onCancel={busy&&state.cancelling?undefined:onCancel} cancelLabel="Stop planning"/>;
  const allowancePause=plan?.status==='paused' && (pauseReason==='RESOURCE_ALLOWANCE_REACHED' || (pauseReason==='SECTION_FAILED'&&plan.remainingCreates===0));
  const sharedStoragePause=plan?.status==='paused' && plan.pauseReason==='STORAGE_LIMIT' && plan.storagePauseScope==='global';
  const canRetry=plan?.status==='paused' && plan.pauseReason==='SECTION_FAILED' && plan.remainingCreates>0 && plan.activeSection?.status==='failed' && !['SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED'].includes(plan.activeSection.errorCode);
  const canReview=needsBudgetEdit || plan?.status==='paused' && ['CONSTRAINT_CONFLICT','BUDGET_EXHAUSTED'].includes(pauseReason);
  const expired=plan?.status==='expired';
  const currency=state.preferences?.currency || 'USD';
  let title='Your trip is taking shape.', message='Planning the next section. Completed sections below are ready to review; the rest of the trip is not finished yet.';
  if(plan?.status==='completed'){title='Your full date range is planned.';message='All requested days have a completed plan. Browse the sections below and check current prices and availability before booking.';}
  else if(plan?.status==='cancelled'){title='Planning has stopped.';message='No further sections will be created for this plan. The completed sections below are retained as estimates, not verified bookings.';}
  else if(expired){title='This planning session has expired.';message='These checkpoints are no longer available here. Return to your trip details to decide what to do next.';}
  else if(uncertain || state.error){title=requestRecovery.title;message=requestRecovery.message;}
  else if(allowancePause){title='Ready for the next part?';message=`This batch has reached its planning-request allowance. Your full trip dates are kept. ${Number.isSafeInteger(plan.runAllowance)&&plan.runAllowance>=1&&plan.runAllowance<=12?`Continue only when you want to allow up to ${plan.runAllowance} more section requests.`:'Continue only when you want to allow another bounded batch of section requests.'}`;}
  else if(plan?.pauseReason==='STORAGE_LIMIT'){title=sharedStoragePause?'Planning storage is temporarily full.':'This plan has reached its storage allowance.';message=sharedStoragePause?'Shared planning storage is currently full. You can check capacity and resume this same session; if it is still full, no new section request will be started. Your existing request allowance and dates are unchanged.':'This plan has reached its temporary storage allowance. No further sections can be added in this session. Your dates and budget have not been changed.';}
  else if(plan?.status==='paused'){title=recovery.title;message=recovery.message;}
  return <section className="adaptive-planning" aria-label="Section-by-section trip planning">
    <article className="card adaptive-progress"><p className="eyebrow">{state.preferences?.destination || destination || 'Your trip'}</p><h2>{state.cancelling?'Stopping planning…':title}</h2>
      <p role="status">{message}</p>
      {state.preferences&&<p className="hint">Your full trip · <time dateTime={state.preferences.startDate}>{state.preferences.startDate}</time> to <time dateTime={state.preferences.endDate}>{state.preferences.endDate}</time></p>}
      {plan?.pauseReason==='STORAGE_LIMIT'&&Number.isFinite(Date.parse(plan.expiresAt))&&<p className="hint">Completed sections remain available until <time dateTime={plan.expiresAt}>{new Date(plan.expiresAt).toLocaleString()}</time>.</p>}
      {!expired&&Number.isSafeInteger(plan?.totalDays)&&plan.totalDays>0&&<div className="adaptive-progress__count"><strong>{plan.completedDays} of {plan.totalDays} days planned</strong><progress aria-label="Days with completed plans" max={plan.totalDays} value={plan.completedDays}/><p className="hint">Only completed sections count toward this total—not time spent waiting.</p></div>}
      {!expired&&Number.isSafeInteger(plan?.spentCents)&&<p className="hint">Completed-section estimates: {money(currency,plan.spentCents)} of your {money(currency,plan.totalBudgetCents)} total group budget.{plan.completedDays<plan.totalDays&&' Unplanned days still need a budget allocation.'}</p>}
      {canReview&&recovery.proposed&&<p className="hint">These are planning suggestions to review, not verified prices, availability or travel restrictions.</p>}
      {canReview&&recovery.recommendations.length>0&&<ul className="recovery-recommendations">{recovery.recommendations.map((item,index)=><li key={`${item.field}-${index}`}><strong>{item.suggestion}</strong>{item.reason&&<p>{item.reason}</p>}</li>)}</ul>}
      <div className="step-actions">
        {uncertain&&onCheck&&<button className="generate-btn" disabled={busy} onClick={onCheck}>Check planning status</button>}
        {!uncertain&&allowancePause&&onContinue&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onContinue}>Continue planning</button>}
        {!uncertain&&sharedStoragePause&&onContinue&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onContinue}>Check capacity and continue</button>}
        {!uncertain&&canRetry&&onRetry&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={onRetry}>Try this section again</button>}
        {!uncertain&&canReview&&onEditPreferences&&<button className="generate-btn" disabled={busy||state.cancelRequested} onClick={()=>onEditPreferences(recovery)}>{needsBudgetEdit?'Review budget format':'Stop planning and review changes'}</button>}
        {hasSession&&!terminal(plan?.status)&&onCancel&&<button className="preview-btn" disabled={state.cancelling||state.cancelRequested} onClick={onCancel}>Stop planning</button>}
        {(terminal(plan?.status)||!hasSession)&&onNewPlan&&<button className="preview-btn" disabled={busy} onClick={onNewPlan}>Back to trip details</button>}
      </div>
      {!expired&&plan?.completedDays>0&&onExport&&<section className="adaptive-export" aria-label="Download retained trip snapshot" aria-busy={exporting}>
        <p className="hint"><strong>{plan.completedDays===plan.totalDays?'Full-date snapshot.':'Partial snapshot.'}</strong> Download all retained completed sections, not just this page.{plan.completedDays<plan.totalDays&&' Unplanned days are not included.'} These are planning estimates, not bookings.</p>
        <p className="hint">This temporary plan is kept for 24 hours, not saved as an account itinerary.{Number.isFinite(Date.parse(plan.expiresAt))&&<> Download before <time dateTime={plan.expiresAt}>{new Date(plan.expiresAt).toLocaleString()}</time>.</>}</p>
        <button type="button" className="preview-btn" disabled={exporting} onClick={onExport}>{exporting?'Preparing download…':'Download retained plan (.txt)'}</button>
        {exportError&&<p role="alert" className="field-error">{exportError}</p>}
      </section>}
    </article>
    {(state.sections || []).slice(0,3).map(section=><CompletedSection key={section.id} section={section} currency={currency}/>)}
    {onLoadPage&&(!!state.sections?.length||state.pageCursor>0||state.nextCursor!==null&&state.nextCursor!==undefined)&&<nav className="adaptive-pages" aria-label="Completed section pages"><span className="hint">Showing {Math.min(state.sections?.length||0,3)} completed {state.sections?.length===1?'section':'sections'}.</span>{state.pageCursor>0&&<button className="preview-btn" disabled={state.loading} onClick={()=>onLoadPage(0)}>First sections</button>}{state.nextCursor!==null&&state.nextCursor!==undefined&&<button className="preview-btn" disabled={state.loading} onClick={()=>onLoadPage(state.nextCursor)}>Next completed sections</button>}</nav>}
  </section>;
}
