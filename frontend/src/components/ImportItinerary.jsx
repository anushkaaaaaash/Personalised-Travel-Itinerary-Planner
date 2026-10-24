import { useEffect, useRef, useState } from 'react';
import { readItineraryFile } from '../services/itineraryImport.js';
export default function ImportItinerary({ onImport, disabled }) {
  const [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  async function choose(event) {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || disabled) return;
    const current = ++sequence.current; setLoading(true); setError('');
    try { const data = await readItineraryFile(file); if (current === sequence.current) onImport(data); }
    catch { if (current === sequence.current) setError('This file could not be imported safely. Choose a valid planner JSON export up to 128 KiB. Your current plan is unchanged.'); }
    finally { if (current === sequence.current) setLoading(false); }
  }
  return <section className="card"><h2>Restore an exported itinerary</h2><p className="hint">Import JSON from this planner on this device. No AI request or database save is made. Older exports may need missing trip preferences reviewed.</p><label className="field"><span>Import itinerary JSON (maximum 128 KiB)</span><input type="file" accept="application/json,.json" disabled={disabled || loading} onChange={choose} /></label>{loading && <p role="status">Checking local file…</p>}{error && <p role="alert">{error}</p>}</section>;
}
