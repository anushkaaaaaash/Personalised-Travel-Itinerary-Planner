import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { plan as itinerary, preferences } from './shareFixture.js';
import { createAdaptiveFixture } from '../tools/adaptiveVisualFixtures.mjs';
import { validateAdaptivePage } from '../src/services/adaptivePlanning.js';

const plan = patch => ({id:'test-plan',status:'active',completedDays:3,totalDays:24,runAllowance:3,estimatedSections:8,remainingCreates:2,spentCents:15000,totalBudgetCents:250000,pauseReason:null,activeSection:null,...patch});
const state = patch => ({plan:plan(),preferences:{...preferences,endDate:'2028-03-22'},sections:[],nextCursor:null,pageCursor:0,loading:false,needsCheck:false,resumable:true,...patch});
const actions = {onCheck(){},onCancel(){},onContinue(){},onRetry(){},onLoadPage(){},onNewPlan(){},onEditPreferences(){}};

test('adaptive status shows only authoritative completed-day counts and honest section scope',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const section={id:'section-a',sequence:1,startDate:preferences.startDate,endDate:preferences.endDate,checkpoint:{itinerary:itinerary(),spentCents:15000,startLocation:'Tokyo',endLocation:'Kyoto'}};
    const html=renderToStaticMarkup(React.createElement(Status,{state:state({sections:[section]}),...actions}));
    assert.match(html,/3 of 24 days planned/);assert.match(html,/max="24" value="3"/);assert.match(html,/2028-03-22/);
    assert.match(html,/Only completed sections count/);assert.match(html,/Section estimate/);assert.match(html,/not finished yet/);
    assert.doesNotMatch(html,/Save itinerary|Update this saved|Download summary|Print \/ save|Make it more you|\d+%/);
  }finally{await server.close();}
});

