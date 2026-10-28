import {useEffect,useRef,useState} from 'react';

export function planningTimeEstimate(totalDays) {
  if(!Number.isSafeInteger(totalDays)||totalDays<1)return null;
  if(totalDays>30)return 'Longer trips may need several planning runs. Timing varies with research and retries.';
  const parts=Math.ceil(totalDays/3);
  return `Rough whole-trip estimate: ${parts*3}–${parts*5} minutes, based on limited recent timing observations. This is not a countdown or a guarantee; research and retries may take longer.`;
}
export function elapsedVisitLabel(milliseconds) {
  const minutes=Math.max(0,Math.floor(milliseconds/60000));
  return minutes<1?'Less than a minute on this visit':`${minutes} ${minutes===1?'minute':'minutes'} on this visit`;
}
export default function PlanningWaitGuidance({planId,totalDays,expiresAt,active=true}) {
  const [elapsed,setElapsed]=useState(0);
  const started=useRef(Date.now());
  useEffect(()=>{started.current=Date.now();setElapsed(0);},[planId]);
  useEffect(()=>{
    if(!active)return;
    setElapsed(Math.max(0,Date.now()-started.current));
    const timer=setInterval(()=>setElapsed(Math.max(0,Date.now()-started.current)),15000);
    return()=>clearInterval(timer);
  },[planId,active]);
  if(!active)return null;
  const estimate=planningTimeEstimate(totalDays);
  const expiry=typeof expiresAt==='string'?Date.parse(expiresAt):NaN;
  return <aside className="secondary-tools" aria-label="Planning time and returning later">
    {estimate&&<p className="hint">{estimate}</p>}
    <p className="hint">{elapsedVisitLabel(elapsed)}. Your completed-day count shows progress, not time remaining.</p>
    {typeof planId==='string'&&planId&&Number.isFinite(expiry)&&expiry>Date.now()&&<p className="hint">You can leave this page and return from this account before <time dateTime={expiresAt}>{new Date(expiresAt).toLocaleString()}</time>. Planning may pause for your approval. This temporary plan is not an account-saved trip.</p>}
  </aside>;
}
