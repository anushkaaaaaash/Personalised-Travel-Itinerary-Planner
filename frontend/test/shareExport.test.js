import test from 'node:test';
import assert from 'node:assert/strict';
import { exportSnapshot,compactSummary,copySummary,printDocument,printSummary,downloadText } from '../src/services/itineraryExport.js';
import { parseItineraryImport } from '../src/services/itineraryImport.js';
import { createDetailController,savedTripsAPI } from '../src/services/savedTripDetail.js';
import { PlannerRequestError } from '../src/services/readRequest.js';
import { id,preferences,plan,detail } from './shareFixture.js';
test('full export roundtrips with explicit preferences while excluding unknown nested account data',()=>{
  const p=plan();p.access_token='PRIVATE_SENTINEL';p.user_id='PRIVATE_SENTINEL';p.days[0].owner='PRIVATE_SENTINEL';p.days[0].activities[0].credential='PRIVATE_SENTINEL';
  const text=exportSnapshot(p,{preferences,userEdited:true});assert.ok(!text.includes('PRIVATE_SENTINEL'));
  const restored=parseItineraryImport(text);assert.deepEqual(restored.preferences,preferences);assert.equal(restored.userEdited,true);assert.equal(restored.itinerary.days[0].activities[0].title,'Museum');
});
test('summary omits notes and preferences but includes dates timing group budget and estimate warning',()=>{
  const text=compactSummary(plan());for(const s of ['Kyoto','2028-02-28','09:00','60 min','USD 150','not bookings'])assert.ok(text.includes(s));
  for(const s of ['Private dietary','Private mobility','Private activity','Tokyo'])assert.ok(!text.includes(s));
});
test('print output escapes text and contains only the compact itinerary',()=>{
  const p=plan();p.days[0].activities[0].title='<img src=x onerror=alert(1)>';
  const html=printDocument(p);assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('Private activity'));assert.ok(!html.includes('<form'));
});
test('clipboard denied or unavailable gives honest manual-copy fallback',async()=>{
  await assert.rejects(copySummary('safe',{}),/Select and copy/);await assert.rejects(copySummary('safe',{writeText:async()=>{throw new Error('private raw failure');}}),/denied.*Select and copy/);
  let copied;await copySummary('safe',{writeText:async value=>copied=value});assert.equal(copied,'safe');
});
test('download failures still remove anchor and release blob',async()=>{
  let removed=false,revoked=false;assert.throws(()=>downloadText('safe','travel-summary.txt','text/plain',{body:{appendChild(){}},createElement:()=>({click(){throw new Error();},remove(){removed=true;}})},{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:()=>revoked=true}));
  assert.ok(removed);await new Promise(r=>setTimeout(r,1050));assert.ok(revoked);
});
test('print uses an isolated document and confirms only invocation before cleanup',async()=>{
  let frame,printed=false,after;const pending=printSummary(plan(),{createElement:()=>frame={style:{},remove(){frame.removed=true;},contentWindow:{focus(){},print(){printed=true;},addEventListener:(name,fn)=>after=fn}},body:{appendChild(){}}});
  assert.ok(frame.srcdoc.includes('Travel itinerary summary'));frame.onload();assert.deepEqual(await pending,{requested:true});assert.ok(printed);after();assert.ok(frame.removed);
});
test('async print invocation failure rejects safely and removes the frame',async()=>{
  let frame;const pending=printSummary(plan(),{createElement:()=>frame={style:{},remove(){frame.removed=true;},contentWindow:{focus(){},print(){throw new Error('PRIVATE_RUNTIME_ERROR');},addEventListener(){}}},body:{appendChild(){}}});
  frame.onload();await assert.rejects(pending,e=>e.message.includes('could not be started')&&!e.message.includes('PRIVATE_RUNTIME_ERROR'));assert.ok(frame.removed);
});
test('print setup and iframe loading failures reject with cleanup',async()=>{
  await assert.rejects(printSummary(plan(),{createElement(){throw new Error('RAW');}}),/could not be started/);
  let frame;await assert.rejects(printSummary(plan(),{createElement:()=>frame={style:{},remove(){frame.removed=true;}},body:{appendChild(){throw new Error('RAW');}}}),/could not be started/);assert.ok(frame.removed);
  const pending=printSummary(plan(),{createElement:()=>frame={style:{},remove(){frame.removed=true;}},body:{appendChild(){}}});frame.onerror();await assert.rejects(pending,/could not be started/);assert.ok(frame.removed);
});
function setup(api={}){let state;const owner={user:{id:'synthetic-owner'}};const c=createDetailController(id,s=>state=s,{session:()=>owner,api:{get:async()=>detail(),...api}});return {c,get state(){return state;}};}
test('mount only reads; explicit update keeps original ID/version; conflict preserves edits',async()=>{
  let calls=0;const s=setup({update:async(gotId,v,record)=>{calls++;assert.equal(gotId,id);assert.equal(v,2);assert.equal(record.title,'Edited');throw new PlannerRequestError('Changed elsewhere',{status:409});}});
  await s.c.run('load');assert.equal(calls,0);s.c.edit({title:'Edited'});await s.c.run('update');assert.equal(calls,1);assert.equal(s.state.title,'Edited');assert.equal(s.state.record.version,2);assert.ok(s.state.dirty);
});
test('regeneration is explicit, keeps previous plan until success, never invokes save',async()=>{
  let resolve,generated=0;const s=setup({generate:()=>{generated++;return new Promise(r=>resolve=r);},update:()=>assert.fail('autosave')});
  await s.c.run('load');assert.equal(generated,0);const original=s.state.plan;const request=s.c.run('generate');assert.equal(s.state.plan,original);assert.deepEqual(await s.c.run('generate'),{ignored:true});
  const replacement=plan();replacement.explanation='Replacement';resolve(replacement);await request;assert.equal(s.state.plan,replacement);assert.ok(s.state.dirty);
});
test('generation failure retains local plan and edits',async()=>{const s=setup({generate:async()=>{throw new PlannerRequestError('Unavailable');}});await s.c.run('load');s.c.edit({title:'Unstored'});const p=s.state.plan;await s.c.run('generate');assert.equal(s.state.plan,p);assert.equal(s.state.title,'Unstored');});
test('route disposal ignores old responses and does not update another route',async()=>{let resolve;const s=setup({get:()=>new Promise(r=>resolve=r)});const request=s.c.run('load');s.c.dispose();resolve(detail());assert.deepEqual(await request,{ignored:true});assert.equal(s.state.record,null);});
test('logout during request ignores response even before React unmount',async()=>{let owner={},resolve;let state;const c=createDetailController(id,s=>state=s,{session:()=>owner,api:{get:()=>new Promise(r=>resolve=r)}});const req=c.run('load');owner=null;resolve(detail());assert.deepEqual(await req,{ignored:true});assert.equal(state.record,null);});
test('invalid IDs and signed-out detail access make no API request',async()=>{
  for(const [key,session] of [['bad',()=>({})],[id,()=>null]]){let state;const c=createDetailController(key,s=>state=s,{session,api:{get:()=>assert.fail('request')}});await c.run('load');assert.ok(state.error);}
});
for(const status of [401,403,404])test(`private detail status ${status} retained safely`,async()=>{const s=setup({get:async()=>{throw new PlannerRequestError('Unavailable',{status});}});await s.c.run('load');assert.equal(s.state.record,null);assert.equal(s.state.error,'Unavailable');});
test('saved facade uses owner-scoped endpoint, not legacy preference route',async()=>{let url;const r=await savedTripsAPI.get(id,{fetchImpl:async value=>{url=value;return {status:200,json:async()=>detail()};}});assert.equal(url,`/api/saved-itineraries/${id}`);assert.equal(r.version,2);});
test('cancel cannot abort or forget a pending write; late confirmed revision is accepted',async()=>{
  let finish,signal;const s=setup({update:async(gotId,version,record,options)=>{signal=options.signal;return new Promise(r=>finish=r);}});
  await s.c.run('load');s.c.edit({title:'Edited'});const pending=s.c.run('update');
  assert.equal(s.state.activeAction,'update');assert.equal(s.c.cancel(),false);assert.equal(signal.aborted,false);assert.equal(s.state.busy,true);
  assert.deepEqual(await s.c.run('update'),{ignored:true});s.c.edit({title:'Must not change'});assert.equal(s.state.title,'Edited');
  finish({...detail(),title:'Edited',version:3});await pending;assert.equal(s.state.record.version,3);assert.equal(s.state.busy,false);assert.equal(s.state.activeAction,null);assert.equal(s.state.dirty,false);
});
for(const action of ['generate','refine'])test(`cancel ${action} retains plan and ignores late response`,async()=>{
  let finish,signal;const s=setup({[action]:async(input,options)=>{signal=options.signal;return new Promise(r=>finish=r);}});
  await s.c.run('load');const previous=s.state.plan;const pending=s.c.run(action,{});assert.equal(s.c.cancel(),true);assert.ok(signal.aborted);assert.equal(s.state.plan,previous);assert.equal(s.state.busy,false);
  finish({...plan(),explanation:'Must be ignored'});assert.deepEqual(await pending,{ignored:true});assert.equal(s.state.plan,previous);assert.equal(s.c.cancel(),false);
});
