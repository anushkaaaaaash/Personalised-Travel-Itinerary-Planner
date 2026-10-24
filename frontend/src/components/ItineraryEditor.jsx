import { useState } from 'react';
import { editActivity } from '../utils/itineraryEdits.js';
/** Explicit local edits only, retaining the backend's canonical day schema. */
export default function ItineraryEditor({ day, onChange, disabled = false }) {
  const [open, setOpen] = useState(false);
  function updateActivity(index, key, value) {
    onChange(editActivity(day, index, key, value));
  }
  return <div className="itinerary-editor"><button type="button" className="preview-btn" disabled={disabled} onClick={() => setOpen(v => !v)}>{open ? 'Close day editor' : `Edit activities, timings & notes for ${day.date}`}</button>
    {open && <fieldset disabled={disabled} className="planner-fields"><legend>Local edits for {day.date}</legend><p className="hint">Changes are local and unsaved. Editing activities does not recalculate prices or verify travel time. Changing an activity name clears its coordinates until regenerated. Select kinds explicitly; once all are known, the main count is recalculated. A count outside the selected pace must be reviewed, not silently adjusted.</p>
      {day.activities?.length ? day.activities.map((activity, index) => <div className="editor-slot" key={activity.id}>
        <label className="field"><span>Activity {index + 1}</span><input maxLength={160} value={activity.title} onChange={e => updateActivity(index, 'title', e.target.value)} /></label>
        <label className="field"><span>Activity kind</span><select value={activity.kind || 'unknown'} onChange={e => updateActivity(index, 'kind', e.target.value)}>{['unknown', 'main', 'rest', 'transfer', 'meal', 'accommodation'].map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></label><label className="field"><span>Start time</span><input type="time" required value={activity.startTime} onChange={e => updateActivity(index, 'startTime', e.target.value)} /></label>
        <label className="field"><span>Duration (minutes)</span><input type="number" min={15} max={240} value={activity.durationMinutes} onChange={e => updateActivity(index, 'durationMinutes', Number(e.target.value))} /></label>
        <label className="field"><span>Notes</span><textarea maxLength={500} value={activity.notes} onChange={e => updateActivity(index, 'notes', e.target.value)} /></label>
        <label><input type="checkbox" checked={activity.fixedTime} onChange={e => updateActivity(index, 'fixedTime', e.target.checked)} /> Keep this start time fixed during optimization</label>
      </div>) : <p className="hint">No structured activity timeline was provided. Regenerate to request one; times will not be invented.</p>}
      {['morning', 'afternoon', 'evening', 'dining'].map(slot => <label className="field editor-slot" key={slot}><span>{slot} summary</span><textarea maxLength={700} value={day[slot]} onChange={e => onChange({ ...day, [slot]: e.target.value })} /></label>)}
    </fieldset>}
  </div>;
}
