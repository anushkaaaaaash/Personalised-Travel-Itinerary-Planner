export default function TripHistory({ history, detail, onLoad, onSelect, onPrefill, onClose, onCancel, onCancelHistory, saving = false, ownershipEnabled = false }) {
  return <section className="card trip-history" aria-label="Saved trip preferences">
    <h2>Saved trip history</h2><p className="hint">{ownershipEnabled ? 'These are saved preferences for your signed-in account.' : "Private local prototype: these are this project's saved preferences, not an authenticated personal account."} Generated itineraries are not stored here.</p>
    <button className="preview-btn" onClick={() => onLoad(0)} disabled={history.loading || saving}>{history.loading ? 'Reading saved trips…' : history.result ? 'Refresh saved trips' : 'Load saved trips'}</button>
    {history.loading && <div><p role="status">Reading history…</p><button className="preview-btn" onClick={onCancelHistory}>Cancel history request</button></div>}
    {history.error && <p role="alert">{history.error}</p>}
    {history.result && <>
      {history.result.trips.length === 0 ? <p>No saved trips on this page.</p> : <ul className="history-list">{history.result.trips.map(t => <li key={t.id}><div><strong>{t.destination}</strong><p>{t.startDate} – {t.endDate} · {t.travelers} travelers</p><small>Trip ID: {t.id}{t.preferencesStatus === 'unavailable' ? ' · Legacy preferences cannot be restored' : ''}</small></div><button className="back-btn" disabled={saving || detail.loading} onClick={() => onSelect(t.id)}>View preferences</button></li>)}</ul>}
      <div className="step-actions"><button className="back-btn" onClick={() => onLoad(Math.max(0, history.result.offset - 20))} disabled={saving || history.loading || history.result.offset === 0}>Previous trips</button><button className="back-btn" onClick={() => onLoad(history.result.offset + 20)} disabled={saving || history.loading || !history.result.hasMore || history.result.offset >= 10000}>Next trips</button></div>
    </>}
    {detail.loading && <div><p role="status">Reading saved preferences…</p><button className="preview-btn" onClick={onCancel}>Cancel reading</button></div>}
    {detail.error && <p role="alert">{detail.error} Select View preferences to retry.</p>}
    {detail.result && <section className="history-detail" aria-label="Saved trip details"><h3>{detail.result.destination}</h3><p>Confirmed saved trip ID: {detail.result.id}</p>
      {detail.result.preferences ? <><dl className="history-preferences">{Object.entries(detail.result.preferences).map(([key, value]) => <div key={key}><dt>{({ departureCity: 'Departure city', startDate: 'Start date', endDate: 'End date', dietaryNeeds: 'Dietary needs', travelPace: 'Travel pace', travelStyle: 'Travel style', mobilityConcerns: 'Mobility preferences' })[key] || key}</dt><dd>{Array.isArray(value) ? value.join(', ') || 'None' : String(value || 'Not specified')}</dd></div>)}</dl><button className="preview-btn" disabled={saving} onClick={() => onPrefill(detail.result)}>Use these preferences in planner</button><p className="hint">Replaces the current form and clears generated results. It does not save or call AI.</p></> : <p>This older record does not contain valid complete preferences. No missing values will be guessed.</p>}
      <button className="preview-btn" onClick={onClose}>Close details</button>
    </section>}
  </section>;
}
