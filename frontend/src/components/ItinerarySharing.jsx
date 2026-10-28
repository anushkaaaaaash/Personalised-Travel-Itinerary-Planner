import { downloadSnapshotPdf } from '../services/snapshotPdf.js';
import { useState, useEffect, useRef } from 'react';
import { Copy, Download } from 'lucide-react';
import { compactSummary, copySummary } from '../services/itineraryExport.js';
export default function ItinerarySharing({result,preferences,edited}) {
  const [message,setMessage]=useState(''),[preview,setPreview]=useState(false),[printing,setPrinting]=useState(false);
  const summary=compactSummary(result);
  const active=useRef(null);
  useEffect(()=>{setPrinting(false);return()=>{active.current?.abort();active.current=null;};},[result]);
  async function pdf(){if(active.current)return;const controller=new AbortController();active.current=controller;setPrinting(true);setMessage('Preparing itinerary PDF…');try{await downloadSnapshotPdf(result,preferences,{signal:controller.signal});if(!controller.signal.aborted)setMessage('Your itinerary PDF is ready.');}catch{if(!controller.signal.aborted)setMessage('The PDF could not be prepared. Try again; your itinerary is unchanged.');}finally{if(active.current===controller)active.current=null;if(!controller.signal.aborted)setPrinting(false);}}
  async function copy(){setPreview(true);try{await copySummary(summary);setMessage('Summary copied. Review it before sharing.');}catch(e){setMessage(e.message);}}
  return <div className="itinerary-sharing"><div className="step-actions export-actions">
    <button className="preview-btn" onClick={copy}><Copy size={16} aria-hidden="true"/> Copy summary</button>
    <button type="button" className="preview-btn" disabled={printing} onClick={pdf}><Download size={16} aria-hidden="true"/> {printing?'Preparing PDF…':'Download itinerary PDF'}</button>


  </div><p className="hint">The PDF includes all daily details, expenses and personal travel notes. Review before sharing.</p>
  {preview&&<label className="field">Summary to review and copy<textarea readOnly rows={12} value={summary}/></label>}{message&&<p role="status">{message}</p>}</div>;
}
