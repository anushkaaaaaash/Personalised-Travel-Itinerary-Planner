import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';
const jobId='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const config={enabled:true,mode:'production',ownership_enabled:true,saved_only:true};
const owner=id=>({user:{id,email:`${id}@example.test`},access_token:'TEST_TOKEN',expires_at:Date.now()/1000+3600});
const response=body=>({status:200,json:async()=>body});
async function mounted(fetchImpl,run){
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});const original=globalThis.fetch;let renderer;
 const {setSession}=await server.ssrLoadModule('/src/services/session.js');
 try{globalThis.fetch=fetchImpl;setSession(owner('owner-a'));
  const {default:Auth}=await server.ssrLoadModule('/src/components/AuthBoundary.jsx');const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');const {MemoryRouter}=await server.ssrLoadModule('react-router-dom');
  await act(async()=>{renderer=create(React.createElement(MemoryRouter,null,React.createElement(Auth)));});
  await run({setSession,renderer,Page,text:()=>JSON.stringify(renderer.toJSON()),prepare:async()=>{const props=()=>renderer.root.findByType(Form).props;await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:preferences[name]}});});await act(async()=>props().onSubmit({preventDefault(){}}));await act(async()=>props().onSubmit({preventDefault(){}}));return props;}});
 }finally{if(renderer)await act(async()=>renderer.unmount());setSession(null);globalThis.fetch=original;await server.close();}
}
for(const [label,capability,expected] of [['old backend',undefined,false],['unready or unhealthy cleanup',false,false],['ready backend',true,true],['malformed truthy field','true',false]]){
 test(`${label} capability selects only the authorized initial planning path`,async()=>{
  const calls=[];await mounted(async(url,options)=>{calls.push(url);if(url==='/api/auth/config')return response({...config,...(capability===undefined?{}:{planning_jobs_enabled:capability})});if(url==='/api/itineraries/generate')return response(plan());assert.equal(url,'/api/planning-jobs');const requestId=JSON.parse(options.body).requestId;return response({id:jobId,requestId,status:'queued',result:null,createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+3600000).toISOString()});},async env=>{assert.equal(env.renderer.root.findByType(env.Page).props.jobsEnabled,expected);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.deepEqual(calls,['/api/auth/config',expected?'/api/planning-jobs':'/api/itineraries/generate']);});
 });
}
test('config fetch failure exposes no planner and cannot opt into jobs',async()=>{const calls=[];await mounted(async url=>{calls.push(url);throw Error('offline');},async env=>{assert.equal(env.renderer.root.findAllByType(env.Page).length,0);assert.match(env.text(),/Retry connection/);assert.deepEqual(calls,['/api/auth/config']);});});
test('logout and owner changes remount capability-enabled planner and ignore old job responses',async()=>{
 let resolve,requestId;const calls=[];await mounted(async(url,options)=>{calls.push(url);if(url==='/api/auth/config')return response({...config,planning_jobs_enabled:true});assert.equal(url,'/api/planning-jobs');requestId=JSON.parse(options.body).requestId;return new Promise(done=>{resolve=done;});},async env=>{const props=await env.prepare();await act(async()=>props().onGenerateItinerary());await act(async()=>env.setSession(null));assert.equal(env.renderer.root.findAllByType(env.Page).length,0);await act(async()=>env.setSession(owner('owner-b')));assert.equal(env.renderer.root.findByType(env.Page).props.jobsEnabled,true);await act(async()=>resolve(response({id:jobId,requestId,status:'succeeded',result:plan(),createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+3600000).toISOString()})));assert.doesNotMatch(env.text(),/Make the days your own/);assert.deepEqual(calls,['/api/auth/config','/api/planning-jobs']);});
});
