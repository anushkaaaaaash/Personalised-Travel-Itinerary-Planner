import test from 'node:test';import assert from 'node:assert/strict';import React from 'react';import {act,create} from 'react-test-renderer';import {createServer} from 'vite';import {fileURLToPath} from 'node:url';import {continuousDayFixture} from './continuousDayFixture.js';
async function harness(run){const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer,current;const renders=[];const{setSession}=await server.ssrLoadModule('/src/services/session.js');const{default:useDays}=await server.ssrLoadModule('/src/components/useContinuousPlanDays.js');const session=owner=>({user:{id:owner},access_token:'synthetic',expires_at:Date.now()/1000+3600});setSession(session('owner-a'));function View(props){current=useDays(props);renders.push({complete:current.complete,loadedDays:current.loadedDays});return React.createElement('div',null,current.sections.flatMap(s=>s.checkpoint.itinerary.days.map(d=>d.date)).join('|'));}try{await run({mount:async props=>act(async()=>{renderer=create(React.createElement(View,props));}),update:async props=>act(async()=>renderer.update(React.createElement(View,props))),state:()=>current,renders:()=>renders,text:()=>JSON.stringify(renderer.toJSON()),owner:async name=>act(async()=>setSession(session(name))),unmount:async()=>act(async()=>renderer.unmount())});}finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);await server.close();}}
const first=f=>({...f.page(),pageCursor:0,needsCheck:false});
test('later-page read failure keeps earlierdays and explicit read-only reload completes the continuousview',()=>harness(async env=>{const f=continuousDayFixture();let broken=true,calls=0;const client={get:async(id,{afterSequence})=>{calls++;if(broken)throw Error('network');return f.page(afterSequence);}};await env.mount({state:first(f),client,enabled:true});assert.equal(env.state().loadedDays,3);assert.match(env.state().error,/Some planned days/);assert.match(env.text(),/2028-01-01/);broken=false;await act(async()=>env.state().retry());assert.equal(env.state().loadedDays,17);assert.equal(env.state().complete,true);assert.equal(calls,3);}));
test('late continuation after ownerchange or disposal never publishes private retaineddays',()=>harness(async env=>{const f=continuousDayFixture();let finish;const client={get:()=>new Promise(resolve=>finish=resolve)};await env.mount({state:first(f),client,enabled:true});assert.equal(env.state().loadedDays,3);await env.owner('owner-b');await act(async()=>finish(f.page(3)));assert.equal(env.state().loadedDays,0);assert.doesNotMatch(env.text(),/2028-01-01/);await env.unmount();}));
test('poll refreshes at an unchanged completed frontier do not refetch everypage',()=>harness(async env=>{const f=continuousDayFixture();let calls=0;const client={get:async(id,{afterSequence})=>{calls++;return f.page(afterSequence);}};await env.mount({state:first(f),client,enabled:true});assert.equal(calls,2);await env.update({state:{...first(f),plan:{...f.plan,version:999}},client,enabled:true});assert.equal(calls,2);assert.equal(env.state().loadedDays,17);}));

test('a changed uncertain frontier never inherits complete status or reads another page',()=>harness(async env=>{
 const f=continuousDayFixture();let reads=0;const client={get:async()=>{reads++;assert.fail('uncertain frontier cannot fetch more pages');}};
 const initial={...first(f),plan:{...f.plan,completedDays:3,spentCents:45000},nextCursor:null};
 await env.mount({state:initial,client,enabled:true});assert.equal(env.state().loadedDays,3);assert.equal(env.state().complete,true);
 const next={...initial,plan:{...initial.plan,completedDays:9,spentCents:135000},nextCursor:3,needsCheck:true};
 const firstRender=env.renders().length;await env.update({state:next,client,enabled:true});assert.equal(env.renders()[firstRender].complete,false);assert.equal(env.state().loadedDays,3);assert.equal(env.state().complete,false);assert.equal(env.state().loading,false);assert.equal(reads,0);assert.match(env.text(),/2028-01-01/);
}));
test('an uncertain snapshot can reveal already validated accepted days without extra reads',()=>harness(async env=>{
 const f=continuousDayFixture();let reads=0;const client={get:async()=>{reads++;assert.fail('no additional request');}};
 const initial={...first(f),plan:{...f.plan,completedDays:3,spentCents:45000},nextCursor:null};
 await env.mount({state:initial,client,enabled:true});
 const next={...initial,plan:{...initial.plan,completedDays:9,spentCents:135000},sections:f.all.slice(0,3),needsCheck:true};
 await env.update({state:next,client,enabled:true});assert.equal(env.state().loadedDays,9);assert.equal(env.state().complete,true);assert.equal(env.state().loading,false);assert.equal(reads,0);assert.match(env.text(),/2028-01-09/);
}));

test('an uncertain later-page snapshot never becomes the first prefix or triggers a GET',()=>harness(async env=>{
 const f=continuousDayFixture();let reads=0;const client={get:async()=>{reads++;assert.fail('no additional request');}};
 const initial={...first(f),plan:{...f.plan,completedDays:3,spentCents:45000},nextCursor:null};
 await env.mount({state:initial,client,enabled:true});
 const next={...initial,plan:{...initial.plan,completedDays:9,spentCents:135000},sections:f.all.slice(1,3),pageCursor:3,needsCheck:true};
 await env.update({state:next,client,enabled:true});assert.equal(env.state().loadedDays,3);assert.equal(env.state().complete,false);assert.equal(reads,0);assert.match(env.text(),/2028-01-01/);assert.doesNotMatch(env.text(),/2028-01-09/);
}));
