import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {createAdaptiveFixture} from '../tools/adaptiveVisualFixtures.mjs';
import {preferences} from './shareFixture.js';
import {savedFixture,savedId} from './savedAdaptiveFixture.js';
const archiveId='77777777-7777-4777-8777-777777777777';
const owner=id=>({user:{id},access_token:'SYNTHETIC',expires_at:Date.now()/1000+3600});
const flatten=node=>typeof node==='string'?node:typeof node==='number'?String(node):Array.isArray(node)?node.map(flatten).join(''):node?.children?node.children.map(flatten).join(''):'';
const button=(env,label)=>env.root().findAllByType('button').find(node=>flatten(node)===label);
function archiveFixture() {
  const fixture=createAdaptiveFixture();fixture.phase='completed';fixture.preferences={...preferences,startDate:'2028-01-01',endDate:'2028-01-12'};fixture.requestId='22345678-1234-1234-1234-123456789abc';
  const base=fixture.snapshot();
  const saved={id:archiveId,requestId:fixture.requestId,title:'A saved twelve-day journey',version:1,createdAt:'2026-10-01T12:00:00Z',updatedAt:'2026-10-01T12:00:00Z',format:'adaptive-sections-v1',persisted:true,sourcePlanId:base.plan.id,sourceVersion:12,totalDays:12,sectionCount:4,spentCents:180000,totalBudgetCents:250000,currency:'USD',startDate:'2028-01-01',endDate:'2028-01-12',destination:base.preferences.destination};
  const historical={receivedAt:'2025-01-01T12:00:00Z',expiresAt:'2025-01-02T12:00:00Z',text:'Historical museum notes. Confirm opening hours.',sources:[{url:'https://example.com/museum',title:'Museum visitor information'}],citations:[{start:0,end:10,url:'https://example.com/museum',title:'Museum visitor information'}],applicability:'unknown',evidenceStatus:'historical_unverified'};
  const sections=base.sections.map((section,index)=>({...section,sourceAssociation:index===0?'linked_historical':'none_recorded',historicalSources:index===0?[historical]:[]}));
  const last=structuredClone(sections[2]);last.id='88888888-8888-4888-8888-888888888888';last.sequence=4;last.startDate='2028-01-10';last.endDate='2028-01-12';last.checkpoint.endLocation=base.preferences.departureCity;
  last.checkpoint.itinerary.days.forEach((day,index)=>{day.date=`2028-01-${index+10}`;day.dining='FINAL_PAGE_DINING';});
  return {saved,page:cursor=>({saved,preferences:base.preferences,journeyStrategy:sections[0].checkpoint.journeyStrategy,sections:cursor===0?sections:[last],nextCursor:cursor===0?3:null})};
}
async function mounted(run) {
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});let renderer;
  const {setSession}=await server.ssrLoadModule('/src/services/session.js');
  try {
    const {default:Collection}=await server.ssrLoadModule('/src/components/SavedAdaptiveTrips.jsx');
    const {default:Detail,SavedAdaptiveTripReader}=await server.ssrLoadModule('/src/pages/SavedAdaptiveTripPage.jsx');
    const {MemoryRouter,Routes,Route}=await server.ssrLoadModule('react-router-dom');
    setSession(owner('owner-a'));
    await run({Collection,Detail,SavedAdaptiveTripReader,setSession,root:()=>renderer.root,text:()=>flatten(renderer.toJSON()),
      mount:async(component,props={},path='/')=>act(async()=>{renderer=create(React.createElement(MemoryRouter,{initialEntries:[path]},React.createElement(component,props)));}),
      mountRoute:async client=>act(async()=>{renderer=create(React.createElement(MemoryRouter,{initialEntries:[`/saved-adaptive-trips/${archiveId}`]},React.createElement(Routes,null,React.createElement(Route,{path:'/saved-adaptive-trips/:tripID',element:React.createElement(Detail,{client})}))));}),
      unmount:async()=>act(async()=>{renderer.unmount();renderer=null;})});
  } finally {if(renderer)await act(async()=>renderer.unmount());setSession(null);await server.close();}
}
test('saved archive collection is separate, bounded and navigates only to verified saved IDs',()=>mounted(async env=>{
  const fixture=archiveFixture(),calls=[];let finish;
  const client={list:async(offset,{signal})=>{calls.push({offset,signal});if(offset===0)return{items:[fixture.saved],offset,hasMore:true};return new Promise(resolve=>finish=resolve);}};
  await env.mount(env.Collection,{client});assert.match(env.text(),/Your complete saved trips/);assert.ok(env.root().findAllByType('a').some(link=>link.props.href===`/saved-adaptive-trips/${archiveId}`));assert.doesNotMatch(env.text(),/Save this trip|Delete|Regenerate/);
  await act(async()=>{const next=button(env,'Next trips').props.onClick;next();next();});assert.deepEqual(calls.map(call=>call.offset),[0,20]);assert.equal(button(env,'Next trips').props.disabled,true);
  await act(async()=>finish({items:[],offset:20,hasMore:false}));assert.doesNotMatch(env.text(),/A saved twelve-day journey/);assert.equal(button(env,'Next trips').props.disabled,true);
  await act(async()=>button(env,'Previous trips').props.onClick());assert.deepEqual(calls.map(call=>call.offset),[0,20,0]);
}));
test('saved archive collection scrubs prior data and ignores an in-flight response on owner change',()=>mounted(async env=>{
  const fixture=archiveFixture();let finish,signal;
  await env.mount(env.Collection,{client:{list:(_,options)=>{signal=options.signal;return new Promise(resolve=>finish=resolve);}}});
  await act(async()=>env.setSession(owner('owner-b')));assert.equal(signal.aborted,true);
  await act(async()=>finish({items:[fixture.saved],offset:0,hasMore:false}));assert.doesNotMatch(env.text(),/A saved twelve-day journey/);assert.match(env.text(),/Sign in again/);
}));
test('saved trip route reopens historical sections after source expiry with real totals and no temporary-plan calls',()=>mounted(async env=>{
  const fixture=archiveFixture(),calls=[],original=structuredClone(fixture.page(0));let finish;
  const client={get:async(id,{afterSequence,signal})=>{calls.push({id,afterSequence,signal});assert.equal(id,archiveId);if(afterSequence===0)return fixture.page(0);return new Promise(resolve=>finish=resolve);}};
  await env.mountRoute(client);
  assert.match(env.text(),/A saved twelve-day journey/);assert.match(env.text(),/copy remains separate from the original temporary planning session and its expiry/);assert.match(env.text(),/USD 1,800.00/);assert.match(env.text(),/Costs cover all 12 saved days/);
  assert.equal(env.root().findAll(node=>node.props['aria-label']?.startsWith('Saved trip days ')).length,3);
  assert.match(env.text(),/Historical museum notes/);assert.match(env.text(),/2025/);assert.match(env.text(),/Saving did not refresh them/);assert.match(env.text(),/No sources were saved for these dates/);assert.doesNotMatch(env.text(),/This planning session has expired|FINAL_PAGE_DINING/);
  const link=env.root().findAllByType('a').find(node=>node.props.href==='https://example.com/museum');assert.equal(link.props.rel,'noopener noreferrer');assert.equal(link.props.target,'_blank');
  assert.match(env.text(),/Example Garden Café/);assert.equal(env.root().findAll(node=>node.type==='section'&&node.props.className==='card adaptive-section').length,0);assert.equal(env.root().findAll(node=>node.type==='details'&&node.props.className==='card adaptive-day').length,9);assert.match(env.text(),/Day outline/);assert.match(env.text(),/Day expense breakdown/);assert.doesNotMatch(env.text(),/Accept this revised day|Save this trip|Stop planning|Retry research/);
  assert.equal(button(env,'Next days'),undefined);assert.equal(button(env,'Earlier days'),undefined);assert.deepEqual(calls.map(call=>call.afterSequence),[0,3]);assert.match(env.text(),/9 of 12 saved days shown/);
  await act(async()=>finish(fixture.page(3)));assert.equal(env.root().findAll(node=>node.props['aria-label']?.startsWith('Saved trip days ')).length,4);assert.match(env.text(),/FINAL_PAGE_DINING/);assert.match(env.text(),/Day 10/);assert.match(env.text(),/Day 12/);assert.match(env.text(),/Day 01/);assert.match(env.text(),/Historical museum notes/);assert.match(env.text(),/USD 1,800.00/);assert.match(env.text(),/12 of 12 saved days shown/);assert.equal(button(env,'Next days'),undefined);assert.deepEqual(calls.map(call=>call.afterSequence),[0,3]);assert.deepEqual(fixture.page(0),original);
}));
test('saved detail ignores late owner and unmount results and never retains private day text for another owner',()=>mounted(async env=>{
  const fixture=archiveFixture();let finish,signal;
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:(_,options)=>{signal=options.signal;return new Promise(resolve=>finish=resolve);}}});
  await act(async()=>env.setSession(owner('owner-b')));assert.equal(signal.aborted,true);
  await act(async()=>finish(fixture.page(0)));assert.doesNotMatch(env.text(),/A saved twelve-day journey|Private dietary note/);assert.match(env.text(),/Sign in again/);
  await env.unmount();env.setSession(owner('owner-a'));
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:(_,options)=>{signal=options.signal;return new Promise(resolve=>finish=resolve);}}});
  await env.unmount();assert.equal(signal.aborted,true);await act(async()=>finish(fixture.page(0)));
}));
test('saved detail failure messages are fixed and retry reads do not expose raw server text',()=>mounted(async env=>{
  let calls=0;const fixture=archiveFixture();
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:async(_,{afterSequence})=>{if(++calls===1)throw Object.assign(Error('PRIVATE_SERVER_TEXT'),{code:'SAVED_ADAPTIVE_NOT_FOUND'});return fixture.page(afterSequence);}}});
  assert.match(env.text(),/could not be found or is not available to your account/);assert.doesNotMatch(env.text(),/PRIVATE_SERVER_TEXT/);
  await act(async()=>button(env,'Check this saved trip').props.onClick());assert.match(env.text(),/A saved twelve-day journey/);assert.equal(calls,3);
}));
test('saved copy deletion requires explicit confirmation, suppresses duplicates and clears only saved detail',()=>mounted(async env=>{
  const fixture=archiveFixture(),calls=[];let finish;
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:async(_,{afterSequence})=>fixture.page(afterSequence),remove:(...args)=>{calls.push(args);return new Promise(resolve=>finish=resolve);}}});
  await act(async()=>button(env,'Delete saved copy').props.onClick());assert.equal(calls.length,0);assert.match(env.text(),/original temporary plan remains unchanged/);
  await act(async()=>button(env,'Keep saved copy').props.onClick());assert.equal(calls.length,0);
  await act(async()=>button(env,'Delete saved copy').props.onClick());
  await act(async()=>{const confirm=button(env,'Confirm delete saved copy').props.onClick;confirm();confirm();});assert.equal(calls.length,1);assert.equal(calls[0][0],archiveId);assert.equal(calls[0][1],fixture.saved.version);
  await act(async()=>finish({id:archiveId,deleted:true,version:fixture.saved.version}));assert.match(env.text(),/saved account copy was deleted/);assert.doesNotMatch(env.text(),/A saved twelve-day journey|Example Garden Café/);assert.ok(env.root().findAllByType('a').some(link=>link.props.href==='/saved-trips'));
}));
test('unknown delete stops writes until same-ID read succeeds and requires fresh confirmation',()=>mounted(async env=>{
  const fixture=archiveFixture();let reads=0,writes=0;
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:async(id,{afterSequence})=>{assert.equal(id,archiveId);if(afterSequence===0&&++reads===2)throw Error('temporary');return fixture.page(afterSequence);},remove:async()=>{writes++;throw Error('PRIVATE_UNKNOWN');}}});
  await act(async()=>button(env,'Delete saved copy').props.onClick());const staleConfirm=button(env,'Confirm delete saved copy').props.onClick;
  await act(async()=>staleConfirm());assert.equal(writes,1);assert.equal(button(env,'Delete saved copy').props.disabled,true);assert.match(env.text(),/deletion outcome is not confirmed/);assert.doesNotMatch(env.text(),/PRIVATE_UNKNOWN/);
  await act(async()=>{staleConfirm();button(env,'Check this saved trip').props.onClick();});assert.equal(writes,1);assert.equal(button(env,'Delete saved copy').props.disabled,true);
  await act(async()=>button(env,'Check this saved trip').props.onClick());assert.equal(button(env,'Delete saved copy').props.disabled,false);await act(async()=>staleConfirm());assert.equal(writes,1);
  await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>{button(env,'Confirm delete saved copy').props.onClick();});assert.equal(writes,2);
}));
test('unknown delete followed by not-found reports inaccessible rather than confirmed deletion',()=>mounted(async env=>{
  const fixture=archiveFixture();let reads=0,writes=0;
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:async(_,{afterSequence})=>{if(afterSequence===0&&++reads>1)throw Object.assign(Error('missing'),{code:'SAVED_ADAPTIVE_NOT_FOUND'});return fixture.page(afterSequence);},remove:async()=>{writes++;return {deleted:false};}}});
  await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>{button(env,'Confirm delete saved copy').props.onClick();});await act(async()=>button(env,'Check this saved trip').props.onClick());
  assert.equal(writes,1);assert.match(env.text(),/not available to your account/);assert.doesNotMatch(env.text(),/copy was deleted|A saved twelve-day journey/);assert.equal(button(env,'Delete saved copy'),undefined);
}));
test('delete aborts and ignores late success after token replacement or unmount',()=>mounted(async env=>{
  const fixture=archiveFixture();let finish,signal;
  const client={get:async(_,{afterSequence})=>fixture.page(afterSequence),remove:(_,__,options)=>{signal=options.signal;return new Promise(resolve=>finish=resolve);}};
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>{button(env,'Confirm delete saved copy').props.onClick();});
  await act(async()=>env.setSession(owner('owner-a')));assert.equal(signal.aborted,true);await act(async()=>finish({id:archiveId,deleted:true,version:1}));assert.match(env.text(),/Sign in again/);assert.doesNotMatch(env.text(),/copy was deleted|A saved twelve-day journey/);
  await env.unmount();await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>{button(env,'Confirm delete saved copy').props.onClick();});await env.unmount();assert.equal(signal.aborted,true);await act(async()=>finish({id:archiveId,deleted:true,version:1}));
}));

