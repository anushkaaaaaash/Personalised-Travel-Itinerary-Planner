import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {SAMPLE_TRIPS,samplePreferences} from '../src/data/sampleTrips.js';
import {validateTripPreferences} from '../../shared/tripPreferences.mjs';

test('three public examples are independent defaults with no invented user dates or quoted prices',()=>{
 assert.deepEqual(SAMPLE_TRIPS.map(x=>x.id),['kyoto','goa','paris']);
 for(const item of SAMPLE_TRIPS){const a=samplePreferences(item.id),b=samplePreferences(item.id);assert.equal(a.destination,item.destination);assert.equal(a.startDate,'');assert.equal(a.endDate,'');assert.equal(item.days.length,3);a.interests.push('shopping');assert.notDeepEqual(a.interests,b.interests);assert.equal(validateTripPreferences({...b,startDate:'2028-01-01',endDate:'2028-01-03'}).valid,true);assert.match(item.source,/^https:\/\//);}
});

function visible(node){if(typeof node==='string')return node;if(!node)return '';if(Array.isArray(node))return node.map(visible).join('');return visible(node.children);}
async function harness(run){
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});const original=globalThis.fetch;let renderer;
 try{
  const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx'),{default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx'),{default:Welcome}=await server.ssrLoadModule('/src/components/BrandWelcome.jsx'),{default:Discovery}=await server.ssrLoadModule('/src/components/DestinationDiscovery.jsx'),{default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
  const {default:Auth}=await server.ssrLoadModule('/src/components/AuthBoundary.jsx'),{MemoryRouter}=await server.ssrLoadModule('react-router-dom');
  const session=await server.ssrLoadModule('/src/services/session.js');globalThis.fetch=()=>assert.fail('Examples and restart must not generate requests');
  const env={Page,Welcome,Form,session,Status,Auth,MemoryRouter,mount:async(Component,props={})=>act(async()=>{renderer=create(React.createElement(Component,props));}),root:()=>renderer.root,text:()=>visible(renderer.toJSON()),form:()=>renderer.root.findByType(Form).props,select:async id=>act(async()=>renderer.root.findByType(Discovery).props.onSelect(id)),click:async label=>act(async()=>{const button=renderer.root.findAllByType('button').find(n=>n.children.join('')===label);assert.ok(button,label);assert.notEqual(button.props.disabled,true,label+' enabled');await button.props.onClick();})};
  await run(env);
 }finally{if(renderer)await act(async()=>renderer.unmount());const session=await server.ssrLoadModule('/src/services/session.js');session.setSession(null);globalThis.fetch=original;await server.close();}
}

test('signed-out homepage gives instant sample and explicit sign-in handoff without generation',()=>harness(async e=>{
 let selected;await e.mount(e.Welcome,{onUseSample:id=>selected=id});const buttons=e.root().findAll(n=>n.type==='button'&&n.props['aria-pressed']!==undefined);assert.equal(buttons.length,3);
 await act(async()=>buttons[2].props.onClick());assert.match(e.text(),/prewritten sample/);assert.match(e.text(),/Day 01/);assert.match(e.text(),/not your travel dates/);assert.match(e.text(),/Louvre/);await e.click('Use this example');assert.equal(selected,'paris');
}));

test('city selection preloads editable preferences and sample, protects existing draft, dates stay required',()=>harness(async e=>{
 await e.mount(e.Page);await e.select('kyoto');assert.equal(e.form().form.destination,'Kyoto, Japan');assert.equal(e.form().form.startDate,'');assert.equal(e.form().form.currency,'USD');assert.match(e.text(),/prewritten sample/);
 await e.click('Adjust preferences');assert.equal(e.form().step,1);await e.click('Review my settings');assert.equal(e.form().step,0);assert.ok(e.form().errors.startDate);
 await e.select('goa');assert.equal(e.form().form.destination,'Kyoto, Japan');await e.click('Keep my details');assert.equal(e.form().form.destination,'Kyoto, Japan');
 await e.select('goa');await e.click('Load example settings');assert.equal(e.form().form.destination,'Goa, India');assert.equal(e.form().form.currency,'INR');assert.match(e.text(),/Panaji/);
}));

test('confirmed start over resets to first step; dismiss keeps draft and never starts work',()=>harness(async e=>{
 await e.mount(e.Page,{initialSampleId:'paris'});await e.click('Adjust preferences');await e.click('Start over');await e.click('Keep my trip');assert.equal(e.form().step,1);assert.equal(e.form().form.destination,'Paris, France');
 await e.click('Start over');await e.click('Yes, start over');assert.equal(e.form().step,0);assert.equal(e.form().form.destination,'');assert.equal(e.form().form.startDate,'');assert.doesNotMatch(e.text(),/prewritten sample/);
}));

