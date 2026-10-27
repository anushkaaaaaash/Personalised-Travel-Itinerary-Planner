import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {plan,preferences} from './shareFixture.js';
import {revisionBase} from './adaptiveRevisionFixture.js';
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
  await run({setSession,renderer,Page,text:()=>JSON.stringify(renderer.toJSON()),prepare:async(values=preferences)=>{const props=()=>renderer.root.findByType(Form).props;await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:values[name]}});});await act(async()=>props().onSubmit({preventDefault(){}}));await act(async()=>props().onSubmit({preventDefault(){}}));return props;}});
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
for(const capability of [true,false,'true',undefined]){
 test(`adaptive capability ${String(capability)} is exact-boolean gated through auth and routes`,async()=>{
  const calls=[];await mounted(async(url,options)=>{calls.push(url);if(url==='/api/auth/config')return response({...config,adaptive_planning_enabled:capability,adaptive_planning_policy:{sectionDays:3,maxSubmissionsPerRun:12}});if(url==='/api/adaptive-plans/current')return{status:404,json:async()=>({error:{code:'SECTION_CURRENT_NOT_FOUND'}})};if(url==='/api/itineraries/generate')return response(plan());assert.equal(url,'/api/adaptive-plans');const requestId=JSON.parse(options.body).requestId;return response({preferences,plan:{id:jobId,requestId,status:'paused',runAllowance:12,estimatedSections:1,completedDays:0,totalDays:1,remainingCreates:0,spentCents:0,totalBudgetCents:250000,pauseReason:'RESOURCE_ALLOWANCE_REACHED',expiresAt:new Date(Date.now()+3600000).toISOString(),activeSection:null},sections:[],nextCursor:null});},async env=>{assert.equal(env.renderer.root.findByType(env.Page).props.adaptiveEnabled,capability===true);const props=await env.prepare();await act(async()=>props().onGenerateItinerary());assert.deepEqual(calls,capability===true?['/api/auth/config','/api/adaptive-plans/current','/api/adaptive-plans']:['/api/auth/config','/api/itineraries/generate']);});
 });
}
for(const policy of [undefined,{}, {sectionDays:4,maxSubmissionsPerRun:12},{sectionDays:3,maxSubmissionsPerRun:13},{sectionDays:3,maxSubmissionsPerRun:'12'}]){
 test(`adaptive true with invalid policy ${JSON.stringify(policy)} fails closed`,async()=>{await mounted(async url=>{assert.equal(url,'/api/auth/config');return response({...config,adaptive_planning_enabled:true,adaptive_planning_policy:policy});},async env=>{assert.equal(env.renderer.root.findByType(env.Page).props.adaptiveEnabled,false);});});
}

for(const capability of [true,false,'true',undefined])test(`selected-day revision policy ${String(capability)} passes through actual authentication and routes only when valid`,async()=>{
 const base=revisionBase(),calls=[];const policy={sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,researchMode:'on_demand',maxWebSearchCalls:6,provisionalDayPreviews:true,responseDeadlineMinutes:8,...(capability===undefined?{}:{selectedDayRevisions:capability})};
 await mounted(async(url,options)=>{calls.push(url);if(url==='/api/auth/config')return response({...config,adaptive_planning_enabled:true,adaptive_planning_policy:policy});if(url==='/api/adaptive-plans/current')return{status:404,json:async()=>({error:{code:'SECTION_CURRENT_NOT_FOUND'}})};if(url==='/api/adaptive-plans'){const value=structuredClone(base);value.plan.requestId=JSON.parse(options.body).requestId;return response(value);}if(url.endsWith('/revisions/current'))return{status:404,json:async()=>({error:{code:'REVISION_NOT_FOUND'}})};throw Error(`Unexpected ${url}`);},async env=>{const page=env.renderer.root.findByType(env.Page);assert.equal(page.props.adaptiveEnabled,capability!=='true');if(capability==='true')return;assert.equal(page.props.adaptivePolicy.selectedDayRevisions,capability);const props=await env.prepare(base.preferences);await act(async()=>props().onGenerateItinerary());assert.equal(env.text().includes('Change one day'),capability===true);assert.equal(calls.some(url=>url.endsWith('/revisions/current')),capability===true);});
});
