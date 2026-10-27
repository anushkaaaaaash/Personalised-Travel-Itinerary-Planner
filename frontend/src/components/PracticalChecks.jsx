import { useEffect, useState } from 'react';
import { evidenceForActivity } from '../utils/travelEvidence.js';
const checks=[['opening_hours','Opening hours','Confirm with the venue'],['booking','Tickets & reservations','Check availability'],['route','Travel time','Allow a buffer between stops'],['closure','Current disruptions','Review local updates before leaving']];
export default function PracticalChecks({activity,date,destinationId,assessments,timeZone}) {
  const [now,setNow]=useState(Date.now);
  useEffect(()=>{ const expiries=(Array.isArray(assessments)?assessments:[]).map(item=>Date.parse(item?.expiresAt)).filter(time=>Number.isFinite(time)&&time>now); if(!expiries.length)return;const timer=setTimeout(()=>setNow(Date.now()),Math.min(2147483647,Math.max(1,Math.min(...expiries)-Date.now()+1)));return()=>clearTimeout(timer); },[assessments,now]);
  const evidence=evidenceForActivity(assessments,{destinationId,date,activityId:activity.id,timeZone,now});
  const blockers=evidence.filter(item=>item.blocker);
  return <div>{blockers.length>0 && <p className="travel-blocker" role="status">Check before visiting: {blockers.map(item=>item.summary).join(' ')}</p>}<details className="practical-checks"><summary>Before you go · {evidence.some(item=>item.status==='Checked')?'practical details':'details to check'}</summary><dl>
    {checks.map(([kind,label,fallback])=>{const item=evidence.find(entry=>entry.kind===kind);return <div className="practical-check-row" key={kind}><dt>{label}</dt><dd><span className={item?.status==='Checked'?'status-checked':'status-unknown'}>{item?.status || 'Not checked'}</span> · {item?.summary || fallback}{item?.source && <small className="evidence-source"><a href={item.source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Source ↗</a>{item.checkedAt && <> · Checked {new Date(item.checkedAt).toLocaleDateString()}</>}</small>}</dd></div>;})}
    {evidence.filter(item=>['weather','transit'].includes(item.kind)).map((item,index)=><div className="practical-check-row" key={index}><dt>{item.kind==='weather'?'Weather':'Transport'}</dt><dd>{item.status} · {item.summary}{item.source&&<small className="evidence-source"><a href={item.source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Source ↗</a>{item.checkedAt&&<> · Checked {new Date(item.checkedAt).toLocaleDateString()}</>}</small>}</dd></div>)}
  </dl></details></div>;
}
