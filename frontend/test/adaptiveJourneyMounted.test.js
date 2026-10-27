import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {preferences} from './shareFixture.js';
const id='11111111-1111-4111-8111-111111111111',requestId='22222222-2222-4222-8222-222222222222';
const prefs={...preferences,startDate:'2028-01-01',endDate:'2028-12-31'};
const page=(status='paused',patch={})=>({plan:{id,requestId,status,totalDays:366,completedDays:9,remainingCreates:0,spentCents:10000,totalBudgetCents:250000,pauseReason:'RESOURCE_ALLOWANCE_REACHED',activeSection:null,...patch},preferences:prefs,sections:[],nextCursor:null});
async function harness(run){
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  const {setSession}=await server.ssrLoadModule('/src/services/session.js');
  try{
    const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
    setSession({user:{id:'test-owner'},access_token:'TEST_ONLY_TOKEN',expires_at:Date.now()/1000+3600});
    const env={mount:async(client,enabled=true)=>act(async()=>{renderer=create(React.createElement(Page,{signedIn:true,adaptiveEnabled:enabled,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12},adaptiveClient:client,adaptiveStorage:storage,adaptivePollMs:10000}));}),text:()=>JSON.stringify(renderer.toJSON()),form:()=>renderer.root.findByType(Form).props,status:()=>renderer.root.findByType(Status).props,prepare:async()=>{await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])env.form().onChange({target:{name,value:prefs[name]}});});await act(async()=>env.form().onSubmit({preventDefault(){}}));await act(async()=>env.form().onSubmit({preventDefault(){}}));}};
    await run(env);
  }finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);await server.close();}
}
test('adaptive capability permits long dates and starts one durable plan; legacy remains gated',()=>harness(async env=>{
  let calls=0;await env.mount({start:async p=>{calls++;assert.equal(p.endDate,prefs.endDate);return page();}});await env.prepare();assert.equal(env.form().step,2);
  await act(async()=>{const handler=env.form().onGenerateItinerary;handler();handler();});assert.equal(calls,1);assert.equal(env.status().state.plan.totalDays,366);assert.match(env.text(),/Kyoto/);
}));
test('without advertised capability long dates stay in legacy validation and no adaptive request',()=>harness(async env=>{
  await env.mount({start:async()=>assert.fail('not enabled')},false);await env.prepare();assert.equal(env.form().step,0);assert.match(env.form().errors.endDate,/14/);
}));
test('review recommendations waits for confirmed cancellation and preserves original preferences',()=>harness(async env=>{
  let resolve;const stopped=new Promise(r=>resolve=r);
  await env.mount({start:async()=>page('paused',{pauseReason:'CONSTRAINT_CONFLICT',remainingCreates:2,activeSection:{id,status:'failed',errorCode:'SECTION_CONSTRAINT_CONFLICT'}}),cancel:()=>stopped});await env.prepare();await act(async()=>env.form().onGenerateItinerary());
  const advice={code:'SECTION_CONSTRAINT_CONFLICT',title:'Review your trip',message:'Proposed changes',retryable:false,editStep:1,proposed:true,recommendations:[{field:'budget',suggestion:'Review travel budget.'}]};
  await act(async()=>env.status().onEditPreferences(advice));assert.equal(env.status().state.cancelling,true);
  await act(async()=>resolve(page('cancelled')));assert.equal(env.form().step,1);assert.equal(env.form().form.endDate,prefs.endDate);assert.equal(env.form().form.budget,prefs.budget);assert.equal(env.form().recovery,advice);await act(async()=>env.form().onChange({target:{name:'travelers',value:2}}));assert.equal(env.form().recovery,advice);
}));
test('unconfirmed stop does not navigate to editable preferences or start replacement work',()=>harness(async env=>{
  let starts=0;await env.mount({start:async()=>{starts++;return page();},cancel:async()=>{throw Error('network');}});await env.prepare();await act(async()=>env.form().onGenerateItinerary());
  await act(async()=>env.status().onEditPreferences({editStep:1,recommendations:[]}));assert.equal(env.status().state.needsCheck,true);assert.equal(starts,1);
}));
