import { useEffect, useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { createAdaptiveExportController } from '../services/adaptiveExport.js';
export default function SavedTripPdfButton({tripID,disabled=false}) {
  const controller=useRef(null);
  const [state,setState]=useState({exporting:false,exportError:''});
  useEffect(()=>{const current=createAdaptiveExportController({resource:'saved-adaptive-trips',onStateChange:setState});controller.current=current;return()=>{current.dispose();controller.current=null;};},[tripID]);
  return <div className="itinerary-sharing" aria-busy={state.exporting}>
    <button type="button" className="preview-btn" disabled={disabled||state.exporting} onClick={()=>controller.current?.download(tripID)}><Download size={16} aria-hidden="true"/>{state.exporting?'Preparing PDF…':'Download itinerary PDF'}</button>
    <p className="hint">All saved days and expense details. Includes personal travel notes; review before sharing.</p>
    {state.exportError&&<p role="status">{state.exportError}</p>}
  </div>;
}
