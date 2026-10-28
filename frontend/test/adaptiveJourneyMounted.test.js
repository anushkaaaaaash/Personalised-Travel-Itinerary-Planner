import {groundedPage,groundedPreferences} from './groundedPlanningFixture.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {travelPage,travelPreferences} from './adaptiveTravelDayFixture.js';
import {createAdaptivePlanningClient} from '../src/services/adaptivePlanning.js';
import {preferences} from './shareFixture.js';
const noCurrent=()=>({status:404,json:async()=>({error:{code:'SECTION_CURRENT_NOT_FOUND'}})});
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
    const env={mount:async(client,enabled=true,policy={sectionDays:3,maxSubmissionsPerRun:12})=>act(async()=>{renderer=create(React.createElement(Page,{signedIn:true,adaptiveEnabled:enabled,adaptivePolicy:policy,adaptiveClient:client,adaptiveStorage:storage,adaptivePollMs:10000}));}),text:()=>JSON.stringify(renderer.toJSON()),form:()=>renderer.root.findByType(Form).props,status:()=>renderer.root.findByType(Status).props,prepare:async(selected=prefs)=>{await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])env.form().onChange({target:{name,value:selected[name]}});});await act(async()=>env.form().onSubmit({preventDefault(){}}));await act(async()=>env.form().onSubmit({preventDefault(){}}));}};
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
test('validated zero-main international return day renders as completed without demanding extra visits',()=>harness(async env=>{
 const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{if(url.endsWith('/current'))return noCurrent();const body=travelPage();body.plan.requestId=JSON.parse(options.body).requestId;return{status:200,json:async()=>body};}});
 await env.mount(client);await env.prepare(travelPreferences);await act(async()=>env.form().onGenerateItinerary());assert.equal(env.status().state.plan.status,'completed');assert.equal(env.status().state.sections[0].checkpoint.itinerary.days[2].mainActivityCount,0);assert.match(env.text(),/Return journey/);assert.equal(env.status().state.needsCheck,false);
}));
test('ordinary zero-main day is rejected before a checkpoint reaches mounted results',()=>harness(async env=>{
 const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{if(url.endsWith('/current'))return noCurrent();const body=travelPage();body.plan.requestId=JSON.parse(options.body).requestId;const days=body.sections[0].checkpoint.itinerary.days;days[1].activities=structuredClone(days[2].activities);days[1].mainActivityCount=0;return{status:200,json:async()=>body};}});
 await env.mount(client);await env.prepare(travelPreferences);await act(async()=>env.form().onGenerateItinerary());assert.equal(env.status().state.needsCheck,true);assert.deepEqual(env.status().state.sections,[]);assert.doesNotMatch(env.text(),/Your full date range is planned/);
}));
test('explicit remaining-section retry keeps six accepted days and duplicate clicks make one request',()=>harness(async env=>{
 const paused=travelPage();paused.plan={...paused.plan,status:'paused',completedDays:6,remainingCreates:9,spentCents:90000,pauseReason:'CONSTRAINT_CONFLICT',activeSection:{id:'44444444-4444-4444-8444-444444444444',status:'failed',errorCode:'SECTION_CONSTRAINT_CONFLICT',failureDetails:{applicability:'proposed',explanation:'The proposed last section needs a travel-day review.',recommendations:[{field:'travelPace',reason:'Return travel takes time.',suggestion:'Review visits on the return day.'}]}}};
 const template=structuredClone(paused.sections[0]);paused.sections=[0,1].map(index=>{const section=structuredClone(template);section.id=index?'55555555-5555-4555-8555-555555555555':template.id;section.sequence=index+1;section.startDate=`2028-01-0${index*3+1}`;section.endDate=`2028-01-0${index*3+3}`;section.checkpoint.endLocation='Kyoto';section.checkpoint.itinerary.days=[0,1,2].map(offset=>({...structuredClone(template.checkpoint.itinerary.days[0]),date:`2028-01-0${index*3+offset+1}`}));section.checkpoint.itinerary.remainingBudget=2050-index*450;return section;});
 const calls=[];let resolveRetry;const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{if(url.endsWith('/current'))return noCurrent();calls.push(url);if(url==='/api/adaptive-plans'){paused.plan.requestId=JSON.parse(options.body).requestId;return{status:200,json:async()=>structuredClone(paused)};}assert.equal(url,`/api/adaptive-plans/${paused.plan.id}/retry`);assert.equal(JSON.parse(options.body).sectionId,paused.plan.activeSection.id);return new Promise(resolve=>{resolveRetry=resolve;});}});
 await env.mount(client);await env.prepare(travelPreferences);await act(async()=>env.form().onGenerateItinerary());const before=structuredClone(env.status().state.sections);await act(async()=>{env.status().onRetry();env.status().onRetry();});assert.equal(calls.length,2);assert.equal(env.status().state.plan.completedDays,6);assert.deepEqual(env.status().state.sections,before);
 const continued=structuredClone(paused);continued.plan={...continued.plan,status:'active',pauseReason:null,remainingCreates:8,activeSection:{id:paused.plan.activeSection.id,status:'queued',errorCode:null,failureDetails:null}};await act(async()=>resolveRetry({status:200,json:async()=>continued}));assert.equal(env.status().state.plan.id,paused.plan.id);assert.equal(env.status().state.plan.completedDays,6);assert.deepEqual(env.status().state.sections,before);assert.equal(calls.length,2);
}));
function existingOwnerPage(){const b=travelPage();b.preferences={...b.preferences,destination:'Paris, France'};b.sections[0].checkpoint.itinerary.destination=b.preferences.destination;b.plan={...b.plan,status:'paused',remainingCreates:0,pauseReason:'RESOURCE_ALLOWANCE_REACHED'};return b;}
test('refresh discovers an unfinished owner trip and explicit resume navigates to its real preferences without creating work',()=>harness(async env=>{
 const calls=[];const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{calls.push([url,options.method]);assert.equal(url,'/api/adaptive-plans/current');return{status:200,json:async()=>existingOwnerPage()};}});
 await env.mount(client);assert.equal(env.status().state.existingPlan.preferences.destination,'Paris, France');assert.equal(env.status().state.preferences,null);await act(async()=>env.status().onResumeExisting());assert.equal(env.status().state.existingPlan,null);assert.equal(env.status().state.preferences.destination,'Paris, France');assert.deepEqual(calls,[['/api/adaptive-plans/current','GET']]);assert.match(env.text(),/Paris, France/);
}));
test('owner rejection preserves attempted trip until explicit resume and never recreates or silently cancels',()=>harness(async env=>{
 const calls=[];let reads=0;const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{calls.push([url,options.method]);if(url.endsWith('/current'))return ++reads===1?noCurrent():{status:200,json:async()=>existingOwnerPage()};assert.equal(url,'/api/adaptive-plans');return{status:429,json:async()=>({error:{code:'SECTION_OWNER_PLAN_EXISTS'}})};}});
 await env.mount(client);await env.prepare(travelPreferences);await act(async()=>env.form().onGenerateItinerary());assert.equal(env.status().state.preferences.destination,'Kyoto');assert.equal(env.status().state.attemptedPreferences.destination,'Kyoto');assert.equal(env.status().state.existingPlan.preferences.destination,'Paris, France');await act(async()=>env.status().onResumeExisting());assert.equal(env.status().state.preferences.destination,'Paris, France');assert.deepEqual(calls.map(c=>c[1]),['GET','POST','GET']);
}));
test('explicit stop of discovered conflicting trip returns untouched attempted preferences only after confirmation',()=>harness(async env=>{
 let reads=0,resolveStop;const client=createAdaptivePlanningClient({fetchImpl:async(url)=>{if(url.endsWith('/current'))return ++reads===1?noCurrent():{status:200,json:async()=>existingOwnerPage()};if(url.endsWith('/cancel'))return new Promise(resolve=>resolveStop=resolve);return{status:429,json:async()=>({error:{code:'SECTION_OWNER_PLAN_EXISTS'}})};}});
 await env.mount(client);await env.prepare(travelPreferences);await act(async()=>env.form().onGenerateItinerary());await act(async()=>{env.status().onCancelExisting();});assert.equal(env.status().state.existingPlan.preferences.destination,'Paris, France');const stopped=existingOwnerPage();stopped.plan.status='cancelled';await act(async()=>resolveStop({status:200,json:async()=>stopped}));assert.equal(env.form().form.destination,'Kyoto');assert.equal(env.form().form.endDate,travelPreferences.endDate);
}));