for(const finalStatus of ['cancelled','completed'])test(`restart waits for confirmed ${finalStatus} and preserves ambiguous identity without automatic replacement`,()=>harness(async e=>{
 e.session.setSession({user:{id:'example-owner'},access_token:'TEST_ONLY',expires_at:Date.now()/1000+3600});
 const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};let starts=0,cancels=0,checks=0;
 const id='11111111-1111-4111-8111-111111111111';let body;
 const client={start:async(preferences,requestId)=>{starts++;body={preferences,plan:{id,requestId,status:'active',totalDays:3,completedDays:0,remainingCreates:11,runAllowance:12,spentCents:0,totalBudgetCents:90000,expiresAt:'2029-01-01T00:00:00Z',activeSection:null},sections:[],nextCursor:null};return body;},cancel:async()=>{cancels++;throw Error('lost response');},get:async()=>{checks++;return {...body,plan:{...body.plan,status:finalStatus}};}};
 await e.mount(e.Page,{initialSampleId:'kyoto',signedIn:true,adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12},adaptiveClient:client,adaptiveStorage:storage,adaptivePollMs:600000});
 await act(async()=>{e.form().onChange({target:{name:'startDate',value:'2028-01-01'}});e.form().onChange({target:{name:'endDate',value:'2028-01-03'}});});
 await act(async()=>e.form().onSubmit({preventDefault(){}}));await act(async()=>e.form().onSubmit({preventDefault(){}}));await act(async()=>e.form().onGenerateItinerary());
 await e.click('Start over');await e.click('Yes, start over');assert.equal(starts,1);assert.equal(cancels,1);assert.equal(values.size,1);assert.equal(e.root().findByType(e.Status).props.state.needsCheck,true);assert.match(e.text(),/Waiting for confirmation/);
 await act(async()=>e.root().findByType(e.Status).props.onCheck());assert.equal(checks,1);assert.equal(starts,1);assert.equal(cancels,1);assert.equal(e.form().step,0);assert.equal(e.form().form.destination,'');assert.equal(values.size,0);if(finalStatus==='completed')assert.match(e.text(),/Return to the previous retained trip/);
}));


test('request-only unknown start cannot be cleared or cancelled by Start over',()=>harness(async e=>{
 e.session.setSession({user:{id:'example-owner'},access_token:'TEST_ONLY',expires_at:Date.now()/1000+3600});const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};let starts=0,cancels=0;
 await e.mount(e.Page,{initialSampleId:'kyoto',signedIn:true,adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12},adaptiveStorage:storage,adaptiveClient:{start:async()=>{starts++;throw Error('lost start');},cancel:async()=>{cancels++;assert.fail('must not cancel unknown identity');}}});
 await act(async()=>{e.form().onChange({target:{name:'startDate',value:'2028-01-01'}});e.form().onChange({target:{name:'endDate',value:'2028-01-03'}});});await act(async()=>e.form().onSubmit({preventDefault(){}}));await act(async()=>e.form().onSubmit({preventDefault(){}}));await act(async()=>e.form().onGenerateItinerary());
 const retained=[...values.values()][0];await e.click('Start over');await e.click('Yes, start over');assert.match(e.text(),/Check the current planning status first/);assert.equal(starts,1);assert.equal(cancels,0);assert.equal([...values.values()][0],retained);assert.equal(e.root().findAllByType(e.Form).length,0);
}));

test('actual auth boundary carries only selected sample into planner after explicit sign-in',()=>harness(async e=>{
 e.session.setSession(null);const calls=[];globalThis.fetch=async(url,options)=>{calls.push([url,options?.method]);if(url==='/api/auth/config')return{status:200,json:async()=>({enabled:true,mode:'production',ownership_enabled:true,saved_only:true})};assert.equal(url,'/api/auth/login');return{status:200,json:async()=>({session:{access_token:'TEST_ONLY',token_type:'bearer',expires_at:Date.now()/1000+3600},user:{id:'example-owner'}})};};
 await e.mount(e.MemoryRouter,{children:React.createElement(e.Auth)});const welcome=e.root().findByType(e.Welcome);await act(async()=>welcome.props.onUseSample('goa'));assert.match(e.text(),/Sign in below/);assert.equal(calls.length,1);
 await act(async()=>{e.root().findByProps({type:'email'}).props.onChange({target:{value:'example@example.test'}});e.root().findByProps({type:'password'}).props.onChange({target:{value:'SYNTHETIC_PASSWORD'}});});await act(async()=>e.root().findByProps({className:'account-form'}).props.onSubmit({preventDefault(){}}));
 assert.equal(e.form().form.destination,'Goa, India');assert.equal(e.form().form.startDate,'');assert.match(e.text(),/prewritten sample/);assert.deepEqual(calls.map(x=>x[0]),['/api/auth/config','/api/auth/login']);
}));
