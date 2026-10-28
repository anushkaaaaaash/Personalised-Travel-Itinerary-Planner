import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {groundedPage,groundedPreferences} from './groundedPlanningFixture.js';
let server,Status,Form;
before(async()=>{server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});({default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx'));({default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx'));});
after(async()=>server?.close());
const state=body=>({...body,loading:false,needsCheck:false,resumable:true,pageCursor:0});
const policy={sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,maxWebSearchCalls:6,researchMode:'on_demand',provisionalDayPreviews:true,responseDeadlineMinutes:8};
test('research-enabled new-run continuation requires disclosure and confirmation before callback',async()=>{
  let renderer,continued=0;const body=groundedPage({status:'failed'});body.plan.pauseReason='RESEARCH_ALLOWANCE_REACHED';body.research.toolCallsReserved=6;
  const props={state:state(body),onContinue:()=>continued++,onCheck(){},onCancel(){}};
  try{await act(async()=>{renderer=create(React.createElement(Status,props));});const button=name=>renderer.root.findAllByType('button').find(node=>node.children.join('')===name);
    assert.equal(continued,0);assert.equal(button('Yes, continue this trip'),undefined);await act(async()=>button('Continue with another run').props.onClick());assert.equal(continued,0);assert.match(JSON.stringify(renderer.toJSON()),/fresh allowance of up to 6/);assert.match(JSON.stringify(renderer.toJSON()),/Earlier usage is not refunded/);
    await act(async()=>button('Not now').props.onClick());assert.equal(button('Yes, continue this trip'),undefined);assert.equal(continued,0);
    await act(async()=>button('Continue with another run').props.onClick());await act(async()=>button('Yes, continue this trip').props.onClick());assert.equal(continued,1);
    await act(async()=>renderer.update(React.createElement(Status,{...props,state:{...props.state,loading:true}})));assert.equal(button('Yes, continue this trip').props.disabled,true);
    await act(async()=>renderer.update(React.createElement(Status,{...props,state:{...props.state,needsCheck:true}})));assert.equal(button('Yes, continue this trip'),undefined);assert.ok(button('Check planning status'));
  }finally{if(renderer)await act(async()=>renderer.unmount());}
});
test('known research failure has precise retry cost and never preference blame or an unknown-state retry',()=>{
  const props={state:state(groundedPage({status:'failed'})),onRetryResearch(){},onCheck(){},onCancel(){}};
  const html=renderToStaticMarkup(React.createElement(Status,props));assert.match(html,/Retry research/);assert.match(html,/one model request and reserves 2 search\/tool requests/);assert.doesNotMatch(html,/review changes|increase your budget|shorten/);
  for(const patch of [{needsCheck:true},{research:{...props.state.research,status:'submission_unknown'}},{plan:{...props.state.plan,remainingCreates:0}},{research:{...props.state.research,toolCallsReserved:6}}])assert.doesNotMatch(renderToStaticMarkup(React.createElement(Status,{...props,state:{...props.state,...patch}})),/>Retry research<|>Continue with another run</);
});
test('review states on-demand research, bounded allowances and real provisional semantics',()=>{
  const html=renderToStaticMarkup(React.createElement(Form,{form:groundedPreferences,step:2,adaptiveEnabled:true,adaptivePolicy:policy}));
  assert.match(html,/Research is used when needed/);assert.doesNotMatch(html,/one for research|first research request/);assert.match(html,/up to 12 planning requests/);assert.match(html,/6 searches/);assert.match(html,/up to 8 minutes while available/);assert.match(html,/labelled Draft until checked/);
  const longer=renderToStaticMarkup(React.createElement(Form,{form:groundedPreferences,step:2,adaptiveEnabled:true,adaptivePolicy:{...policy,responseDeadlineMinutes:30}}));assert.match(longer,/up to 30 minutes while available/);assert.match(longer,/service limits may stop it sooner/);assert.match(longer,/recoverable planning response may retry once using the current allowance/);
  const noPreview=renderToStaticMarkup(React.createElement(Form,{form:groundedPreferences,step:2,adaptiveEnabled:true,adaptivePolicy:{...policy,provisionalDayPreviews:false}}));assert.doesNotMatch(noPreview,/Early previews are labelled/);
  const legacy=renderToStaticMarkup(React.createElement(Form,{form:groundedPreferences,step:2,adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12}}));assert.match(legacy,/12 planning requests/);assert.doesNotMatch(legacy,/search\/tool requests|about 4 model requests|8-minute time limit/);
});