test('allowance continuation and retry are explicit; unknown or unconfirmed cancellation never creates again',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    let continues=0,checks=0;
    const render=async value=>act(async()=>{if(renderer)renderer.update(React.createElement(Status,{state:value,...actions,onContinue:()=>continues++,onCheck:()=>checks++}));else renderer=create(React.createElement(Status,{state:value,...actions,onContinue:()=>continues++,onCheck:()=>checks++}));});
    const buttons=()=>renderer.root.findAllByType('button');
    await render(state({plan:plan({status:'paused',pauseReason:'RESOURCE_ALLOWANCE_REACHED',remainingCreates:0})}));
    assert.match(JSON.stringify(renderer.toJSON()),/Planning is paused/);
    assert.equal(continues,0);const next=buttons().find(node=>node.children.join('')==='Continue planning');assert.ok(next);
    await act(async()=>next.props.onClick());assert.equal(continues,1);
    await render(state({needsCheck:true,cancelRequested:true,cancelUnconfirmed:true,plan:plan({status:'paused',pauseReason:'SUBMISSION_UNKNOWN',activeSection:{status:'submission_unknown',errorCode:null}})}));
    assert.equal(buttons().some(node=>/Continue planning|Try this section/.test(node.children.join(''))),false);
    const check=buttons().find(node=>node.children.join('')==='Check planning status');assert.equal(Boolean(check.props.disabled),false);await act(async()=>check.props.onClick());assert.equal(checks,1);assert.equal(continues,1);
    await render(state({plan:plan({status:'active'})}));assert.doesNotMatch(JSON.stringify(renderer.toJSON()),/Planning is paused/);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('filtered empty section pages remain navigable without creating new planning work',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');const pages=[];
    await act(async()=>{renderer=create(React.createElement(Status,{state:state({sections:[],pageCursor:3,nextCursor:6}),...actions,onLoadPage:value=>pages.push(value)}));});
    const buttons=renderer.root.findAllByType('button');
    await act(async()=>buttons.find(node=>node.children.join('')==='First sections').props.onClick());
    await act(async()=>buttons.find(node=>node.children.join('')==='Next completed sections').props.onClick());
    assert.deepEqual(pages,[0,6]);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('constraint recommendations are clearly proposed and target an edit step without changing inputs',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status,adaptiveRecovery}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    const paused=plan({status:'paused',pauseReason:'SECTION_FAILED',remainingCreates:0,activeSection:{status:'failed',errorCode:'SECTION_CONSTRAINT_CONFLICT',failureDetails:{applicability:'proposed',explanation:'This part needs more transfer time.',recommendations:[{field:'travelPace',reason:'The proposed transfers leave too little rest.',suggestion:'Consider a slower pace for the requested activities.'}]}}});
    let recovery;
    await act(async()=>{renderer=create(React.createElement(Status,{state:state({plan:paused}),...actions,onEditPreferences:value=>{recovery=value;}}));});
    assert.match(JSON.stringify(renderer.toJSON()),/not verified prices/);
    assert.doesNotMatch(JSON.stringify(renderer.toJSON()),/Ready for the next part|Continue planning|Try this section again/);
    const button=renderer.root.findAllByType('button').find(node=>node.children.join('')==='Stop planning and review changes');await act(async()=>button.props.onClick());
    assert.equal(recovery.proposed,true);assert.equal(recovery.editStep,1);assert.equal(recovery.recommendations[0].field,'travelPace');
    const original=structuredClone(preferences);
    const form=renderToStaticMarkup(React.createElement(Form,{form:preferences,step:1,recovery,onChange(){},adaptiveEnabled:true}));
    assert.match(form,/Suggestions to review/);assert.match(form,/proposed transfers leave too little rest/);assert.match(form,/travelPace-recovery/);assert.deepEqual(preferences,original);
    const dates=renderToStaticMarkup(React.createElement(Form,{form:state().preferences,step:0,onChange(){},adaptiveEnabled:true}));
    assert.match(dates,/value="2028-03-22"/);assert.match(dates,/Choose your full trip dates/);assert.doesNotMatch(dates,/1–14|30 days/);
    const budget=adaptiveRecovery(plan({pauseReason:'SECTION_FAILED',activeSection:{status:'failed',errorCode:'SECTION_BUDGET_EXHAUSTED'}}));assert.equal(budget.editStep,1);assert.equal(budget.recommendations[0].field,'budget');assert.equal(budget.proposed,undefined);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('section service and output failures explain their actual category without inventing trip corrections',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  try{
    const {adaptiveRecovery}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const cases={SECTION_PROVIDER_FAILED:/service couldn’t finish/,SECTION_DEADLINE_REACHED:/time limit/,SECTION_PROVIDER_INCOMPLETE:/incomplete/,SECTION_OUTPUT_LIMIT:/output allowance/,SECTION_CONTINUITY_CONFLICT:/preceding section/,SECTION_RETURN_MISSING:/return journey/,SECTION_REST_CONFLICT:/required rest/,SECTION_TRAVEL_DOUBLE_COUNT:/duplicate journey costs/,SECTION_BUDGET_EXCEEDED:/does not prove/,SECTION_INVALID_COST:/cost estimates/,SECTION_RESPONSE_MISMATCH:/did not match/,SECTION_STRATEGY_CONFLICT:/planned journey/,SECTION_TRANSFER_MISSING:/required transfer/,SECTION_REPEAT_CONFLICT:/recent activity/};
    for(const [errorCode,expected] of Object.entries(cases)){
      const recovery=adaptiveRecovery(plan({pauseReason:'SECTION_FAILED',activeSection:{status:'failed',errorCode}}));
      assert.match(`${recovery.title} ${recovery.message}`,expected);assert.equal(recovery.editStep,null);assert.deepEqual(recovery.recommendations,[]);
    }
  }finally{await server.close();}
});

test('review discloses actual section and request estimates without imposing a total-day cap',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  try{
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const form={...preferences,startDate:'2028-01-01',endDate:'2028-02-15'};
    const html=renderToStaticMarkup(React.createElement(Form,{form,step:2,onChange(){},adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:12}}));
    assert.match(html,/46-day trip starts with an estimated 16 sections/);assert.match(html,/up to 12 section requests/);assert.match(html,/Retries use this allowance/);assert.match(html,/dates stay unchanged/);assert.doesNotMatch(html,/1–14|maximum trip|30 days/);
    const paused=renderToStaticMarkup(React.createElement(Status,{state:state({plan:plan({status:'paused',pauseReason:'RESOURCE_ALLOWANCE_REACHED',remainingCreates:0,runAllowance:12})}),...actions}));
    assert.match(paused,/up to 12 more section requests/);assert.doesNotMatch(paused,/three more/);
    const invalid=renderToStaticMarkup(React.createElement(Form,{form,step:2,onChange(){},adaptiveEnabled:true,adaptivePolicy:{sectionDays:3,maxSubmissionsPerRun:Infinity}}));assert.doesNotMatch(invalid,/Infinity/);
  }finally{await server.close();}
});

