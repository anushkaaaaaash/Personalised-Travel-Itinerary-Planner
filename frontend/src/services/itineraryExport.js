import { parseItineraryImport } from './itineraryImport.js';
import { validateTripPreferences } from '../../../shared/tripPreferences.mjs';
const pick=(value,keys)=>Object.fromEntries(keys.filter(k=>value?.[k]!==undefined).map(k=>[k,value[k]]));
const notice='AI-generated estimates, not bookings. Verify prices, hours and availability. Exporting does not save to your account.';
export function exportSnapshot(result,{preferences,userEdited=false}={}) {
  const body=pick(result,['status','destination','currency','travelStyle','travelPace','explanation','warnings','vibe','source','provider','model','saved','estimatedTotalGroupCost','remainingBudget']);
  body.days=result.days.map(day=>({...pick(day,['date','morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest','mainActivityCount','interestTags']),
    costs:pick(day.costs,['accommodation','meals','localTransport','activities','departureTravel']),
    activities:day.activities.map(a=>pick(a,['id','title','startTime','durationMinutes','notes','latitude','longitude','fixedTime','kind']))}));
  body.userEdited=Boolean(userEdited);body.notice=notice;
  if(preferences){const p=validateTripPreferences(preferences);if(!p.valid)throw new Error('Review preferences before exporting.');body.preferences=p.value;}
  // Enforce the same bounded portable contract as import, including all nested fields.
  const text=JSON.stringify(body,null,2);parseItineraryImport(text);return text;
}
export function compactSummary(result) {
  return [`${result.destination} — itinerary summary`,`${result.days[0]?.date} to ${result.days.at(-1)?.date}`,
    `Estimated group total: ${result.currency} ${result.estimatedTotalGroupCost}`,'Check current prices, opening hours and availability before booking.',
    'Private preference fields and activity/dietary/mobility notes are omitted. Review activity titles before sharing.',
    ...result.days.flatMap(day=>['',day.date,...(day.activities||[]).map(a=>`${a.startTime} (${a.durationMinutes} min) ${a.title}`)])].join('\n');
}
export function downloadText(text,filename,type,documentImpl=document,urlImpl=URL) {
  const url=urlImpl.createObjectURL(new Blob([text],{type}));let anchor;
  try{anchor=documentImpl.createElement('a');anchor.href=url;anchor.download=filename;documentImpl.body.appendChild(anchor);anchor.click();}
  finally{anchor?.remove();setTimeout(()=>urlImpl.revokeObjectURL(url),1000);}
}
export function downloadItinerary(result,documentImpl=document,urlImpl=URL) {
  downloadText(exportSnapshot(result,{preferences:result.preferences,userEdited:result.userEdited}),'travel-itinerary.json','application/json',documentImpl,urlImpl);
}
export async function copySummary(text,clipboard=globalThis.navigator?.clipboard) {
  if(!clipboard?.writeText)throw new Error('Clipboard unavailable. Select and copy the summary below.');
  try{await clipboard.writeText(text);}catch{throw new Error('Clipboard access was denied. Select and copy the summary below.');}
}
export const escapeHtml=text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function printDocument(result) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>Travel itinerary summary</title><style>body{font:16px system-ui;margin:2rem}pre{white-space:pre-wrap;line-height:1.6}</style></head><body><h1>Travel itinerary summary</h1><pre>${escapeHtml(compactSummary(result))}</pre></body></html>`;
}
export function printSummary(result,documentImpl=document) {
  return new Promise((resolve,reject)=>{
    let frame,loadTimer,cleanupTimer,settled=false,started=false,cleaned=false;
    const cleanup=()=>{clearTimeout(loadTimer);clearTimeout(cleanupTimer);cleaned=true;try{frame?.remove();}catch{/* Best-effort detached-frame cleanup. */}};
    const fail=()=>{if(settled)return;settled=true;cleanup();reject(new Error('Printing could not be started. Download the compact summary or try printing again.'));};
    try{
      frame=documentImpl.createElement('iframe');frame.title='Printable itinerary summary';frame.style.display='none';
      frame.srcdoc=printDocument(result);
      frame.onerror=fail;
      frame.onload=()=>{
        if(settled||started)return;started=true;clearTimeout(loadTimer);
        try{
          frame.contentWindow.addEventListener('afterprint',cleanup,{once:true});
          frame.contentWindow.focus();frame.contentWindow.print();
          settled=true;if(!cleaned)cleanupTimer=setTimeout(cleanup,60000);
          resolve({requested:true});
        }catch{fail();}
      };
      loadTimer=setTimeout(fail,10000);documentImpl.body.appendChild(frame);
    }catch{fail();}
  });
}
