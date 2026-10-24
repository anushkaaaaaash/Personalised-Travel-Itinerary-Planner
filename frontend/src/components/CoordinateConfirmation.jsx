export default function CoordinateConfirmation({ itinerary, confirmed = [], onConfirm, onEditDay, disabled }) {
  function matches(entry, day, activity) { return entry.date === day.date && entry.id === activity.id && entry.title === activity.title && entry.latitude === activity.latitude && entry.longitude === activity.longitude; }
  function change(day, index, key, raw) {
    const value = raw === '' ? null : Number(raw);
    onEditDay({ ...day, activities: day.activities.map((a, i) => i === index ? { ...a, [key]: value } : a) });
  }
  return <details className="coordinate-confirmation"><summary>Review and confirm stop coordinates before estimating a route</summary><p className="hint">AI coordinates can be wrong, even when numerically valid. Check each named place against a trusted map, correct its latitude/longitude, then explicitly confirm that stop. We do not geographically verify these coordinates. Generic or unknown locations should remain unconfirmed. Editing or regenerating clears confirmations.</p>
    {itinerary.days.map(day => <section key={day.date}><h4>{day.date}</h4>{day.activities.map((a, index) => {
      const usable = Number.isFinite(a.latitude) && Math.abs(a.latitude) <= 90 && Number.isFinite(a.longitude) && Math.abs(a.longitude) <= 180;
      return <fieldset className="editor-slot planner-fields" disabled={disabled} key={a.id}><legend>{a.title}</legend><div className="form-grid"><label className="field"><span>Latitude for {a.title}</span><input type="number" min={-90} max={90} step="any" value={a.latitude ?? ''} onChange={e => change(day, index, 'latitude', e.target.value)} /></label><label className="field"><span>Longitude for {a.title}</span><input type="number" min={-180} max={180} step="any" value={a.longitude ?? ''} onChange={e => change(day, index, 'longitude', e.target.value)} /></label></div><label><input type="checkbox" disabled={!usable || disabled} checked={confirmed.some(entry => matches(entry, day, a))} onChange={e => onConfirm({ date: day.date, id: a.id, title: a.title, latitude: a.latitude, longitude: a.longitude }, e.target.checked)} /> I checked this specific place on a trusted map and confirm these coordinates for planning estimates.</label></fieldset>;
    })}</section>)}
  </details>;
}