test('all seventeen saved days load continuously through validated GET pages without a Next button',()=>mounted(async env=>{
  const fixture=savedFixture(),calls=[];
  const {createSavedAdaptiveClient}=await import('../src/services/savedAdaptiveTrips.js');
  const client=createSavedAdaptiveClient({fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method});assert.equal(options.method,'GET');
    const cursor=Number(new URL(url,'https://example.test').searchParams.get('afterSequence'));
    const page=structuredClone(fixture.page(cursor));Object.assign(page.saved,{title:'Seventeen saved days',endDate:'2028-01-17',totalDays:17,spentCents:255000});
    page.preferences.endDate='2028-01-17';page.journeyStrategy.stays.at(-1).endDate='2028-01-17';
    for(const section of page.sections){section.checkpoint.journeyStrategy=structuredClone(page.journeyStrategy);if(section.sequence===6){section.endDate='2028-01-17';section.checkpoint.itinerary.days.pop();section.checkpoint.spentCents=30000;section.checkpoint.itinerary.estimatedTotalGroupCost=300;section.checkpoint.itinerary.remainingBudget=4700;}}
    return{status:200,json:async()=>page};
  }});
  await env.mount(env.SavedAdaptiveTripReader,{tripID:savedId,client});
  assert.equal(calls.length,2);assert.deepEqual(calls.map(call=>Number(new URL(call.url,'https://example.test').searchParams.get('afterSequence'))),[0,3]);
  assert.match(env.text(),/Seventeen saved days/);assert.match(env.text(),/17 of 17 saved days shown/);assert.match(env.text(),/Day 01/);assert.match(env.text(),/Day 17/);
  assert.equal(env.root().findAll(node=>node.type==='details'&&node.props.className==='card adaptive-day').length,17);assert.equal(button(env,'Next days'),undefined);assert.ok(button(env,'Download itinerary PDF'));
}));

