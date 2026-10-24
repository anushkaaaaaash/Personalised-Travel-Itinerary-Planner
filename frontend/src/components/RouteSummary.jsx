import CoordinateConfirmation from './CoordinateConfirmation.jsx';
export default function RouteSummary({ state = {}, onOptimize, onCancel, disabled, itinerary, confirmedCoordinates = [], onConfirmCoordinate, onEditDay }) {
  const result = state.result?.routeSummary;
  return <section className="card route-summary"><h3>Route &amp; travel-time estimates</h3><p className="hint">Optimize the order of activities using only explicitly user-confirmed stop coordinates. Unconfirmed AI coordinates are not used. This is a schematic estimate, not a map, live directions or verified journey time.</p>
    {itinerary && onConfirmCoordinate && <CoordinateConfirmation itinerary={itinerary} confirmed={confirmedCoordinates} onConfirm={onConfirmCoordinate} onEditDay={onEditDay} disabled={disabled || state.loading} />}
    <button className="preview-btn" disabled={disabled || state.loading} onClick={onOptimize}>{state.loading ? 'Optimizing route…' : 'Optimize route and timing (does not save)'}</button>{state.loading && <button className="preview-btn" onClick={onCancel}>Cancel optimization</button>}
    {state.error && <p role="alert">{state.error}</p>}
    {result && <><p>{result.basis}</p><ul>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>{result.days.map(day => <article key={day.date} className="route-day"><h4>{day.date}: {day.status}</h4>
      <ol className="route-stops" aria-label={`Estimated route for ${day.date}`}>{day.orderedStops.map((stop, i) => <li key={stop.id}><span className="day-badge">{i + 1}</span><strong>{stop.title}</strong><span>{stop.startTime} · {stop.durationMinutes} min</span></li>)}</ol>
      <p>Estimated straight-line distance: {day.beforeDistanceKm === null ? 'Unavailable' : `${day.beforeDistanceKm.toFixed(2)} km`} before → {day.afterDistanceKm === null ? 'Unavailable' : `${day.afterDistanceKm.toFixed(2)} km`} after</p>
      {day.legs.length > 0 && <ul>{day.legs.map((leg, i) => <li key={i}>{day.orderedStops.find(s => s.id === leg.fromId)?.title || leg.fromId} → {day.orderedStops.find(s => s.id === leg.toId)?.title || leg.toId}: {leg.distanceKm === null ? 'Distance unknown' : `${leg.distanceKm.toFixed(2)} km`}, {leg.estimatedMinutes === null ? 'time unknown' : `~${Math.round(leg.estimatedMinutes)} minutes`}</li>)}</ul>}
      {day.timingChanges.length > 0 && <ul aria-label="Timing changes">{day.timingChanges.map(c => <li key={c.id}>{day.orderedStops.find(s => s.id === c.id)?.title || c.id}: {c.from} → {c.to}</li>)}</ul>}
      <ul>{day.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
    </article>)}</>}
  </section>;
}
