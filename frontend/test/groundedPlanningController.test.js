import test from 'node:test';
import assert from 'node:assert/strict';
import { createAdaptivePlanningController,ADAPTIVE_STORAGE_KEY } from '../src/services/adaptivePlanningController.js';
import { createAdaptivePlanningClient } from '../src/services/adaptivePlanning.js';
import { groundedPage,groundedPreferences } from './groundedPlanningFixture.js';
const requestId='22222222-2222-4222-8222-222222222222';
const tick=()=>new Promise(resolve=>setTimeout(resolve,15));
function setup(fetchImpl,seed) {
  let owner='owner',listener;const entries=new Map(seed?[[ADAPTIVE_STORAGE_KEY,JSON.stringify(seed)]]:[]);
  const controller=createAdaptivePlanningController({client:createAdaptivePlanningClient({fetchImpl}),storage:{getItem:k=>entries.get(k),setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)},getOwner:()=>owner,subscribe:fn=>{listener=fn;return()=>{};},pollMs:100000,randomUUID:()=>requestId});
  return {controller,entries,changeOwner(value){owner=value;listener();}};
}
test('fresh optional contexts replace old previews, persist only opaque identity and retain accepted sections on bad reads',async()=>{
  let body=groundedPage();const s=setup(async()=>({status:200,json:async()=>body}));
  try{await s.controller.start(groundedPreferences);assert.equal(s.controller.snapshot().draft.days.length,1);assert.equal(s.controller.snapshot().plan.completedDays,3);assert.deepEqual(Object.keys(JSON.parse(s.entries.get(ADAPTIVE_STORAGE_KEY))).sort(),['owner','planId','requestId']);assert.doesNotMatch(s.entries.get(ADAPTIVE_STORAGE_KEY),/Museum|source|draft|2028/);
    body=groundedPage({days:2});await s.controller.check();assert.equal(s.controller.snapshot().draft.days.length,2);
    body.draft.days[0].date='2029-01-01';await s.controller.check();assert.equal(s.controller.snapshot().errorCode,'ADAPTIVE_INVALID_RESPONSE');assert.equal(s.controller.snapshot().draft,null);assert.equal(s.controller.snapshot().sections.length,1);assert.equal(s.controller.snapshot().plan.completedDays,3);
    body=groundedPage();delete body.draft;delete body.research;await s.controller.check();assert.equal(s.controller.snapshot().draft,null);assert.equal(s.controller.snapshot().research,null);
  }finally{s.controller.dispose();}
});
test('restoring a handle fetches current previews but account changes and late responses cannot leak them',async()=>{
  const body=groundedPage();let resolve;const response=new Promise(r=>resolve=r);const s=setup(()=>response,{owner:'owner',requestId,planId:body.plan.id});
  try{assert.equal(s.controller.snapshot().research,null);assert.equal(s.controller.snapshot().draft,null);const pending=s.controller.resume();s.changeOwner('other');resolve({status:200,json:async()=>body});await pending;assert.equal(s.controller.snapshot().research,null);assert.equal(s.controller.snapshot().draft,null);assert.equal(s.entries.size,0);}finally{s.controller.dispose();}
});
test('known failed research retries once only on explicit click within both allowances; uncertainty cannot replay',async()=>{
  let body=groundedPage({status:'failed'}),resolve,calls=[];const pending=new Promise(r=>resolve=r);const s=setup(async(url,options)=>{calls.push([url,options.method]);if(url.endsWith('/research/retry'))return pending;return{status:200,json:async()=>body};});
  try{await s.controller.start(groundedPreferences);await tick();assert.equal(calls.length,1);const retry=s.controller.retryResearch();await s.controller.retryResearch();assert.equal(calls.length,2);assert.match(calls[1][0],/\/research\/retry$/);assert.equal(s.controller.snapshot().plan.completedDays,3);
    body=groundedPage({status:'running'});body.research.toolCallsReserved=6;resolve({status:200,json:async()=>body});await retry;assert.equal(s.controller.snapshot().research.status,'running');await s.controller.retryResearch();assert.equal(calls.length,2);
  }finally{s.controller.dispose();}
});
test('failed research with exhausted allowance, unknown submission and in-progress states never permit retry or section replay',async()=>{
  for(const [status,remaining,reserved] of [['failed',0,4],['failed',2,6],['submission_unknown',2,4],['running',2,4]]){
    const body=groundedPage({status});body.plan.remainingCreates=remaining;body.research.toolCallsReserved=reserved;let calls=0;const s=setup(async()=>{calls++;return{status:200,json:async()=>body};});
    try{await s.controller.start(groundedPreferences);await s.controller.retryResearch();await s.controller.retry();await s.controller.continue();assert.equal(calls,1);if(status==='submission_unknown')assert.equal(s.controller.snapshot().needsCheck,true);}finally{s.controller.dispose();}
  }
});
test('unknown research is checked and explicitly stopped on the same plan, not automatically restarted',async()=>{
  const body=groundedPage({status:'submission_unknown'}),calls=[];const s=setup(async(url,options)=>{calls.push([url,options.method]);if(url.endsWith('/cancel')){const stopped=groundedPage({status:'cancelled'});stopped.plan.status='cancelled';return{status:200,json:async()=>stopped};}return{status:200,json:async()=>body};});
  try{await s.controller.start(groundedPreferences);await tick();assert.equal(calls.length,1);await s.controller.check();assert.equal(calls[1][1],'GET');await s.controller.cancel();assert.match(calls[2][0],/\/cancel$/);assert.equal(s.controller.snapshot().plan.status,'cancelled');assert.equal(s.controller.snapshot().draft,null);}finally{s.controller.dispose();}
});
test('research allowance pause requires explicit new-run request and no automatic continuation',async()=>{
  const body=groundedPage({status:'failed'});body.plan.pauseReason='RESEARCH_ALLOWANCE_REACHED';body.research.toolCallsReserved=6;let calls=[];const s=setup(async(url,options)=>{calls.push([url,options.method]);return{status:200,json:async()=>body};});
  try{await s.controller.start(groundedPreferences);await tick();assert.equal(calls.length,1);await s.controller.continue();assert.match(calls[1][0],/\/continue$/);assert.equal(s.controller.snapshot().plan.completedDays,3);}finally{s.controller.dispose();}
});

test('public-query format rejection without a research job never calls the research retry endpoint',async()=>{
 const body=groundedPage({status:'failed'});body.research.errorCode='RESEARCH_QUERY_INVALID';body.research.toolCallsReserved=0;let calls=0;const s=setup(async()=>{calls++;return{status:200,json:async()=>body};});
 try{await s.controller.start(groundedPreferences);assert.equal(s.controller.snapshot().research.errorCode,'RESEARCH_QUERY_INVALID');await s.controller.retryResearch();await s.controller.retry();assert.equal(calls,1);}finally{s.controller.dispose();}
});
