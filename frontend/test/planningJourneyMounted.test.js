import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';
const jobId='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const store=()=>{const map=new Map();return {getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key),dump:()=>[...map.values()].join('')};};
async function harness(run){
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
 const {setSession}=await server.ssrLoadModule('/src/services/session.js');
 try{
  const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');const {default:Generated}=await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');const {createPlanningJobsClient,itineraryEvidenceDigest}=await server.ssrLoadModule('/src/services/planningJobs.js');
  const storage=store();setSession({user:{id:'owner-a'},access_token:'TEST_ONLY_TOKEN',expires_at:Date.now()/1000+3600});
  const env={storage,setSession,digest:itineraryEvidenceDigest,editDay:async day=>act(async()=>renderer.root.findByType(Generated).props.onEditDay(day)),client:fetchImpl=>createPlanningJobsClient({enabled:true,fetchImpl}),mount:async client=>act(async()=>{renderer=create(React.createElement(Page,{signedIn:true,jobsEnabled:true,jobClient:client,jobStorage:storage,jobPollMs:10}));}),unmount:async()=>act(async()=>{renderer?.unmount();renderer=null;}),text:()=>JSON.stringify(renderer.toJSON()),click:async label=>act(async()=>{const button=renderer.root.findAllByType('button').find(n=>n.children.join('').includes(label));assert.ok(button,label);button.props.onClick();}),prepare:async()=>{const props=()=>renderer.root.findByType(Form).props;await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:preferences[name]}});});await act(async()=>props().onSubmit({preventDefault(){}}));await act(async()=>props().onSubmit({preventDefault(){}}));return props;}};
  await run(env);
 }finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);await server.close();}
}
const snapshot=(requestId,status='running')=>({id:jobId,requestId,status,result:status==='succeeded'?plan():null,error:null,createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+3600000).toISOString()});
const response=body=>({status:200,json:async()=>body});
const tick=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,35));});
test('feature-gated journey submits once and polls real states to a checked itinerary',()=>harness(async env=>{
 let requestId,posts=0,reads=0;const client=env.client(async(url,options)=>{if(options.method==='POST'){assert.equal(url,'/api/planning-jobs');posts++;requestId=JSON.parse(options.body).requestId;return response(snapshot(requestId,'queued'));}reads++;return response(snapshot(requestId,reads>1?'succeeded':'running'));});
 await env.mount(client);const props=await env.prepare();const handlers=props();await act(async()=>{handlers.onGenerateItinerary();handlers.onGenerateItinerary();});assert.equal(posts,1);assert.match(env.text(),/in line/);
 for(let i=0;i<4&&!env.text().includes('Make the days your own');i++)await tick();
 assert.match(env.text(),/Make the days your own/);assert.equal(posts,1);assert.ok(reads>=2);assert.doesNotMatch(env.storage.dump(),/Kyoto|Tokyo|budget|TEST_ONLY_TOKEN|days/);
}));
test('lost submit response checks the same request read-only, then confirms cancellation',()=>harness(async env=>{
 let requestId,posts=0,lookups=0,cancels=0;
 const client=env.client(async(url,options)=>{if(url==='/api/planning-jobs'){posts++;requestId=JSON.parse(options.body).requestId;throw Error('PRIVATE_NETWORK_DETAIL');}if(url.endsWith('/cancel')){cancels++;return response(snapshot(requestId,'cancelled'));}if(url.includes('/requests/')){lookups++;assert.equal(options.method,'GET');assert.ok(url.endsWith(requestId));return response(snapshot(requestId));}return response(snapshot(requestId));});
 await env.mount(client);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.match(env.text(),/Check my plan/);assert.doesNotMatch(env.text(),/PRIVATE_NETWORK_DETAIL/);await env.click('Check my plan');assert.equal(lookups,1);assert.equal(posts,1);await env.click('Cancel planning');assert.equal(cancels,1);assert.match(env.text(),/Planning stopped/);assert.equal(posts,1);
}));
test('remount resumes with authenticated context, storing no trip details',()=>harness(async env=>{
 let requestId,posts=0,contexts=0;let complete=false;
 const client=env.client(async(url,options)=>{if(url==='/api/planning-jobs'){posts++;requestId=JSON.parse(options.body).requestId;return response(snapshot(requestId));}if(url.endsWith('/context')){contexts++;return response({preferences,job:snapshot(requestId,complete?'succeeded':'running')});}return response(snapshot(requestId));});
 await env.mount(client);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());await env.unmount();assert.doesNotMatch(env.storage.dump(),/destination|budget|interests|TEST_ONLY_TOKEN/);complete=true;await env.mount(client);assert.equal(contexts,1);assert.equal(posts,1);assert.match(env.text(),/Make the days your own/);assert.match(env.text(),new RegExp(preferences.destination));
}));
test('logout clears the resumable identity and ignores a late start response',()=>harness(async env=>{
 let resolve,requestId;const client=env.client(async(url,options)=>{assert.equal(url,'/api/planning-jobs');requestId=JSON.parse(options.body).requestId;return new Promise(done=>{resolve=done;});});
 await env.mount(client);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.ok(env.storage.dump());await act(async()=>env.setSession(null));assert.equal(env.storage.dump(),'');await act(async()=>resolve(response(snapshot(requestId,'succeeded'))));assert.doesNotMatch(env.text(),/Make the days your own/);
}));

