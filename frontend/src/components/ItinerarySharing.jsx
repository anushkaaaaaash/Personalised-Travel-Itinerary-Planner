import { useState } from 'react';
import { Copy, Download, Printer } from 'lucide-react';
import { compactSummary, copySummary, downloadItinerary, downloadText, printSummary } from '../services/itineraryExport.js';
export default function ItinerarySharing({result,preferences,edited}) {
  const [message,setMessage]=useState(''),[preview,setPreview]=useState(false),[printing,setPrinting]=useState(false);
  const summary=compactSummary(result);
  function run(action){try{action();setMessage('Your download is ready.');}catch{setMessage('Export could not be prepared. Check the complete plan and file size.');}}
  async function copy(){setPreview(true);try{await copySummary(summary);setMessage('Summary copied. Review it before sharing.');}catch(e){setMessage(e.message);}}
  async function print(){if(printing)return;setPrinting(true);setMessage('Preparing print summary.');try{await printSummary(result);setMessage('Choose Print or Save as PDF in your browser.');}catch{setMessage('Printing could not be started. Download the compact summary or try again.');}finally{setPrinting(false);}}
  return <div className="itinerary-sharing"><div className="step-actions export-actions">
    <button className="preview-btn" onClick={copy}><Copy size={16} aria-hidden="true"/> Copy summary</button>
    <button className="preview-btn" onClick={()=>run(()=>downloadText(summary,'travel-summary.txt','text/plain'))}><Download size={16} aria-hidden="true"/> Download summary</button>

    <button className="preview-btn" disabled={printing} onClick={print}><Printer size={16} aria-hidden="true"/> Print / save PDF</button>
  </div><p className="hint">Review your summary before sharing; it includes your activity choices.</p>
  {preview&&<label className="field">Summary to review and copy<textarea readOnly rows={12} value={summary}/></label>}{message&&<p role="status">{message}</p>}</div>;
}