const groundedPolicy={sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,maxWebSearchCalls:6,researchMode:'on_demand',provisionalDayPreviews:true,responseDeadlineMinutes:8};
test('actual Page presents complete provisional days with accepted sections and never counts drafts as completed',()=>harness(async env=>{
 let body=groundedPage(),calls=[];
 const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{calls.push([url,options.method]);if(url.endsWith('/current'))return noCurrent();if(options.method==='POST')body.plan.requestId=JSON.parse(options.body).requestId;return{status:200,json:async()=>body};}});
 await env.mount(client,true,groundedPolicy);await env.prepare(groundedPreferences);
 assert.match(env.text(),/planning requests/);assert.match(env.text(),/6 searches/);assert.match(env.text(),/8/);
 await act(async()=>env.form().onGenerateItinerary());assert.match(env.text(),/Research notes/);assert.match(env.text(),/Days taking shape/);assert.match(env.text(),/Day 01/);assert.match(env.text(),/Provisional day 2028-01-04/);assert.equal(env.status().state.plan.completedDays,3);
 const request=body.plan.requestId;body=groundedPage({days:2});body.plan.requestId=request;await act(async()=>env.status().onCheck());assert.match(env.text(),/Provisional day 2028-01-05/);assert.equal(env.status().state.plan.completedDays,3);
 body.draft=null;body.plan.status='paused';body.plan.pauseReason='RESOURCE_ALLOWANCE_REACHED';body.plan.remainingCreates=0;body.plan.activeSection=null;await act(async()=>env.status().onCheck());assert.doesNotMatch(env.text(),/Days taking shape/);assert.match(env.text(),/Day 01/);assert.match(env.text(),/Continue with another run/);assert.deepEqual(calls.map(call=>call[1]),['GET','POST','GET','GET']);
}));
test('Page research retry is explicit and never offers preference changes for a research service failure',()=>harness(async env=>{
 let body=groundedPage({status:'failed'}),calls=[];
 const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{calls.push([url,options.method]);if(url.endsWith('/current'))return noCurrent();if(url.endsWith('/research/retry')){const next=groundedPage({status:'running'});next.plan.requestId=body.plan.requestId;body=next;}else if(options.method==='POST')body.plan.requestId=JSON.parse(options.body).requestId;return{status:200,json:async()=>body};}});
 await env.mount(client,true,groundedPolicy);await env.prepare(groundedPreferences);await act(async()=>env.form().onGenerateItinerary());assert.match(env.text(),/Retry research/);assert.match(env.text(),/not evidence that your dates or budget are wrong/);assert.doesNotMatch(env.text(),/Stop planning and review changes/);
 await act(async()=>{env.status().onRetryResearch();env.status().onRetryResearch();});assert.equal(calls.filter(call=>call[0].endsWith('/research/retry')).length,1);assert.equal(env.status().state.plan.completedDays,3);assert.match(env.text(),/Researching your journey/);
}));

