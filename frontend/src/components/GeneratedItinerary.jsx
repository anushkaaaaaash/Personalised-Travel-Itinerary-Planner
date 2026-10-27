import { travelError } from '../utils/travelMessages.js';
import DestinationLoading from './DestinationLoading.jsx';
import PracticalChecks from './PracticalChecks.jsx';
import ItineraryEditor from './ItineraryEditor.jsx';
import RefinementControls from './RefinementControls.jsx';
import { COST_LABELS } from '../services/itineraries.js';
import ItinerarySharing from './ItinerarySharing.jsx';
export { downloadItinerary } from '../services/itineraryExport.js';
const money = (currency, value) => `${currency} ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const dayLabel = value => new Intl.DateTimeFormat(undefined, { weekday:'long', month:'short', day:'numeric', timeZone:'UTC' }).format(new Date(`${value}T12:00:00Z`));
export default function GeneratedItinerary({ loading, error, result, evidence, onRetry, onEditPreferences, onCancel, onEditDay, edited = false, refinement = {}, onRefine, onCancelRefine, optimization = {}, onOptimize, onCancelOptimize, preferences, confirmedCoordinates = [], onConfirmCoordinate }) {
  if (loading) return <DestinationLoading destination={preferences?.destination} onCancel={onCancel} />;
  if (error) {
    const dateRangeError = /1[–-]14 days/.test(error);
    return <section className="card results--error"><p className="eyebrow">Your trip preferences are kept</p>
      <h2>{dateRangeError ? 'Let’s check your dates.' : 'We couldn’t build this trip.'}</h2>
      <p role="alert">{dateRangeError ? 'Plan 1–14 days at a time. Edit your trip dates to continue.' : travelError(error, 'We couldn’t finish this plan. You can try again or edit your trip details.')}</p>
      <div className="step-actions">
        {!dateRangeError && onRetry && <button className="generate-btn" onClick={onRetry}>Try again</button>}
        {onEditPreferences && <button className={dateRangeError ? 'generate-btn' : 'preview-btn'} onClick={onEditPreferences}>Edit trip details</button>}
      </div>
    </section>;
  }
  if (!result) return null;
  return <section className="results-wrap generated-itinerary" aria-label="Your itinerary">
    <article className="card results-hero">
      <p className="eyebrow">Your next chapter</p><h2>{result.destination}.<br />{result.status === 'planned' ? 'Make the days your own.' : 'Let’s find a better fit.'}</h2>
      <p>{result.explanation}</p>
      <div className="trip-summary"><span>{result.days.length} {result.days.length === 1 ? 'day' : 'days'} to explore</span><span>{result.travelPace} pace</span>{preferences?.travelers && <span>{preferences.travelers} {Number(preferences.travelers) === 1 ? 'traveler' : 'travelers'}</span>}</div>
      {result.warnings.length > 0 && <details className="practical-checks"><summary>Things to keep in mind ({result.warnings.length})</summary><ul aria-label="Itinerary warnings">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
      {result.status === 'infeasible' && <p>Try adjusting your budget, dates or pace in trip preferences.</p>}
      {result.status === 'planned' && <ItinerarySharing result={result} preferences={preferences} edited={edited}/>}
    </article>
    {result.status === 'planned' && <>
      <article className="card budget-card"><p className="eyebrow">The big picture</p><h3>Your estimated budget</h3><div className="budget-total"><strong>{money(result.currency, result.estimatedTotalGroupCost)}</strong><span>{money(result.currency, result.remainingBudget)} remaining</span></div><p className="hint">Whole group, whole trip. Check current prices before booking.</p></article>
      <div className="day-grid">{result.days.map((day, index) => <article className="card day-card" key={day.date}><header><span className="day-badge">{String(index + 1).padStart(2,'0')}</span><div><p className="eyebrow">Day {index + 1}</p><h3><time dateTime={day.date}>{dayLabel(day.date)}</time></h3><p>{day.mainActivityCount} main activities · space for the in-between</p></div></header>
        {day.activities?.length > 0 ? <ol className="activity-list timeline" aria-label={`Activity timeline for ${day.date}`}>{day.activities.map(activity => <li key={activity.id}><div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} min</span>{activity.fixedTime && <span className="tag">Fixed time</span>}</div><strong>{activity.title}</strong><p>{activity.notes}</p><PracticalChecks activity={activity} date={day.date} destinationId={evidence?.destinationId} assessments={evidence?.assessments} timeZone={evidence?.timeZone}/></li>)}</ol> : <ul className="activity-list">{['morning', 'afternoon', 'evening', 'dining'].map(slot => <li key={slot}><strong className="slot-label">{slot}</strong><p>{day[slot]}</p></li>)}</ul>}
        <div className="day-notes"><p><strong>Getting around & taking a break</strong><br />{day.transitAndRest}</p><p><strong>At the table · confirm dietary needs with venues</strong><br />{day.dietaryNotes}</p><p><strong>Access · confirm arrangements with venues</strong><br />{day.mobilityNotes}</p></div>
        <details className="secondary-tools"><summary>Day budget breakdown</summary><ul className="budget-list">{Object.entries(COST_LABELS).map(([key, label]) => <li key={key}><span>{label}</span><span>{money(result.currency, day.costs[key])}</span></li>)}</ul></details>
        {onEditDay && <details className="secondary-tools"><summary>Adjust this day</summary><ItineraryEditor day={day} onChange={onEditDay} disabled={refinement.loading || optimization.loading} /></details>}
      </article>)}</div>
    </>}
    {onRefine && <details className="secondary-tools"><summary>Make it more you</summary><RefinementControls result={result} state={refinement} onRefine={onRefine} onCancel={onCancelRefine} /></details>}

  </section>;
}
