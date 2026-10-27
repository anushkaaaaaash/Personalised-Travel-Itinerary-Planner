import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';
async function harness(run){
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
 const original=globalThis.fetch;let renderer;const calls=[];
 try{
  const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');const {default:Saved}=await server.ssrLoadModule('/src/components/SavedItineraries.jsx');
  globalThis.fetch=async(url,options)=>{assert.equal(url,'/api/itineraries/generate');let finish;const pending=new Promise(resolve=>{finish=resolve;});calls.push({payload:JSON.parse(options.body),finish,signal:options.signal});return pending;};
  const props=()=>renderer.root.findByType(Form).props;
  const env={calls,props,text:()=>JSON.stringify(renderer.toJSON()),mount:async()=>act(async()=>{renderer=create(React.createElement(Page,{signedIn:true,jobsEnabled:false}));}),unmount:async()=>act(async()=>{renderer.unmount();renderer=null;}),change:async values=>act(async()=>{for(const [name,value] of Object.entries(values))props().onChange({target:{name,value}});}),next:async()=>act(async()=>props().onSubmit({preventDefault(){}})),start:async()=>act(async()=>props().onGenerateItinerary()),click:async label=>act(async()=>{const button=renderer.root.findAllByType('button').find(n=>n.children.join('').includes(label));assert.ok(button,label);button.props.onClick();}),load:async record=>act(async()=>renderer.root.findByType(Saved).props.onLoad(record)),finish:async(index,result)=>act(async()=>calls[index].finish({status:200,json:async()=>result}))};
  await env.mount();await run(env);
 }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.fetch=original;await server.close();}
}
test('reported 24-day synchronous trip stays on editable dates, then corrected trip submits once',()=>harness(async e=>{
 await e.change({...preferences,startDate:'2026-10-27',endDate:'2026-11-19'});await e.next();assert.equal(e.props().step,0);assert.match(e.text(),/24 days/);assert.equal(e.calls.length,0);assert.equal(e.props().form.endDate,'2026-11-19');
 await e.change({endDate:'2026-11-09'});await e.next();await e.next();assert.equal(e.props().step,2);await e.start();assert.equal(e.calls.length,1);assert.equal(e.calls[0].payload.endDate,'2026-11-09');await e.finish(0,{...plan(),status:'infeasible',days:[],estimatedTotalGroupCost:null,remainingBudget:null});
}));
test('restored long-trip Review is revalidated without a same-input retry loop or deleting saved data',()=>harness(async e=>{
 const record={preferences:{...preferences,startDate:'2026-10-27',endDate:'2026-11-19'},itinerary:plan()};const before=structuredClone(record);
 await e.load(record);await e.click('Trip preferences');assert.equal(e.props().step,2);await e.start();assert.equal(e.calls.length,0);assert.equal(e.props().step,0);assert.match(e.text(),/24 days/);assert.doesNotMatch(e.text(),/Your trip needs a little more time|Try again/);assert.deepEqual(record,before);
}));
test('new destination clears previous result, late cancelled response cannot overwrite fresh plan, reload starts clean',()=>harness(async e=>{
 await e.change(preferences);await e.next();await e.next();await e.start();await e.finish(0,plan());assert.match(e.text(),/Make the days your own/);
 await e.click('Trip preferences');await e.change({destination:'Paris'});assert.doesNotMatch(e.text(),/Return to your itinerary|Make the days your own/);await e.start();assert.equal(e.calls[1].payload.destination,'Paris');
 await e.click('Trip preferences');assert.equal(e.calls[1].signal.aborted,true);await e.change({destination:'Tokyo'});await e.start();
 await e.finish(1,{...plan(),destination:'Paris'});assert.doesNotMatch(e.text(),/Make the days your own/);
 await e.finish(2,{...plan(),destination:'Tokyo'});assert.match(e.text(),/Make the days your own/);assert.doesNotMatch(e.text(),/Paris|Kyoto/);
 await e.unmount();await e.mount();assert.equal(e.props().step,0);assert.equal(e.props().form.destination,'');assert.doesNotMatch(e.text(),/Make the days your own/);assert.equal(e.calls.length,3);
}));