test('later saved-page failures keep earlier days and same-version metadata is required before appending',()=>mounted(async env=>{
  const fixture=archiveFixture(),calls=[];let repaired=false;
  const client={get:async(id,{afterSequence})=>{calls.push(afterSequence);const page=structuredClone(fixture.page(afterSequence));if(afterSequence&&!repaired)page.saved.version=2;return page;}};
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});
  assert.deepEqual(calls,[0,3]);assert.match(env.text(),/Day 01/);assert.doesNotMatch(env.text(),/Day 12|FINAL_PAGE_DINING/);assert.match(env.text(),/displayed days are kept/);assert.equal(button(env,'Check this saved trip').props.disabled,false);
  repaired=true;await act(async()=>button(env,'Check this saved trip').props.onClick());assert.deepEqual(calls,[0,3,0,3]);assert.match(env.text(),/12 of 12 saved days shown/);assert.match(env.text(),/FINAL_PAGE_DINING/);
}));

test('owner changes abort a later automatic saved-page read and scrub already displayed days',()=>mounted(async env=>{
  const fixture=archiveFixture();let finish,signal;
  const client={get:async(_,{afterSequence,signal:requestSignal})=>{if(!afterSequence)return fixture.page(0);signal=requestSignal;return new Promise(resolve=>finish=resolve);}};
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});assert.match(env.text(),/Day 01/);assert.match(env.text(),/9 of 12 saved days shown/);
  await act(async()=>env.setSession(owner('owner-b')));assert.equal(signal.aborted,true);await act(async()=>finish(fixture.page(3)));
  assert.match(env.text(),/Sign in again/);assert.doesNotMatch(env.text(),/Day 01|Day 12|FINAL_PAGE_DINING|A saved twelve-day journey/);
}));

