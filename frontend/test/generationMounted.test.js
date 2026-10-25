import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';

test('mounted day-plan flow shows progress, valid results and safe failures without duplicate calls or saves',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const original=globalThis.fetch;let renderer,finish;const calls=[];
  try {
    globalThis.fetch=async(url,options)=>{
      assert.equal(url,'/api/itineraries/generate','No auth, save, or other external request is permitted');
      assert.equal(options.method,'POST');calls.push(JSON.parse(options.body));
      return new Promise(resolve=>{finish=resolve;});
    };
    const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    await act(async()=>{renderer=create(React.createElement(Page,{legacyEnabled:false,signedIn:false}));});
    const props=()=>renderer.root.findByType(Form).props;
    const text=()=>JSON.stringify(renderer.toJSON());
    await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:preferences[name]}});});
    await act(async()=>props().onSubmit({preventDefault(){}}));await act(async()=>props().onSubmit({preventDefault(){}}));
    assert.equal(props().step,2);
    const start=async()=>{const count=calls.length;await act(async()=>{props().onGenerateItinerary();props().onGenerateItinerary();});assert.equal(calls.length,count+1);assert.equal(props().itineraryLoading,true);assert.match(text(),/Generating and validating your itinerary/);};
    await start();
    await act(async()=>{finish({status:200,json:async()=>plan()});});
    assert.equal(props().itineraryLoading,false);assert.match(text(),/your day-by-day plan/);assert.match(text(),/Verify all details/);
    for(const [status,body,pattern] of [
      [502,{error:{code:'AI_PROVIDER_FAILED',message:'PRIVATE_DETAIL'}},/provider could not complete/],
      [429,{error:{code:'AI_RATE_LIMITED',message:'PRIVATE_DETAIL'}},/rate limit was reached/],
      [502,{error:{code:'AI_OUTPUT_TRUNCATED'}},/cut off at its output limit/],
      [200,{...plan(),warnings:[]},/failed browser-side validation/],
    ]) {
      await start();const count=calls.length;
      await act(async()=>{finish({status,json:async()=>body});});
      assert.equal(props().itineraryLoading,false);assert.match(text(),pattern);assert.doesNotMatch(text(),/PRIVATE_DETAIL/);
      await act(async()=>{await Promise.resolve();});assert.equal(calls.length,count);
    }
  }finally {
    if(renderer)await act(async()=>renderer.unmount());
    globalThis.fetch=original;await server.close();
  }
});
