import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
let server,Guidance,estimate,elapsedLabel;
before(async()=>{server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});const m=await server.ssrLoadModule('/src/components/PlanningWaitGuidance.jsx');Guidance=m.default;estimate=m.planningTimeEstimate;elapsedLabel=m.elapsedVisitLabel;});
after(async()=>server?.close());
test('estimated range is honest, whole-trip and bounded, never fake remaining progress',()=>{
 assert.match(estimate(9),/9–15 minutes/);assert.match(estimate(9),/limited recent timing observations/);assert.match(estimate(9),/not a countdown or a guarantee/);assert.match(estimate(9),/research and retries may take longer/);
 assert.match(estimate(30),/30–50 minutes/);assert.doesNotMatch(estimate(31),/\d+–\d+/);assert.match(estimate(1000),/several planning runs/);
 for(const days of [0,-1,NaN,2.5,'9'])assert.equal(estimate(days),null);
 assert.equal(elapsedLabel(59999),'Less than a minute on this visit');assert.equal(elapsedLabel(60000),'1 minute on this visit');assert.equal(elapsedLabel(120000),'2 minutes on this visit');
 const html=renderToStaticMarkup(React.createElement(Guidance,{planId:'known-plan',totalDays:9,expiresAt:'2099-01-01T00:00:00Z'}));assert.match(html,/return from this account before/);assert.match(html,/Planning may pause for your approval/);assert.match(html,/not an account-saved trip/);assert.doesNotMatch(html,/<progress|\d+%|minutes remaining/);
 for(const props of [{planId:null,expiresAt:'2099-01-01T00:00:00Z'},{planId:'known',expiresAt:'2000-01-01T00:00:00Z'},{planId:'known',expiresAt:'invalid'}])assert.doesNotMatch(renderToStaticMarkup(React.createElement(Guidance,{totalDays:9,...props})),/You can leave this page/);
});
test('elapsed display tracks this mounted visit, resets for another plan and cleans its timer',async()=>{
 const originalNow=Date.now,originalSet=globalThis.setInterval,originalClear=globalThis.clearInterval;let now=1000,tick,cleared=0,renderer;
 Date.now=()=>now;globalThis.setInterval=(callback,delay)=>{assert.equal(delay,15000);tick=callback;return 123;};globalThis.clearInterval=id=>{assert.equal(id,123);cleared++;};
 try {
  await act(async()=>{renderer=create(React.createElement(Guidance,{planId:'plan-a',totalDays:9}));});
  now+=125000;await act(async()=>tick());assert.match(JSON.stringify(renderer.toJSON()),/2 minutes on this visit/);
  await act(async()=>renderer.update(React.createElement(Guidance,{planId:'plan-a',totalDays:9,active:false})));assert.equal(renderer.toJSON(),null);assert.equal(cleared,1);now+=60000;
  await act(async()=>renderer.update(React.createElement(Guidance,{planId:'plan-a',totalDays:9,active:true})));assert.match(JSON.stringify(renderer.toJSON()),/3 minutes on this visit/);
  await act(async()=>renderer.update(React.createElement(Guidance,{planId:'plan-b',totalDays:9})));assert.match(JSON.stringify(renderer.toJSON()),/Less than a minute on this visit/);assert.equal(cleared,2);
  await act(async()=>renderer.unmount());renderer=null;assert.equal(cleared,3);
 }finally{if(renderer)await act(async()=>renderer.unmount());Date.now=originalNow;globalThis.setInterval=originalSet;globalThis.clearInterval=originalClear;}
});
test('wait guidance is shown only during known active planning, never paused, terminal or uncertain states',async()=>{
 const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
 const state={plan:{id:'known-plan',status:'active',totalDays:9,completedDays:0,remainingCreates:3,runAllowance:3,expiresAt:'2099-01-01T00:00:00Z'},preferences:{destination:'Kyoto',startDate:'2028-01-01',endDate:'2028-01-09'},sections:[],nextCursor:null,pageCursor:0};
 const render=value=>renderToStaticMarkup(React.createElement(Status,{state:value}));
 assert.match(render(state),/9–15 minutes/);assert.match(render(state),/Destination notes while planning/);assert.doesNotMatch(render(state),/destination-loading__intro/);
 for(const status of ['paused','completed','cancelled','expired'])assert.doesNotMatch(render({...state,plan:{...state.plan,status}}),/Rough whole-trip estimate|on this visit|You can leave this page/);
 for(const patch of [{needsCheck:true},{error:'unconfirmed'},{research:{status:'submission_unknown'}},{plan:{...state.plan,activeSection:{status:'submission_unknown'}}}])assert.doesNotMatch(render({...state,...patch}),/Rough whole-trip estimate|on this visit|You can leave this page/);
});


test('same-plan destination notes do not repeat after pause or uncertainty recovery',async()=>{
 const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');let renderer;
 const state={plan:{id:'known-plan',status:'active',totalDays:9,completedDays:0,remainingCreates:3,runAllowance:3},preferences:{destination:'Kyoto',startDate:'2028-01-01',endDate:'2028-01-09'},sections:[],nextCursor:null,pageCursor:0};
 try{
  await act(async()=>{renderer=create(React.createElement(Status,{state}));});
  const title=()=>renderer.root.findByProps({className:'destination-loading__postcard'}).findByType('h3').children.join('');
  const first=title();await act(async()=>renderer.root.findAllByType('button').find(node=>node.children.join('')==='Next note').props.onClick());const next=title();assert.notEqual(first,next);
  for(const patch of [{plan:{...state.plan,status:'paused'}},{needsCheck:true},{error:'unconfirmed'}]){
   await act(async()=>renderer.update(React.createElement(Status,{state:{...state,...patch}})));assert.equal(title(),next);assert.ok(renderer.root.findAllByType('div').some(node=>node.props.hidden===true));
   await act(async()=>renderer.update(React.createElement(Status,{state})));assert.equal(title(),next);
  }
 }finally{if(renderer)await act(async()=>renderer.unmount());}
});