test('bound server evidence reaches the itinerary and is invalidated by a local edit',()=>harness(async env=>{
 const result=plan();const day=result.days[0],activity=day.activities[0];

 const evidence={version:1,destinationId:'kyoto-jp',timeZone:'Asia/Tokyo',itineraryDigest:await env.digest(result),assessments:[{scope:{destinationId:'kyoto-jp',localDate:day.date,subjectId:activity.id,timeZone:'Asia/Tokyo',kind:'closure'},status:'verified',severity:'blocker',summary:'Fixture venue closed for maintenance',fallback:'Check opening hours',sourceURL:'https://example.test/official-hours',checkedAt:new Date(Date.now()-10000).toISOString(),expiresAt:new Date(Date.now()+60000).toISOString(),validFrom:day.date,validUntil:day.date}]};
 const client=env.client(async(url,options)=>{assert.equal(url,'/api/planning-jobs');const requestId=JSON.parse(options.body).requestId;return response({...snapshot(requestId,'succeeded'),result,evidence});});
 await env.mount(client);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());for(let i=0;i<4&&!env.text().includes('Make the days your own');i++)await tick();assert.match(env.text(),/Check before visiting: /);assert.match(env.text(),/Fixture venue closed for maintenance/);assert.doesNotMatch(env.storage.dump(),/maintenance|evidence|sourceURL/);
 await env.editDay({...day,activities:day.activities.map((item,index)=>index===0?{...item,notes:'Changed locally'}:item)});assert.doesNotMatch(env.text(),/Fixture venue closed for maintenance/);assert.match(env.text(),/Not checked/);
}));

test('purged known job after remount offers explicit fresh planning without automatic creation',()=>harness(async env=>{
 let requestId,posts=0,purged=false;const client=env.client(async(url,options)=>{if(url==='/api/planning-jobs'){posts++;requestId=JSON.parse(options.body).requestId;return response(snapshot(requestId));}if(url.endsWith('/context')&&purged)return {status:404,json:async()=>({})};return response(snapshot(requestId));});
 await env.mount(client);let props=await env.prepare();await act(async()=>props().onGenerateItinerary());await env.unmount();purged=true;await env.mount(client);assert.match(env.text(),/planning session is no longer available/);assert.equal(posts,1);await tick();assert.equal(posts,1);await env.click('Back to trip preferences');assert.equal(env.storage.dump(),'');props=await env.prepare();purged=false;await act(async()=>props().onGenerateItinerary());assert.equal(posts,2);
}));
test('owner change clears a pending job and never reuses its response for the new account',()=>harness(async env=>{
 let resolve,requestId;const client=env.client(async(url,options)=>{requestId=JSON.parse(options.body).requestId;return new Promise(done=>{resolve=done;});});await env.mount(client);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());await act(async()=>env.setSession({user:{id:'owner-b'},access_token:'OTHER_TEST_TOKEN',expires_at:Date.now()/1000+3600}));assert.equal(env.storage.dump(),'');await act(async()=>resolve(response(snapshot(requestId,'succeeded'))));assert.doesNotMatch(env.text(),/Make the days your own/);
}));

test('unsupported trip length stays editable and creates no background request or handle',()=>harness(async env=>{
 let starts=0;const client=env.client(async(url,options)=>{starts++;return response(snapshot(JSON.parse(options.body).requestId));});await env.mount(client);let props=await env.prepare();await act(async()=>props().onChange({target:{name:'endDate',value:'2028-03-31'}}));await act(async()=>props().onGenerateItinerary());assert.equal(starts,0);assert.equal(env.storage.dump(),'');assert.match(env.text(),/Choose a trip of 1–14 days/);props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.equal(starts,1);
}));

test('confirmed start rejection releases the handle for an explicit corrected plan',()=>harness(async env=>{
 let starts=0;const client=env.client(async(url,options)=>{assert.equal(url,'/api/planning-jobs');starts++;return starts===1?{status:400,json:async()=>({error:{message:'PRIVATE_REJECTION_DETAIL'}})}:response(snapshot(JSON.parse(options.body).requestId));});await env.mount(client);let props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.match(env.text(),/check your trip details/i);assert.doesNotMatch(env.text(),/PRIVATE_REJECTION_DETAIL/);assert.equal(env.storage.dump(),'');assert.equal(starts,1);await env.click('Back to trip preferences');await act(async()=>props().onGenerateItinerary());assert.equal(starts,2);
}));
