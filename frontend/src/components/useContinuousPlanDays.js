import {useEffect,useRef,useState} from 'react';
import {getSession,subscribeSession} from '../services/session.js';
import {readContinuousDays,continuousDaysMessage} from '../services/continuousTripDays.js';

const blank=()=>({sections:[],loadedDays:0,loading:false,error:'',complete:false});
const identity=page=>JSON.stringify([page?.plan?.id,page?.plan?.requestId,page?.plan?.completedDays,page?.plan?.spentCents,page?.preferences]);
export default function useContinuousPlanDays({state,client,enabled}) {
  const latest=useRef(state);latest.current=state;
  const binding=useRef(null),owner=getSession()?.user?.id || null;
  if(!state.plan)binding.current=null;
  else if(binding.current?.id!==state.plan.id)binding.current={id:state.plan.id,owner};
  const [output,setOutput]=useState(blank),[revision,setRevision]=useState(0),[sessionRevision,setSessionRevision]=useState(0);
  const key=state.plan&&state.preferences?identity(state):null;
  const unavailable=!enabled||!state.plan||state.existingPlan||state.plan.status==='expired'||!state.preferences||binding.current?.owner!==owner;
  useEffect(()=>subscribeSession(()=>{setOutput(blank());setSessionRevision(n=>n+1);}),[]);
  useEffect(()=>{
    const session=getSession(),source=latest.current,id=source.plan?.id;
    if(unavailable||!session?.user?.id){setOutput(blank());return;}
    if(source.needsCheck){setOutput(previous=>({...previous,loading:false}));return;}
    const controller=new AbortController();let disposed=false;
    const current=()=>!disposed&&!controller.signal.aborted&&getSession()===session;
    setOutput(previous=>({...((previous.planId===id&&previous.session===session)?previous:blank()),planId:id,session,loading:true,error:''}));
    const readPage=(cursor,{signal})=>{if(!current())throw new DOMException('Aborted','AbortError');return client.get(id,{afterSequence:cursor,signal});};
    void (async()=>{
      try{
        const firstPage=source.pageCursor===0?source:await readPage(0,{signal:controller.signal});
        await readContinuousDays({firstPage,readPage,identity,expectedDays:source.plan.completedDays,startDate:source.preferences.startDate,signal:controller.signal,onPage:value=>{
          if(!current())return;
          setOutput(previous=>{
            const keep=previous.planId===id&&previous.session===session&&previous.loadedDays>value.loadedDays&&value.sections.every((s,i)=>JSON.stringify(s)===JSON.stringify(previous.sections[i]));
            return{planId:id,session,sections:keep?previous.sections:value.sections,loadedDays:keep?previous.loadedDays:value.loadedDays,loading:!value.complete,complete:value.complete,error:''};
          });
        }});
      }catch(error){if(current())setOutput(previous=>({...previous,loading:false,complete:false,error:continuousDaysMessage(error)}));}
    })();
    return()=>{disposed=true;controller.abort();};
  },[key,unavailable,state.needsCheck,client,revision,sessionRevision]);
  const visible=output.planId===state.plan?.id&&output.session===getSession()?output:blank();
  return {...visible,retry:()=>setRevision(n=>n+1)};
}
