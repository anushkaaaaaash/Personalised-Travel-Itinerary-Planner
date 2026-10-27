import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act, create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {destinationCards} from '../src/data/destinationFacts.js';
import {AI_REQUEST_TIMEOUT_MS} from '../src/services/aiRequest.js';
import {generateItinerary, refineItinerary} from '../src/services/itineraries.js';
import {getRecommendations} from '../src/services/recommendations.js';
import {preferences, plan} from './shareFixture.js';

test('selected destinations resolve exact curated aliases, unknown and inherited keys get honestly labeled tips',()=>{
  for(const name of ['Kyoto', '  KYOTO , Japan ', 'Goa, India', 'Paris, France', 'Tokyo', 'Rome, Italy', 'London, UK']) {
    const cards=destinationCards(name);assert.equal(cards[0].label,'Destination fact');assert.match(cards[0].source,/^https:\/\//);
  }
  for(const name of ['', 'constructor', '__proto__', 'toString', 'Paris, Texas', 'Kyoto and Goa', 'Lyon, France', 'Osaka, Japan', 'Somewhere new']) {
    for(const card of destinationCards(name)){assert.equal(card.label,'General travel tip');assert.equal(card.source,undefined);}
  }
});

test('every AI request uses the shared 210 second deadline and clears its timer on error',async()=>{
  assert.equal(AI_REQUEST_TIMEOUT_MS,210000);
  const set=globalThis.setTimeout,clear=globalThis.clearTimeout;let deadlines=[],cleared=[];
  globalThis.setTimeout=(_fn,ms)=>{deadlines.push(ms);return deadlines.length;};
  globalThis.clearTimeout=id=>cleared.push(id);
  const options={fetchImpl:async()=>({status:504,json:async()=>({})})};
  try{
    await assert.rejects(generateItinerary(preferences,options));
    await assert.rejects(refineItinerary({preferences,previous:plan(),feedback:'More rest'},options));
    await assert.rejects(getRecommendations(preferences,options));
    assert.deepEqual(deadlines,[210000,210000,210000]);assert.deepEqual(cleared,[1,2,3]);
  }finally{globalThis.setTimeout=set;globalThis.clearTimeout=clear;}
});

test('cards rotate without requests; pause, destination change, manual next, cancel and unmount clean up',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const set=globalThis.setInterval,clear=globalThis.clearInterval,fetch=globalThis.fetch;let renderer,tick,nextId=0,cancelled=0;const active=new Set();
  try {
    const {default:Loading}=await server.ssrLoadModule('/src/components/DestinationLoading.jsx');
    globalThis.fetch=()=>{throw Error('Loading must not fetch');};
    globalThis.setInterval=(fn,ms)=>{assert.equal(ms,9000);tick=fn;active.add(++nextId);return nextId;};
    globalThis.clearInterval=id=>active.delete(id);
    const props={destination:'Kyoto',onCancel:()=>cancelled++};
    await act(async()=>{renderer=create(React.createElement(Loading,props));});
    const text=()=>JSON.stringify(renderer.toJSON());
    assert.match(text(),/Kyoto/);assert.match(text(),/few minutes/);assert.equal(active.size,1);
    assert.equal(renderer.root.findAll(n=>n.props.role==='progressbar').length,0);
    await act(async()=>tick());assert.match(text(),/Heritage beyond one city/);
    await act(async()=>renderer.root.findByProps({'aria-label':'Pause rotating cards and animation'}).props.onClick());assert.equal(active.size,0);
    await act(async()=>renderer.update(React.createElement(Loading,{...props,destination:'Unknown place'})));assert.match(text(),/General travel tip/);assert.doesNotMatch(text(),/Destination fact/);
    await act(async()=>renderer.root.findAllByType('button').find(n=>n.children.join('')==='Next tip').props.onClick());assert.match(text(),/Check before you set off/);
    await act(async()=>renderer.root.findByProps({'aria-label':'Resume rotating cards and animation'}).props.onClick());assert.equal(active.size,1);
    await act(async()=>renderer.root.findAllByType('button').find(n=>n.children.join('')==='Stop waiting').props.onClick());assert.equal(cancelled,1);
    await act(async()=>renderer.unmount());renderer=null;assert.equal(active.size,0);
  }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.setInterval=set;globalThis.clearInterval=clear;globalThis.fetch=fetch;await server.close();}
});

test('reduced-motion mode does not auto-rotate and keeps manual cards available',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',plugins:[{name:'test-reduced-motion',enforce:'pre',transform(code,id){if(id.endsWith('/DestinationLoading.jsx'))return code.replace("import { useReducedMotion } from 'framer-motion';",'const useReducedMotion = () => true;');}}],server:{middlewareMode:true,watch:null,hmr:false}});
  const set=globalThis.setInterval;let renderer;
  try{
    const {default:Loading}=await server.ssrLoadModule('/src/components/DestinationLoading.jsx');
    globalThis.setInterval=()=>{throw Error('Reduced motion must not auto-rotate');};
    await act(async()=>{renderer=create(React.createElement(Loading,{destination:'Kyoto'}));});
    assert.equal(renderer.root.findAll(n=>n.props['aria-label']==='Pause rotating cards and animation').length,0);
    await act(async()=>renderer.root.findAllByType('button').find(n=>n.children.join('')==='Next fact').props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()),/Heritage beyond one city/);
  }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.setInterval=set;await server.close();}
});
