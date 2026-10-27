import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { tripFailureRecovery } from '../src/utils/travelMessages.js';
import { preferences } from './shareFixture.js';

test('service failures explain the known category without blaming or changing trip preferences',()=>{
  const cases=[
    ['TRANSPORT_TIMEOUT','Planning took too long.'],
    ['TRANSPORT_UNAVAILABLE','We couldn’t reach the planner.'],
    ['SERVICE_UNAVAILABLE','Planning is temporarily unavailable.'],
    ['AI_RATE_LIMITED','The planner is busy.'],
    ['AI_PROVIDER_FAILED','The planning service couldn’t finish.'],
    ['AI_OUTPUT_TRUNCATED','The returned plan was incomplete.'],
    ['UNREADABLE_RESPONSE','The returned plan didn’t pass its checks.'],
  ];
  for(const [code,title] of cases){
    const recovery=tripFailureRecovery({code,fields:['budget','endDate'],message:'PRIVATE_SERVER_MESSAGE'});
    assert.equal(recovery.title,title);assert.equal(recovery.retryable,true);assert.equal(recovery.editStep,null);assert.deepEqual(recovery.recommendations,[]);
    assert.doesNotMatch(JSON.stringify(recovery),/PRIVATE_SERVER_MESSAGE|increase your budget|shorten your trip/i);
  }
});

test('rejected generated budgets, dates and schedules do not invent user preference corrections',()=>{
  for(const reason of ['FORMAT_SCHEMA','PREFERENCE_MISMATCH','DATE_COVERAGE','PACE','BUDGET','TIMELINE','VIBE_MISMATCH','FIXED_COMMITMENT']){
    const recovery=tripFailureRecovery({code:'AI_INVALID_RESPONSE',reason,fields:['budget']});
    assert.match(recovery.message,/We did not accept it/);assert.match(recovery.message,/same details/);
    assert.equal(recovery.editStep,null);assert.deepEqual(recovery.recommendations,[]);
  }
  const unknown=tripFailureRecovery({code:'PRIVATE_CODE',reason:'PRIVATE_REASON',fields:['budget']});
  assert.equal(unknown.code,'REQUEST_FAILED');assert.deepEqual(unknown.recommendations,[]);assert.doesNotMatch(JSON.stringify(unknown),/PRIVATE_/);
});

test('real validation advice whitelists fields and chooses the earliest relevant edit step',()=>{
  const recovery=tripFailureRecovery({code:'VALIDATION_ERROR',fields:['budget','endDate','budget','__proto__','constructor','PRIVATE_FIELD',{},null]});
  assert.equal(recovery.retryable,false);assert.equal(recovery.editStep,0);
  assert.deepEqual(recovery.recommendations.map(item=>item.field),['budget','endDate']);
  assert.match(recovery.recommendations[0].suggestion,/greater than zero/);
  assert.match(recovery.recommendations[1].suggestion,/on or after your start date/);
  assert.equal(tripFailureRecovery({code:'VALIDATION_ERROR',fields:['travelers','travelPace']}).editStep,1);
  assert.deepEqual(tripFailureRecovery({code:'VALIDATION_ERROR',fields:['PRIVATE_FIELD']}).recommendations,[]);
  assert.equal(tripFailureRecovery({code:'REFINEMENT_PACE_CONFLICT'}).editStep,1);
});

test('authentication and request-capacity limits do not encourage repeating the same failed request',()=>{
  for(const code of ['AUTH_REQUIRED','REQUEST_TOO_LARGE','ITINERARY_DURATION_UNSUPPORTED','REFINEMENT_FIXED_CONFLICT']){
    const recovery=tripFailureRecovery({code});assert.equal(recovery.retryable,false);assert.deepEqual(recovery.recommendations,[]);
  }
});

test('recommendations travel to the edit callback, remain attached to fields and preserve every entered value',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  let renderer;
  try {
    const {default:Generated}=await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    let received,focusCount=0,dismissCount=0;
    await act(async()=>{renderer=create(React.createElement(Generated,{error:'PRIVATE_SERVER_MESSAGE',errorCode:'VALIDATION_ERROR',errorFields:['budget'],onRetry(){assert.fail('Validation must not retry unchanged');},onEditPreferences:value=>{received=value;}}));});
    const button=renderer.root.findByType('button');assert.equal(button.children.join(''),'Review recommended changes');
    await act(async()=>button.props.onClick());assert.equal(received.editStep,1);assert.equal(received.recommendations[0].field,'budget');
    await act(async()=>renderer.unmount());renderer=null;
    const form={...preferences,budget:2500};const original=structuredClone(form);
    await act(async()=>{renderer=create(React.createElement(Form,{form,step:1,recovery:received,onChange(){},onDismissRecovery:()=>{dismissCount++;}}),{createNodeMock:node=>node.props?.className==='planning-recovery'?{focus(){focusCount++;}}:null});});
    const budget=renderer.root.findByProps({name:'budget'});
    assert.equal(budget.props.value,2500);assert.equal(budget.props['aria-invalid'],true);assert.equal(budget.props['aria-describedby'],'budget-recovery');
    assert.equal(renderer.root.findByProps({id:'budget-recovery'}).type,'small');assert.equal(focusCount,1);assert.deepEqual(form,original);
    const dismiss=renderer.root.findAllByType('button').find(node=>node.children.join('')==='Dismiss guidance');
    assert.equal(dismiss.props.type,'button');await act(async()=>dismiss.props.onClick());assert.equal(dismissCount,1);
    const service=tripFailureRecovery({code:'AI_PROVIDER_FAILED'});
    const html=renderToStaticMarkup(React.createElement(Form,{form,step:0,recovery:service,onChange(){}}));
    assert.match(html,/Why planning stopped/);assert.doesNotMatch(html,/Suggested adjustment|data-recommended="true"/);
    const invalid=renderToStaticMarkup(React.createElement(Generated,{error:'PRIVATE_MESSAGE',errorCode:'AI_INVALID_RESPONSE',errorReason:'BUDGET',onRetry(){},onEditPreferences(){}}));
    assert.match(invalid,/did not pass the checks against your total budget/);assert.doesNotMatch(invalid,/PRIVATE_MESSAGE|Suggested adjustment|Increase your budget/);
    const repeated=renderToStaticMarkup(React.createElement(Form,{form,step:1,recovery:{...received,recommendations:[{field:'budget',suggestion:'First budget suggestion',reason:'First reason'},{field:'budget',suggestion:'Second budget suggestion',reason:'Second reason'}]},onChange(){}}));
    assert.match(repeated,/First budget suggestion/);assert.match(repeated,/Second budget suggestion/);assert.match(repeated,/Second reason/);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});
