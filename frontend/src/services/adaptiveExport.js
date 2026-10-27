import { getSession, sessionFetch, subscribeSession } from './session.js';
import { adaptiveId } from './adaptivePlanning.js';
export const MAX_ADAPTIVE_EXPORT_BYTES=24*1024*1024;
export const ADAPTIVE_EXPORT_SENTINEL='\nEND OF ROAMORA EXPORT\n';
export class AdaptiveExportError extends Error {
  constructor(code,message){super(message);this.code=code;}
}
function saveBlob(blob,filename){
  const url=URL.createObjectURL(blob),anchor=document.createElement('a');
  try{anchor.href=url;anchor.download=filename;document.body.append(anchor);anchor.click();}
  finally{anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),0);}
}
/** Read-only private export. Never save a truncated, oversized or foreign-session stream. */
export function createAdaptiveExportController({fetchImpl=sessionFetch,getIdentity=getSession,subscribe=subscribeSession,save=saveBlob,onStateChange=()=>{},baseUrl=(import.meta.env?.VITE_API_BASE_URL || '/api'),timeoutMs=60000}={}){
  let active=null,disposed=false;
  const publish=value=>{if(!disposed)onStateChange(value);};
  const abort=()=>{if(active){active.controller.abort();void active.reader?.cancel().catch(()=>{});}active=null;publish({exporting:false,exportError:''});};
  const unsubscribe=subscribe(()=>{if(active&&(getIdentity()!==active.identity||getIdentity()?.user?.id!==active.ownerId))abort();});
  return {
    async download(id){
      if(disposed||active)return{ignored:true};
      const identity=getIdentity();
      if(!identity?.user?.id){publish({exporting:false,exportError:'Sign in again to download your retained plan.'});return{error:true};}
      if(!adaptiveId(id)){publish({exporting:false,exportError:'This plan could not be selected for download.'});return{error:true};}
      const op={identity,ownerId:identity.user.id,controller:new AbortController(),reader:null};active=op;
      const current=()=>!disposed&&active===op&&getIdentity()===identity&&getIdentity()?.user?.id===op.ownerId&&!op.controller.signal.aborted;
      const timer=setTimeout(()=>{op.controller.abort();void op.reader?.cancel().catch(()=>{});if(active===op)publish({exporting:false,exportError:'The download timed out. No file was saved; try downloading again.'});},timeoutMs);
      publish({exporting:true,exportError:''});
      try{
        const response=await fetchImpl(`${baseUrl.replace(/\/$/,'')}/adaptive-plans/${id}/export`,{method:'GET',headers:{Accept:'text/plain'},signal:op.controller.signal});
        if(!current())return{ignored:true};
        if(response.status!==200)throw new AdaptiveExportError('EXPORT_UNAVAILABLE',response.status===401?'Sign in again to download your retained plan.':'The retained plan could not be downloaded. Check its status and try again.');
        const length=response.headers?.get('content-length');
        if(length && (!/^\d+$/.test(length)||Number(length)>MAX_ADAPTIVE_EXPORT_BYTES))throw new AdaptiveExportError('EXPORT_TOO_LARGE','This export exceeds the download size limit. No file was saved.');
        if(response.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='text/plain'||!response.body?.getReader)throw new AdaptiveExportError('EXPORT_INVALID','This export could not be verified. No file was saved.');
        op.reader=response.body.getReader();
        const chunks=[],decoder=new TextDecoder('utf-8',{fatal:true}),sentinelBytes=new TextEncoder().encode(ADAPTIVE_EXPORT_SENTINEL);
        let size=0,tail=new Uint8Array();
        while(true){
          const {done,value}=await op.reader.read();
          if(!current())return{ignored:true};
          if(done)break;
          if(!(value instanceof Uint8Array))throw Error('invalid stream');
          size+=value.byteLength;
          if(size>MAX_ADAPTIVE_EXPORT_BYTES)throw new AdaptiveExportError('EXPORT_TOO_LARGE','This export exceeds the download size limit. No file was saved.');
          decoder.decode(value,{stream:true});
          chunks.push(value);
          const joined=new Uint8Array(Math.min(tail.length+value.length,sentinelBytes.length));
          if(value.length>=joined.length)joined.set(value.subarray(value.length-joined.length));
          else{joined.set(tail.subarray(tail.length-(joined.length-value.length)));joined.set(value,joined.length-value.length);}
          tail=joined;
        }
        decoder.decode();
        if(tail.length!==sentinelBytes.length||tail.some((byte,index)=>byte!==sentinelBytes[index]))throw new AdaptiveExportError('EXPORT_INCOMPLETE','The download was interrupted or incomplete. No file was saved; try downloading again.');
        if(!current())return{ignored:true};
        save(new Blob(chunks,{type:'text/plain;charset=utf-8'}),`roamora-retained-plan-${id}.txt`);
        publish({exporting:false,exportError:''});return{downloaded:true,bytes:size};
      }catch(error){
        if(!current()){if(active===op&&!disposed)publish({exporting:false,exportError:'The download was interrupted. No file was saved; try downloading again.'});return{ignored:true};}
        publish({exporting:false,exportError:error instanceof AdaptiveExportError?error.message:'The download could not be verified. No file was saved; try downloading again.'});return{error:true};
      }finally{clearTimeout(timer);op.controller.abort();if(op.reader){try{await op.reader.cancel();}catch{}}if(active===op)active=null;}
    },
    cancel:abort,
    dispose(){disposed=true;abort();unsubscribe?.();},
  };
}
