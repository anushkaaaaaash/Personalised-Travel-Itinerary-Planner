import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
const text=renderer=>JSON.stringify(renderer.toJSON());

test('confirmation presentation distinguishes checking, verified, invalid and connection failure',async()=>{
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer,continued=0;
 try{
  const {default:Confirmation}=await server.ssrLoadModule('/src/components/EmailConfirmation.jsx');
  const element=(status,signedIn=false)=>React.createElement(Confirmation,{status,signedIn,onContinue:()=>continued++});
  await act(async()=>{renderer=create(element('checking'));});
  assert.match(text(renderer),/Checking your confirmation/);assert.doesNotMatch(text(renderer),/Email confirmed/);assert.equal(renderer.root.findAllByType('button').length,0);
  await act(async()=>renderer.update(element('verified')));assert.match(text(renderer),/Email confirmed/);
  await act(async()=>renderer.root.findByType('button').props.onClick());assert.equal(continued,1);
  await act(async()=>renderer.update(element('unverified')));assert.match(text(renderer),/may be expired, already used, or incomplete/);assert.doesNotMatch(text(renderer),/Email confirmed/);
  await act(async()=>renderer.update(element('unavailable')));assert.match(text(renderer),/connection may have been interrupted/i);assert.doesNotMatch(text(renderer),/Email confirmed/);
  await act(async()=>renderer.update(element('verified',true)));assert.match(text(renderer),/Continue to your travel space/);
 }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('verified callback stays visible until explicit continue, then returns to the sign-in form',async()=>{
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',plugins:[{name:'confirmation-test',enforce:'pre',transform(code,id){if(id.endsWith('/AuthBoundary.jsx'))return code.replace("import { getConfirmationCallback } from '../services/confirmationCallback.js';",'const getConfirmationCallback = () => globalThis.__confirmationTestPromise;');}}],server:{middlewareMode:true,watch:null,hmr:false}});
 const priorFetch=globalThis.fetch;let renderer,finish;
 try{
  globalThis.__confirmationTestPromise=new Promise(resolve=>{finish=resolve;});
  globalThis.fetch=async url=>{assert.equal(url,'/api/auth/config');return {status:200,json:async()=>({enabled:true,mode:'production',ownership_enabled:true})};};
  const {default:Boundary}=await server.ssrLoadModule('/src/components/AuthBoundary.jsx');
  await act(async()=>{renderer=create(React.createElement(React.StrictMode,null,React.createElement(Boundary)));});
  assert.match(text(renderer),/Checking your confirmation/);assert.equal(renderer.root.findAllByType('input').length,0);
  await act(async()=>finish('verified'));assert.match(text(renderer),/Email confirmed/);assert.equal(renderer.root.findAllByType('input').length,0);
  await act(async()=>renderer.root.findByType('button').props.onClick());
  assert.doesNotMatch(text(renderer),/Email confirmed/);assert.equal(renderer.root.findAllByProps({type:'email'}).length,1);assert.equal(renderer.root.findAllByProps({type:'password'}).length,1);
 }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.fetch=priorFetch;delete globalThis.__confirmationTestPromise;await server.close();}
});