test('a research-capable run still discloses future tool allowance when no research was needed in the previous run',()=>{
 const body=groundedPage();body.research=null;body.draft=null;body.plan.status='paused';body.plan.pauseReason='RESOURCE_ALLOWANCE_REACHED';body.plan.remainingCreates=0;
 const html=renderToStaticMarkup(React.createElement(Status,{state:state(body),researchEnabled:true,onContinue(){}}));assert.match(html,/Continue with another run/);assert.doesNotMatch(html,/>Continue planning</);
});

test('deterministic public-query rejection offers only targeted place-field review, never a research retry',async()=>{
 const body=groundedPage({status:'failed'});body.research.errorCode='RESEARCH_QUERY_INVALID';let renderer,advice;
 try{await act(async()=>{renderer=create(React.createElement(Status,{state:state(body),onRetryResearch:()=>assert.fail('no retry'),onEditPreferences:value=>{advice=value;}}));});const text=JSON.stringify(renderer.toJSON());assert.match(text,/place-name format check/);assert.doesNotMatch(text,/Retry research|increase your budget|shorten your trip/);
 const button=renderer.root.findAllByType('button').find(node=>node.children.join('')==='Stop planning and review changes');await act(async()=>button.props.onClick());assert.equal(advice.editStep,0);assert.deepEqual(advice.recommendations.map(item=>item.field),['destination','departureCity']);assert.equal(advice.retryable,false);
 }finally{if(renderer)await act(async()=>renderer.unmount());}
});

test('bounded reconnect keeps completed-day context without prompting another retry mid-recovery',()=>{
 const body=groundedPage({status:'succeeded'}),value={...state(body),needsCheck:true,reconnecting:true,error:'unavailable',errorCode:'ADAPTIVE_UNAVAILABLE'};
 const html=renderToStaticMarkup(React.createElement(Status,{state:value,onCheck(){},onCancel(){},onRetry(){}}));assert.match(html,/Reconnecting to your trip/);assert.match(html,/checking this same trip automatically/);assert.match(html,/3 of 9 days planned/);assert.doesNotMatch(html,/>Check planning status<|>Try this section again</);
 const ended=renderToStaticMarkup(React.createElement(Status,{state:{...value,reconnecting:false},onCheck(){}}));assert.match(ended,/>Check planning status</);
});
test('exhausted automatic recovery and unavailable response have honest fixed guidance',()=>{
 for(const code of ['SECTION_AUTO_RETRYABLE_FAILURE','SECTION_AUTO_RETRYABLE_INCOMPLETE','SECTION_RESPONSE_UNAVAILABLE']){
  const body=groundedPage({status:'failed'});body.research=null;body.plan.pauseReason='SECTION_FAILED';body.plan.activeSection={id:'33333333-3333-4333-8333-333333333333',status:'failed',errorCode:code,failureDetails:null};
  const html=renderToStaticMarkup(React.createElement(Status,{state:state(body),onRetry(){},onCheck(){}}));assert.match(html,/Planning is paused/);assert.match(html,code==='SECTION_RESPONSE_UNAVAILABLE'?/no longer available/:/Automatic recovery/);assert.doesNotMatch(html,/Reconnecting to your trip|increase your budget|shorten your trip/);
 }
});