test('public research query correction returns to the place step after confirmed stop and preserves entries',()=>harness(async env=>{
 let body=groundedPage({status:'failed'}),resolveStop;body.research.errorCode='RESEARCH_QUERY_INVALID';body.research.toolCallsReserved=0;
 const client=createAdaptivePlanningClient({fetchImpl:async(url,options)=>{if(url.endsWith('/current'))return noCurrent();if(url.endsWith('/cancel'))return new Promise(resolve=>resolveStop=resolve);body.plan.requestId=JSON.parse(options.body).requestId;return{status:200,json:async()=>body};}});
 await env.mount(client,true,groundedPolicy);await env.prepare(groundedPreferences);await act(async()=>env.form().onGenerateItinerary());assert.match(env.text(),/Use public place names for research/);assert.doesNotMatch(env.text(),/Retry research/);
 const advice={code:'RESEARCH_QUERY_INVALID',title:'Use public place names for research.',message:'Review public place fields.',retryable:false,editStep:0,recommendations:[{field:'destination',reason:'Only public place names can be sent.',suggestion:'Use a city name without a URL or contact details.'},{field:'departureCity',suggestion:'Use the public city name.'}]};await act(async()=>env.status().onEditPreferences(advice));assert.equal(env.status().state.cancelling,true);
 body={...body,plan:{...body.plan,status:'cancelled',pauseReason:null}};await act(async()=>resolveStop({status:200,json:async()=>body}));assert.equal(env.form().step,0);assert.equal(env.form().recovery.code,'RESEARCH_QUERY_INVALID');assert.equal(env.form().form.destination,groundedPreferences.destination);assert.equal(env.form().form.departureCity,groundedPreferences.departureCity);assert.equal(env.form().form.budget,groundedPreferences.budget);assert.equal(env.form().form.endDate,groundedPreferences.endDate);
}));
