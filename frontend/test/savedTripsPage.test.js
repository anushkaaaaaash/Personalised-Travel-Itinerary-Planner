import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { createAdaptiveFixture } from '../tools/adaptiveVisualFixtures.mjs';
import { preferences } from './shareFixture.js';

const id='32345678-1234-1234-1234-123456789abc';
const record={id,title:'A saved Kyoto trip',version:1,createdAt:'2028-01-01T00:00:00Z',updatedAt:'2028-01-02T00:00:00Z'};
const session=owner=>({user:{id:owner},access_token:'SYNTHETIC_ONLY',expires_at:Date.now()/1000+3600});
async function harness(run){
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;const originalFetch=globalThis.fetch;
  const {setSession}=await server.ssrLoadModule('/src/services/session.js');
  try{const {default:Page}=await server.ssrLoadModule('/src/pages/SavedTripsPage.jsx');const {MemoryRouter}=await server.ssrLoadModule('react-router-dom');setSession(session('owner-a'));
    await run({setSession,mount:async()=>act(async()=>{renderer=create(React.createElement(MemoryRouter,null,React.createElement(Page)));}),root:()=>renderer.root,text:()=>JSON.stringify(renderer.toJSON())});
  }finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);globalThis.fetch=originalFetch;await server.close();}
}

test('saved collection lists verified IDs with bounded explicit pagination and only GET requests',()=>harness(async env=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,method:options.method});const offset=Number(new URL(url,'https://example.test').searchParams.get('offset'));return{status:200,json:async()=>({items:[{...record,title:offset?'Another saved trip':record.title}],offset,hasMore:offset===0})};};
  await env.mount();assert.match(env.text(),/A saved Kyoto trip/);assert.match(env.text(),/Unfinished 24-hour plans are separate/);assert.doesNotMatch(env.text(),/Load for editing|Delete trip|Save this trip/);
  assert.ok(env.root().findAllByType('a').some(link=>link.props.href===`/itineraries/${id}`));
  const next=env.root().findAllByType('button').find(button=>button.children.join('')==='Next saved page');await act(async()=>{next.props.onClick();next.props.onClick();});
  assert.deepEqual(calls.map(call=>call.method),['GET','GET']);assert.match(calls[1].url,/offset=20$/);assert.match(env.text(),/Another saved trip/);assert.equal(env.root().findAllByType('button').find(button=>button.children.join('')==='Next saved page').props.disabled,true);
}));

test('owner change discards an in-flight saved list and never shows another account’s response',()=>harness(async env=>{
  let finish;globalThis.fetch=async()=>new Promise(resolve=>{finish=resolve;});await env.mount();assert.match(env.text(),/Loading saved trips/);
  await act(async()=>env.setSession(session('owner-b')));await act(async()=>finish({status:200,json:async()=>({items:[record],offset:0,hasMore:false})}));
  assert.doesNotMatch(env.text(),/A saved Kyoto trip/);assert.match(env.text(),/Sign in to browse/);
}));

test('unverified list identities never become saved-trip navigation links',()=>harness(async env=>{
  globalThis.fetch=async()=>({status:200,json:async()=>({items:[{...record,id:'javascript:private'}],offset:0,hasMore:false})});await env.mount();
  assert.equal(env.root().findAllByType('a').some(link=>link.props.href?.startsWith('/itineraries/')),false);assert.match(env.text(),/could not be verified/);
}));

test('saved collection route is sign-in gated and header navigation is available independently of planning',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  try{
    const {default:Routes}=await server.ssrLoadModule('/src/components/PlannerRoutes.jsx');
    const {MemoryRouter}=await server.ssrLoadModule('react-router-dom');
    const html=renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/saved-trips']},React.createElement(Routes,{signedIn:false})));assert.match(html,/Sign in to browse your saved trips/);assert.doesNotMatch(html,/Next saved page/);
    const {default:Header}=await server.ssrLoadModule('/src/components/SiteHeader.jsx');const signed=renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(Header,{showSavedTrips:true})));assert.match(signed,/href="\/saved-trips"/);
  }finally{await server.close();}
});

test('saved collection and back navigation retain an unfinished plan identity without cancelling or creating',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;const originalFetch=globalThis.fetch,originalStorage=globalThis.sessionStorage;
  const {setSession}=await server.ssrLoadModule('/src/services/session.js');
  try{
    const fixture=createAdaptiveFixture();fixture.phase='constraint';fixture.preferences={...preferences,destination:'France',startDate:'2028-01-01',endDate:'2028-02-15'};fixture.requestId='22345678-1234-1234-1234-123456789abc';const body=fixture.snapshot();
    const key='travel.adaptive-plan.v1',stored=JSON.stringify({owner:'owner-a',requestId:body.plan.requestId,planId:body.plan.id}),values=new Map([[key,stored]]);globalThis.sessionStorage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
    const requests=[];globalThis.fetch=async(url,options)=>{requests.push({url,method:options.method});if(url.startsWith(`/api/adaptive-plans/${body.plan.id}`))return{status:200,json:async()=>body};if(url==='/api/saved-itineraries?offset=0')return{status:200,json:async()=>({items:[record],offset:0,hasMore:false})};assert.fail(`Unexpected request ${url}`);};
    const {default:Routes}=await server.ssrLoadModule('/src/components/PlannerRoutes.jsx');const {MemoryRouter,useNavigate}=await server.ssrLoadModule('react-router-dom');let navigate;function Probe(){navigate=useNavigate();return null;}
    setSession(session('owner-a'));await act(async()=>{renderer=create(React.createElement(MemoryRouter,null,React.createElement(Probe),React.createElement(Routes,{signedIn:true,adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12}})));});
    assert.match(JSON.stringify(renderer.toJSON()),/Suggestions for this part/);await act(async()=>navigate('/saved-trips'));assert.match(JSON.stringify(renderer.toJSON()),/A saved Kyoto trip/);assert.equal(values.get(key),stored);
    await act(async()=>navigate('/'));assert.match(JSON.stringify(renderer.toJSON()),/Suggestions for this part/);assert.equal(values.get(key),stored);assert.ok(requests.every(request=>request.method==='GET'));assert.equal(requests.filter(request=>request.url.startsWith('/api/adaptive-plans/')).length,2);
  }finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);globalThis.fetch=originalFetch;globalThis.sessionStorage=originalStorage;await server.close();}
});
