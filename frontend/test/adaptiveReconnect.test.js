import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdaptivePlanningController,ADAPTIVE_STORAGE_KEY} from '../src/services/adaptivePlanningController.js';
import {preferences} from './shareFixture.js';
const id='11111111-1111-4111-8111-111111111111',requestId='22222222-2222-4222-8222-222222222222';
const page=(status='active',patch={})=>({plan:{id,requestId,status,totalDays:9,completedDays:3,remainingCreates:8,pauseReason:null,activeSection:null,...patch},preferences,sections:[{sequence:1}],nextCursor:null});
const failure=(code='ADAPTIVE_UNAVAILABLE',confirmed=false)=>Object.assign(Error('private transport detail'),{code,confirmed});
async function harness(fn){
 const realSet=globalThis.setTimeout,realClear=globalThis.clearTimeout;let timerId=0;const timers=new Map(),delays=[];let owner='owner',listener;
 globalThis.setTimeout=(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});delays.push(delay);return id;};globalThis.clearTimeout=id=>timers.delete(id);
 const entries=new Map();let controller;
 const setup=(client,seed)=>{if(seed)entries.set(ADAPTIVE_STORAGE_KEY,JSON.stringify(seed));return controller=createAdaptivePlanningController({client,storage:{getItem:k=>entries.get(k),setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)},getOwner:()=>owner,subscribe:fn=>{listener=fn;return()=>{};},randomUUID:()=>requestId});};
 const tick=async()=>{assert.equal(timers.size,1);const [id,{callback}]=timers.entries().next().value;timers.delete(id);callback();for(let i=0;i<8;i++)await Promise.resolve();};
 try{await fn({setup,tick,timers,delays,entries,changeOwner:()=>{owner='other';listener();}});}finally{controller?.dispose();globalThis.setTimeout=realSet;globalThis.clearTimeout=realClear;}
}
test('lost create response performs exactly three same-request GETs, never another POST or ID',()=>harness(async h=>{
 let posts=0,reads=0;const c=h.setup({start:async(_,r)=>{assert.equal(r,requestId);posts++;throw failure();},findRequest:async r=>{assert.equal(r,requestId);reads++;throw failure('ADAPTIVE_NOT_FOUND');}});
 await c.start(preferences);const stored=h.entries.get(ADAPTIVE_STORAGE_KEY);assert.equal(c.snapshot().reconnecting,true);assert.equal(c.snapshot().reconnectAttempt,1);assert.ok(c.snapshot().reconnectNextAt>Date.now());
 for(let i=0;i<3;i++){await c.start(preferences);await h.tick();}
 assert.deepEqual(h.delays,[2000,5000,10000]);assert.equal(posts,1);assert.equal(reads,3);assert.equal(h.timers.size,0);assert.equal(c.snapshot().reconnecting,false);assert.equal(c.snapshot().reconnectAttempt,3);assert.equal(c.snapshot().reconnectNextAt,null);assert.equal(c.snapshot().needsCheck,true);assert.equal(h.entries.get(ADAPTIVE_STORAGE_KEY),stored);
 await c.check();assert.equal(reads,4);assert.equal(h.timers.size,0);assert.equal(posts,1);
}));
test('transient reads keep accepted days and recover automatically, success resets budget',()=>harness(async h=>{
 let reads=0;const c=h.setup({start:async()=>page(),get:async()=>{reads++;if([1,3].includes(reads))throw failure();return page('paused');}});
 await c.start(preferences);await h.tick();assert.equal(c.snapshot().needsCheck,true);assert.deepEqual(c.snapshot().sections,[{sequence:1}]);assert.equal(c.snapshot().plan.completedDays,3);assert.equal(c.snapshot().reconnectAttempt,1);
 await h.tick();assert.equal(c.snapshot().needsCheck,false);assert.equal(c.snapshot().reconnecting,false);assert.equal(c.snapshot().reconnectAttempt,0);assert.equal(h.timers.size,0);
 await c.check();assert.equal(c.snapshot().reconnectAttempt,1);await h.tick();assert.equal(reads,4);assert.equal(c.snapshot().needsCheck,false);
}));
test('successful submission-unknown snapshots consume bounded reads without resetting the budget',()=>harness(async h=>{
 let reads=0,posts=0;const unknown=()=>page('paused',{pauseReason:'SUBMISSION_UNKNOWN',activeSection:{id,status:'submission_unknown'}});
 const c=h.setup({start:async()=>{posts++;return unknown();},get:async()=>{reads++;return unknown();},retry:async()=>assert.fail('must not retry')});await c.start(preferences);
 for(let i=0;i<3;i++){await c.retry();await h.tick();}assert.equal(reads,3);assert.equal(posts,1);assert.equal(h.timers.size,0);assert.equal(c.snapshot().needsCheck,true);assert.equal(c.snapshot().reconnecting,false);
}));
test('auth and definitive known expiry stop reconnecting without recreation',()=>harness(async h=>{
 let reads=0;const c=h.setup({get:async()=>{reads++;throw failure('AUTH_REQUIRED');}},{owner:'owner',requestId,planId:id});await c.resume();assert.equal(reads,1);assert.equal(h.timers.size,0);assert.equal(c.snapshot().errorCode,'AUTH_REQUIRED');assert.equal(h.entries.size,0);
}));
test('known unavailable state is terminal and does not schedule a retry',()=>harness(async h=>{
 const c=h.setup({get:async()=>{throw failure('ADAPTIVE_PLAN_UNAVAILABLE',true);}},{owner:'owner',requestId,planId:id});await c.resume();assert.equal(c.snapshot().plan.status,'expired');assert.equal(h.timers.size,0);assert.equal(c.snapshot().reconnecting,false);assert.equal(h.entries.size,1);
}));
test('owner change or dispose removes scheduled reconnect and ignores in-flight late reads',async()=>{
 for(const dispose of [false,true])await harness(async h=>{let resolve,reads=0;const pending=new Promise(r=>{resolve=r;});const c=h.setup({start:async()=>{throw failure();},findRequest:async()=>{reads++;return pending;}});await c.start(preferences);await h.tick();assert.equal(reads,1);if(dispose)c.dispose();else h.changeOwner();resolve(page());for(let i=0;i<8;i++)await Promise.resolve();assert.equal(c.snapshot().plan,null);assert.equal(h.timers.size,0);});
});
test('failed cancellation reconciles read-only and never automatically repeats stop',()=>harness(async h=>{
 let stops=0,reads=0;const c=h.setup({start:async()=>page(),cancel:async()=>{stops++;throw failure();},get:async()=>{reads++;throw failure();}});await c.start(preferences);await c.cancel();assert.equal(stops,1);
 for(let i=0;i<3;i++)await h.tick();assert.equal(stops,1);assert.equal(reads,3);assert.equal(c.snapshot().cancelUnconfirmed,true);assert.equal(h.timers.size,0);assert.deepEqual(c.snapshot().sections,[{sequence:1}]);
}));
test('duplicate checks cannot overlap an automatic read or overwrite retained days',()=>harness(async h=>{
 let resolve,reads=0;const c=h.setup({get:async()=>{reads++;if(reads===1)throw failure();return new Promise(r=>{resolve=r;});}},{owner:'owner',requestId,planId:id});await c.resume();await h.tick();assert.deepEqual(await c.check(),{ignored:true});assert.equal(reads,2);resolve(page('completed'));for(let i=0;i<8;i++)await Promise.resolve();assert.equal(c.snapshot().plan.status,'completed');assert.equal(h.timers.size,0);
}));

test('explicit cancellation replaces pending reconnect with one read and stops once identity is confirmed',()=>harness(async h=>{
 let reads=0,stops=0;const c=h.setup({start:async()=>page(),get:async()=>{reads++;if(reads===1)throw failure();return page();},cancel:async()=>{stops++;return page('cancelled');}});await c.start(preferences);await h.tick();assert.equal(c.snapshot().reconnecting,true);await c.cancel();for(let i=0;i<8;i++)await Promise.resolve();assert.equal(reads,2);assert.equal(stops,1);assert.equal(c.snapshot().plan.status,'cancelled');assert.equal(h.timers.size,0);
}));
test('confirmed invalid or rejected reads do not retry indefinitely or automatically',()=>harness(async h=>{
 const c=h.setup({get:async()=>{throw failure('ADAPTIVE_REJECTED',true);}},{owner:'owner',requestId,planId:id});await c.resume();assert.equal(h.timers.size,0);assert.equal(c.snapshot().reconnecting,false);assert.equal(c.snapshot().needsCheck,true);
}));
