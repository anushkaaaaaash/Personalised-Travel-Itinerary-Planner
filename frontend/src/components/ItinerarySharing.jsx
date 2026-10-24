import { useState } from 'react';
import { Copy, Download, Printer } from 'lucide-react';
import { compactSummary, copySummary, downloadItinerary, downloadText, printSummary } from '../services/itineraryExport.js';
export default function ItinerarySharing({result,preferences,edited}) {
  const [message,setMessage]=useState(''),[preview,setPreview]=useState(false);
  const summary=compactSummary(result);
  function run(action){try{action();setMessage('Export prepared on this device. No account save was made.');}catch{setMessage('Export could not be prepared. Check the complete plan and file size.');}}
  async function copy(){setPreview(true);try{await copySummary(summary);setMessage('Summary copied. Review it before sharing.');}catch(e){setMessage(e.message);}}
  return <div className="itinerary-sharing"><div className="step-actions export-actions">
    <button className="preview-btn" onClick={copy}><Copy size={16} aria-hidden="true"/> Copy compact summary</button>
    <button className="preview-btn" onClick={()=>run(()=>downloadText(summary,'travel-summary.txt','text/plain'))}><Download size={16} aria-hidden="true"/> Download summary</button>
    <button className="preview-btn" onClick={()=>run(()=>downloadItinerary({...result,userEdited:edited,...(preferences?{preferences}:{})}))}><Download size={16} aria-hidden="true"/> Download itinerary JSON</button>
    <button className="preview-btn" onClick={()=>{printSummary(result);setMessage('Print requested for the compact summary. Choose your browser’s Save as PDF option if needed.');}}><Printer size={16} aria-hidden="true"/> Print / save PDF</button>
  </div><p className="hint">Compact summaries omit preference fields and private notes. Activity titles may still reveal personal choices: review before sharing. Full JSON includes activity notes and, when available, dietary and mobility preferences. Keep it private unless you intend to share those details. This is not a public sharing link.</p>
  {preview&&<label className="field">Summary to review and copy<textarea readOnly rows={12} value={summary}/></label>}{message&&<p role="status">{message}</p>}</div>;
}
