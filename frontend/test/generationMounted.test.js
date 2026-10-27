import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';
test('focused journey handles repeated generation, cancellation, late responses and clean errors',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const original=globalThis.fetch;let renderer,finish;const calls=[];
  try {
    globalThis.fetch=async(url,options)=>{assert.equal(url,'/api/itineraries/generate');assert.equal(options.method,'POST');calls.push(JSON.parse(options.body));return new Promise(resolve=>{finish=resolve;});};
    const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    await act(async()=>{renderer=create(React.createElement(Page,{legacyEnabled:false,signedIn:false}));});
    const props=()=>renderer.root.findByType(Form).props;
    const text=()=>JSON.stringify(renderer.toJSON());
    const click=async label=>act(async()=>renderer.root.findAllByType('button').find(n=>n.children.join('').includes(label)).props.onClick());
    await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:preferences[name]}});});
    await act(async()=>props().onSubmit({preventDefault(){}}));await act(async()=>props().onSubmit({preventDefault(){}}));
    const start=async()=>{const count=calls.length;const handlers=props();await act(async()=>{handlers.onGenerateItinerary();handlers.onGenerateItinerary();});assert.equal(calls.length,count+1);assert.equal(renderer.root.findAllByType(Form).length,0);assert.match(text(),/Putting your days together/);assert.match(text(),new RegExp(preferences.destination));};
    await start();await act(async()=>finish({status:200,json:async()=>plan()}));assert.match(text(),/Make the days your own/);assert.match(text(),/Verify all details/);
    await click('Trip preferences');assert.equal(props().step,2);
    await start();const staleFinish=finish;await click('Stop waiting');assert.equal(props().step,2);
    await start();const freshFinish=finish;await act(async()=>staleFinish({status:200,json:async()=>plan()}));assert.match(text(),/Putting your days together/);
    await act(async()=>freshFinish({status:200,json:async()=>plan()}));assert.match(text(),/Make the days your own/);
    await click('Trip preferences');
    for(const [status,body] of [[502,{error:{code:'AI_PROVIDER_FAILED',message:'PRIVATE_DETAIL'}}],[429,{error:{code:'AI_RATE_LIMITED'}}],[200,{...plan(),warnings:[]}]]){
      await start();const count=calls.length;await act(async()=>finish({status,json:async()=>body}));assert.match(text(),/couldn’t finish this plan|planner is busy/);assert.doesNotMatch(text(),/PRIVATE_DETAIL|AI provider|not saved/);assert.equal(calls.length,count);await click('Trip preferences');
    }
    assert.equal(calls.length,6);
  }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.fetch=original;await server.close();}
});
