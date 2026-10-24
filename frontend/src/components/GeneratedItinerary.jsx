import RouteSummary from './RouteSummary.jsx';
import ItineraryEditor from './ItineraryEditor.jsx';
import RefinementControls from './RefinementControls.jsx';
import { COST_LABELS } from '../services/itineraries.js';
import ItinerarySharing from './ItinerarySharing.jsx';
export { downloadItinerary } from '../services/itineraryExport.js';
const money = (currency, value) => `${currency} ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
export default function GeneratedItinerary({ loading, error, result, onRetry, onCancel, onEditDay, edited = false, refinement = {}, onRefine, onCancelRefine, optimization = {}, onOptimize, onCancelOptimize, preferences, confirmedCoordinates = [], onConfirmCoordinate }) {
  if (loading) return <section className="card" aria-busy="true"><h2>Your AI day plan</h2><p role="status">Generating and validating your itinerary…</p><button className="preview-btn" onClick={onCancel}>Cancel generation</button></section>;
  if (error) return <section className="card results--error"><h2>Your AI day plan</h2><p role="alert">{error}</p><button className="preview-btn" onClick={onRetry}>Retry itinerary generation</button></section>;
  if (!result) return null;
  return <section className="results-wrap generated-itinerary" aria-label="AI-generated itinerary">
    <article className="card results-hero">
      <p className="eyebrow">Planning copy · not booked</p><h2>{result.destination}: {result.status === 'planned' ? 'your day-by-day plan' : 'preferences need revision'}</h2>
      <p className="hint">Unverified AI explanation — may contain claims inconsistent with the timeline:</p><p>{result.explanation}</p>{edited && <p role="status">Includes your unsaved local edits. Original AI costs have not been recalculated.</p>}<p className="hint">Provider: {result.provider} · Model: {result.model}. Estimates cover the whole group. Verify prices, opening hours, dietary suitability and accessibility directly.</p>
      <ul aria-label="Itinerary warnings">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      {result.status === 'infeasible' && <p>No day plan was accepted. Use Back to adjust your budget, dates or preferences, then generate again.</p>}
      {result.status === 'planned' && <ItinerarySharing result={result} preferences={preferences} edited={edited}/>}
      <p className="hint">Export stays on your device. Generation and export do not save to your account. Use My saved full itineraries for explicit storage and confirmed saved revisions.</p>
    </article>
    {result.refinementSummary && <article className="card"><h3>Computed refinement checks</h3><p>Scope: {result.refinementSummary.scope === 'day' ? `Only ${result.refinementSummary.targetDate}` : 'Whole itinerary'}. Maximum main activities per day: {result.refinementSummary.maxMainActivitiesPerDay ?? 'No new limit requested'}.</p><ul>{result.days.filter(d => !result.refinementSummary.targetDate || d.date === result.refinementSummary.targetDate).map(d => <li key={d.date}>{d.date}: {d.mainActivityCount} main activities</li>)}</ul><p className="hint">These checks cover structured counts and requested limits, not the truth of narrative claims, venue accessibility, schedules or availability. Counts come from the structured day plan, not the AI explanation. For a requested hard limit, main activities are counted from explicit activity kinds. Unknown kinds do not satisfy a hard limit; kinds are not inferred from titles.</p></article>}
    {onOptimize && result.status === 'planned' && <RouteSummary itinerary={result} confirmedCoordinates={confirmedCoordinates} onConfirmCoordinate={onConfirmCoordinate} onEditDay={onEditDay} state={optimization} onOptimize={onOptimize} onCancel={onCancelOptimize} disabled={refinement.loading || optimization.loading} />}
    {onRefine && <RefinementControls result={result} state={refinement} onRefine={onRefine} onCancel={onCancelRefine} />}
    {result.status === 'planned' && <>
      <article className="card budget-card"><h3>Estimated whole-trip budget</h3><div className="budget-total"><strong>{money(result.currency, result.estimatedTotalGroupCost)}</strong><span>{money(result.currency, result.remainingBudget)} remaining</span></div><p className="hint">Estimates are not quotes or guaranteed availability.</p></article>
      <div className="day-grid">{result.days.map((day, index) => <article className="card day-card" key={day.date}><header><span className="day-badge">Day {index + 1}</span><div><h3><time dateTime={day.date}>{day.date}</time></h3><p>{result.travelPace} pace · {day.mainActivityCount} main activities</p></div></header>
        <ul className="activity-list">{['morning', 'afternoon', 'evening', 'dining'].map(slot => <li key={slot}><strong className="slot-label">{slot}</strong><p>{day[slot]}</p></li>)}</ul>
        {day.activities?.length > 0 && <ol className="activity-list timeline" aria-label={`Activity timeline for ${day.date}`}>{day.activities.map(activity => <li key={activity.id}><div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} minutes</span><span className="tag">{activity.kind || 'unknown kind'}</span>{activity.fixedTime && <span className="tag">Fixed time</span>}</div><strong>{activity.title}</strong><p>{activity.notes}</p></li>)}</ol>}
        {onEditDay && <ItineraryEditor day={day} onChange={onEditDay} disabled={refinement.loading || optimization.loading} />}
        <div className="day-notes"><p><strong>Transit &amp; rest:</strong> {day.transitAndRest}</p><p><strong>Dietary notes:</strong> {day.dietaryNotes}</p><p><strong>Mobility notes:</strong> {day.mobilityNotes}</p></div>
        <h4>Estimated group costs</h4><ul className="budget-list">{Object.entries(COST_LABELS).map(([key, label]) => <li key={key}><span>{label}</span><span>{money(result.currency, day.costs[key])}</span></li>)}</ul>
      </article>)}</div>
    </>}
  </section>;
}
