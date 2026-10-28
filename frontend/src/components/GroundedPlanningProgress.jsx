import {tripDayLabel} from '../utils/dayLabels.js';
import { COST_LABELS } from '../services/itineraries.js';
import { validResearchDisplay, validDraftDisplay, researchTimestamp, researchSourceUrl } from '../services/groundedPlanning.js';

const researchMessages={
  queued:'Research is waiting to start.',
  cancelled:'Research has stopped. No further research is being requested for this plan.',
  submitting:'Sending the research request…',
  running:'Research is in progress. Your completed days remain available.',
  succeeded:'Research notes are available for this part of your trip.',
  submission_unknown:'We couldn’t confirm whether research started. Check its status before making another request.',
};
const researchFailures={
  RESEARCH_QUERY_INVALID:'Research could not start because a place field was not suitable for a public search. Review the destination and departure city; use place names rather than URLs or contact details.',
  RESEARCH_PROVIDER_REJECTED:'The research service did not accept this request. Your trip preferences have not been identified as a problem.',
  RESEARCH_DEADLINE_REACHED:'Research reached its processing time limit. A complete research result is not available.',
  RESEARCH_SOURCES_UNCONFIRMED:'The returned notes did not include enough usable source information. Travel details remain unconfirmed.',
  RESEARCH_SUBMISSION_UNCONFIRMED:'We couldn’t confirm whether research started. Check its status before making another request.',
  RESEARCH_POLL_UNCONFIRMED:'The latest research status could not be checked. This does not prove that research failed; check this same request.',
  RESEARCH_PROVIDER_FAILED:'The research service failed before completing its result. This is not evidence that your dates or budget are wrong.',
};
const money=(currency,value)=>`${currency} ${value.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;

export default function GroundedPlanningProgress({research,draft,currency,sectionStart,sectionEnd,tripStart,now=Date.now()}) {
  const researchValid=validResearchDisplay(research),draftValid=validDraftDisplay(draft,currency,sectionStart,sectionEnd);
  if(!research&&!draft)return null;
  const expired=researchValid&&researchTimestamp(research.expiresAt)&&Date.parse(research.expiresAt)<=now;
  return <section className="adaptive-planning" aria-label="Research and provisional trip days">
    {research&&<article className="card adaptive-section" aria-label="Research notes">
      <p className="eyebrow">Sources for your journey</p><h2>Research notes</h2>
      <p role="status">{!researchValid?'The research information could not be checked. No source notes are shown.':research.status==='failed'||research.status==='running'&&research.errorCode==='RESEARCH_POLL_UNCONFIRMED'?(Object.hasOwn(researchFailures,research.errorCode)?researchFailures[research.errorCode]:'A complete research result is not available. Your completed trip days remain unchanged.'):researchMessages[research.status]}</p>
      {researchValid&&<>
        <details className="secondary-tools"><summary>Research usage</summary><p className="hint">{research.toolCallsReserved} of {research.toolCallLimit} search/tool requests reserved in this run. Reservations are not completed searches.</p></details>
        {research.status==='succeeded'&&<>
          <details className="secondary-tools"><summary>Source timing</summary><p className="hint">Research received <time dateTime={research.receivedAt}>{new Date(research.receivedAt).toLocaleString()}</time>. This is when the planner received the notes—not when a publisher updated its information.</p>
          <p className="hint">Research freshness expires <time dateTime={research.expiresAt}>{new Date(research.expiresAt).toLocaleString()}</time>.{expired&&' This freshness window has expired; recheck these details before using them.'}</p></details>
          <p>These are source-informed observations and suggestions, not verified opening hours, prices, closures or journey times. Confirm important details with the venue or transport provider.</p>
          <details className="practical-checks"><summary>Read the research notes</summary><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{research.text}</p></details>
          <details className="practical-checks"><summary>Sources consulted ({research.sources.length})</summary><ul>{research.sources.map((source,index)=><li key={`${source.url}-${index}`} style={{overflowWrap:'anywhere'}}><a href={researchSourceUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title.trim() || new URL(source.url).hostname}</a></li>)}</ul></details>
        </>}
      </>}
    </article>}
    {draft&&<article className="card adaptive-section" style={{borderStyle:'dashed'}} aria-label="Provisional trip days">
      <p className="eyebrow">Draft — not yet accepted</p><h2>Days taking shape</h2>
      <p>These provisional days are still being checked and may change. They do not count as completed days and are not saved or ready to book.</p>
      {!draftValid?<p role="status">Complete draft days are not available to display safely yet. Your accepted days remain unchanged.</p>:<>
        <p className="hint">Draft dates · <time dateTime={sectionStart}>{sectionStart}</time> to <time dateTime={sectionEnd}>{sectionEnd}</time></p>
        {!draft.days.length&&<p>Complete draft days will appear here as they become available.</p>}
        {draft.days.map(day=><section className="adaptive-day" key={day.date} aria-label={`Provisional day ${day.date}`}>
          <h3>{tripDayLabel(day.date,tripStart)} · <time dateTime={day.date}>{day.date}</time> <span className="tag">Provisional</span></h3>
          <ol className="activity-list timeline">{day.activities.map(activity=><li key={activity.id}><div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} min</span><span>{activity.kind || 'Activity'}</span></div><strong>{activity.title}</strong><p>{activity.notes}</p></li>)}</ol>
          <div className="day-notes"><p><strong>Travel & rest</strong><br/>{day.transitAndRest}</p><p><strong>Dietary arrangements · confirm with venues</strong><br/>{day.dietaryNotes}</p><p><strong>Access · confirm with venues</strong><br/>{day.mobilityNotes}</p></div>
          <details className="practical-checks"><summary>Day outline & estimated group costs</summary><p><strong>Morning</strong> · {day.morning}</p><p><strong>Afternoon</strong> · {day.afternoon}</p><p><strong>Evening</strong> · {day.evening}</p><p><strong>Dining</strong> · {day.dining}</p><ul>{Object.entries(COST_LABELS).map(([key,label])=><li key={key}>{label}: {money(currency,day.costs[key])}</li>)}</ul><p className="hint">Estimates, not live quotes or bookings.</p></details>
        </section>)}
      </>}
    </article>}
  </section>;
}