test('confirmed number-format rejection offers a precise budget edit, while unknown outcomes only check',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status,adaptiveRequestRecovery}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');let advice;
    await act(async()=>{renderer=create(React.createElement(Status,{state:state({plan:null,resumable:false,error:'PRIVATE_SERVER_TEXT',errorCode:'SECTION_MONEY_INVALID'}),...actions,onEditPreferences:value=>{advice=value;}}));});
    const text=JSON.stringify(renderer.toJSON());assert.match(text,/not a judgment that your trip budget is too low/);assert.doesNotMatch(text,/PRIVATE_SERVER_TEXT/);
    await act(async()=>renderer.root.findAllByType('button').find(node=>node.children.join('')==='Review budget format').props.onClick());
    assert.equal(advice.editStep,1);assert.match(advice.recommendations[0].suggestion,/at most two decimal places/);assert.equal(advice.recommendations[0].field,'budget');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    const form=renderToStaticMarkup(React.createElement(Form,{form:{...preferences,budget:2500.123},step:1,recovery:advice,onChange(){},adaptiveEnabled:true}));
    assert.match(form,/value="2500.123"/);assert.match(form,/aria-invalid="true" data-recommended="true" aria-describedby="budget-recovery"/);
    for(const code of ['ADAPTIVE_UNAVAILABLE','ADAPTIVE_INVALID_RESPONSE','ADAPTIVE_NOT_FOUND','ADAPTIVE_CONFLICT','ADAPTIVE_OUTCOME_UNCONFIRMED'])assert.deepEqual(adaptiveRequestRecovery(code).recommendations,[]);
    const uncertain=renderToStaticMarkup(React.createElement(Status,{state:state({plan:null,needsCheck:true,error:'PRIVATE_SERVER_TEXT',errorCode:'ADAPTIVE_UNAVAILABLE'}),...actions}));
    assert.match(uncertain,/couldn’t check the planning service/);assert.match(uncertain,/Check planning status/);assert.doesNotMatch(uncertain,/Review budget format|Continue planning|Try this section/);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('storage pauses distinguish a full session from shared capacity and never imply a trip preference fault',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const render=storagePauseScope=>renderToStaticMarkup(React.createElement(Status,{state:state({plan:plan({status:'paused',pauseReason:'STORAGE_LIMIT',storagePauseScope,expiresAt:'2028-12-31T00:00:00Z'})}),...actions}));
    const own=render('plan');assert.match(own,/No further sections can be added in this session/);assert.match(own,/Completed sections remain available until/);assert.doesNotMatch(own,/Check capacity and continue|Continue planning/);
    const shared=render('global');assert.match(shared,/Check capacity and continue/);assert.match(shared,/if it is still full, no new section request/);assert.match(shared,/allowance and dates are unchanged/);assert.doesNotMatch(shared,/Shorten|Increase your budget/);
  }finally{await server.close();}
});