test('a repeated saved-page cursor stops automatic reads without hiding earlier days',()=>mounted(async env=>{
  const fixture=archiveFixture(),calls=[];
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client:{get:async(_,{afterSequence})=>{calls.push(afterSequence);const page=structuredClone(fixture.page(afterSequence));if(afterSequence)page.nextCursor=afterSequence;return page;}}});
  assert.deepEqual(calls,[0,3]);assert.match(env.text(),/Day 01/);assert.doesNotMatch(env.text(),/Day 12|FINAL_PAGE_DINING/);assert.match(env.text(),/Some planned days could not be loaded/);assert.equal(button(env,'Next days'),undefined);assert.equal(button(env,'Check this saved trip').props.disabled,false);
}));


test('explicit saved recheck preserves all previously loaded identical days if a later read fails',()=>mounted(async env=>{
  const fixture=archiveFixture(),reads=[];let rechecking=false;
  const client={get:async(_,{afterSequence})=>{reads.push(afterSequence);if(rechecking&&afterSequence)throw Error('temporary');return fixture.page(afterSequence);},remove:async()=>{throw Error('unknown');}};
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});assert.match(env.text(),/12 of 12 saved days shown/);
  await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>button(env,'Confirm delete saved copy').props.onClick());
  rechecking=true;await act(async()=>button(env,'Check this saved trip').props.onClick());
  assert.deepEqual(reads,[0,3,0,3]);assert.match(env.text(),/12 of 12 saved days shown/);assert.match(env.text(),/Day 12|FINAL_PAGE_DINING/);assert.match(env.text(),/Some planned days could not be loaded/);
}));

test('saved recheck never retains later days against a changed same-version prefix',()=>mounted(async env=>{
  const fixture=archiveFixture();let rechecking=false;
  const client={get:async(_,{afterSequence})=>{if(rechecking&&afterSequence)throw Error('temporary');const page=structuredClone(fixture.page(afterSequence));if(rechecking)page.sections[0].checkpoint.itinerary.days[0].dining='Changed dining';return page;},remove:async()=>{throw Error('unknown');}};
  await env.mount(env.SavedAdaptiveTripReader,{tripID:archiveId,client});assert.match(env.text(),/12 of 12 saved days shown/);
  await act(async()=>button(env,'Delete saved copy').props.onClick());await act(async()=>button(env,'Confirm delete saved copy').props.onClick());
  rechecking=true;await act(async()=>button(env,'Check this saved trip').props.onClick());
  assert.match(env.text(),/9 of 12 saved days shown/);assert.match(env.text(),/Changed dining/);assert.doesNotMatch(env.text(),/Day 12|FINAL_PAGE_DINING/);
}));
