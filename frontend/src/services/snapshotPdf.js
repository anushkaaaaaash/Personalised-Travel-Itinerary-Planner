import { getSession, sessionFetch, subscribeSession } from './session.js';
import { downloadText } from './itineraryExport.js';
/** Read-only rendering of the visible validated snapshot; no AI calls or account save. */
export async function downloadSnapshotPdf(result,preferences,{signal,fetchImpl=sessionFetch,save=downloadText,timeoutMs=60000}={}) {
  const identity=getSession(),controller=new AbortController(),abort=()=>controller.abort();
  const unsubscribe=subscribeSession(next=>{if(next!==identity)abort();});
  const timer=setTimeout(abort,timeoutMs);signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();
  const current=()=>!controller.signal.aborted&&getSession()===identity;
  let reader;
  try {
    const keys=['status','destination','currency','travelStyle','travelPace','explanation','warnings','vibe','days'];
    const itinerary=Object.fromEntries(keys.filter(k=>result[k]!==undefined).map(k=>[k,result[k]]));
    const response=await fetchImpl(`${(import.meta.env?.VITE_API_BASE_URL||'/api').replace(/\/$/,'')}/itineraries/export-pdf`,{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/pdf'},body:JSON.stringify({itinerary,preferences}),signal:controller.signal});
    if(!current())throw Error('Download canceled.');
    if(response.status!==200||response.headers.get('content-type')?.split(';')[0]!=='application/pdf'||!response.body?.getReader)throw Error('The PDF could not be prepared. Check the complete plan and try again.');
    const limit=24*1024*1024,length=response.headers.get('content-length');
    if(length&&(!/^\d+$/.test(length)||Number(length)>limit))throw Error('PDF exceeds the download limit.');
    reader=response.body.getReader();const chunks=[];let size=0;
    const cancelReader=()=>{void reader.cancel().catch(()=>{});};
    controller.signal.addEventListener('abort',cancelReader,{once:true});
    while(true){const {done,value}=await reader.read();if(!current())throw Error('Download canceled.');if(done)break;size+=value.byteLength;if(size>limit)throw Error('PDF exceeds the download limit.');chunks.push(value);}
    if(length&&size!==Number(length))throw Error('The PDF was incomplete.');
    const blob=new Blob(chunks,{type:'application/pdf'});
    if(await blob.slice(0,5).text()!=='%PDF-'||await blob.slice(-6).text()!=='%%EOF\n')throw Error('The PDF was incomplete. No file was saved.');
    if(!current())throw Error('Download canceled.');
    save(blob,'personalised-travel-itinerary.pdf','application/pdf');
  } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);unsubscribe();try{await reader?.cancel();}catch{}controller.abort();}
}