test('SQL-shaped failed checkpoints reach actionable advice after real client validation, even with no requests left',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status,adaptiveRecovery}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');
    const fixture=createAdaptiveFixture();fixture.phase='constraint';fixture.preferences={...preferences,startDate:'2028-01-01',endDate:'2028-02-15'};fixture.requestId='22345678-1234-1234-1234-123456789abc';
    const raw=fixture.snapshot();raw.plan.remainingCreates=0;const decoded=validateAdaptivePage(raw);assert.equal(decoded.plan.pauseReason,'SECTION_FAILED');let advice;
    await act(async()=>{renderer=create(React.createElement(Status,{state:state(decoded),...actions,onEditPreferences:value=>{advice=value;}}));});
    const text=JSON.stringify(renderer.toJSON());assert.match(text,/Suggestions for this part/);assert.doesNotMatch(text,/Ready for the next part|Continue planning|Try this section again/);
    await act(async()=>renderer.root.findAllByType('button').find(node=>node.children.join('')==='Stop planning and review changes').props.onClick());assert.equal(advice.editStep,1);assert.equal(advice.recommendations[0].field,'travelPace');
    const missing=adaptiveRecovery({...decoded.plan,activeSection:{...decoded.plan.activeSection,failureDetails:null}});assert.match(missing.message,/did not provide specific changes/);assert.deepEqual(missing.recommendations,[]);
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('retained-plan downloads disclose partial scope and expiry without claiming account saves',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');let downloads=0;
    const props={state:state({plan:plan({status:'cancelled',expiresAt:'2028-12-31T00:00:00Z'})}),...actions,onExport:()=>downloads++};
    await act(async()=>{renderer=create(React.createElement(Status,props));});const text=JSON.stringify(renderer.toJSON());
    assert.match(text,/Partial snapshot/);assert.match(text,/not just this page/);assert.match(text,/Unplanned days are not included/);assert.match(text,/24 hours, not saved as an account itinerary/);assert.match(text,/2028-12-31T00:00:00Z/);
    const button=renderer.root.findAllByType('button').find(node=>node.children.join('')==='Download retained plan (.txt)');await act(async()=>button.props.onClick());assert.equal(downloads,1);
    await act(async()=>renderer.update(React.createElement(Status,{...props,exporting:true})));assert.equal(renderer.root.findAllByType('button').find(node=>node.children.join('')==='Preparing download…').props.disabled,true);
    await act(async()=>renderer.update(React.createElement(Status,{...props,exportError:'The download was interrupted. No file was saved.'})));assert.match(renderer.root.findByProps({role:'alert'}).children.join(''),/No file was saved/);
    for(const [status,completedDays,expected] of [['completed',24,true],['expired',3,false],['active',0,false]]){
      const html=renderToStaticMarkup(React.createElement(Status,{...props,state:state({plan:plan({status,completedDays})})}));assert.equal(html.includes('Download retained plan (.txt)'),expected);if(expected)assert.match(html,/Full-date snapshot/);
    }
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});

test('proposed constraints permit one explicit remaining-section retry, never unknown or exhausted cases',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  try{
    const {default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx');let retries=0;
    const failed=plan({status:'paused',completedDays:6,totalDays:9,pauseReason:'SECTION_FAILED',remainingCreates:1,activeSection:{status:'failed',errorCode:'SECTION_CONSTRAINT_CONFLICT',failureDetails:{applicability:'proposed',explanation:'Review this travel day.',recommendations:[{field:'travelPace',reason:'Time is needed for travel.',suggestion:'Consider allowing fewer activities.'}]}}});
    await act(async()=>{renderer=create(React.createElement(Status,{state:state({plan:failed}),...actions,onRetry:()=>retries++}));});
    assert.equal(retries,0);assert.match(JSON.stringify(renderer.toJSON()),/completed days are kept; this uses one request/);
    await act(async()=>renderer.root.findAllByType('button').find(node=>node.children.join('')==='Retry remaining section').props.onClick());assert.equal(retries,1);
    assert.ok(renderer.root.findAllByType('button').some(node=>node.children.join('')==='Stop planning and review changes'));
    for(const patch of [{needsCheck:true},{plan:{...failed,remainingCreates:0}},{plan:{...failed,activeSection:{...failed.activeSection,status:'submission_unknown'}}},{plan:{...failed,activeSection:{...failed.activeSection,failureDetails:null}}},{plan:{...failed,activeSection:{...failed.activeSection,failureDetails:{applicability:'proposed'}}}},{plan:{...failed,activeSection:{...failed.activeSection,errorCode:'SECTION_BUDGET_EXHAUSTED'}}}]){
      const html=renderToStaticMarkup(React.createElement(Status,{state:state({plan:failed,...patch}),...actions}));assert.doesNotMatch(html,/Retry remaining section/);
    }
  }finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
});
