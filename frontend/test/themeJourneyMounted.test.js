import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { COUNTRY_THEMES } from '../src/themes/countryThemes.js';
import { plan, preferences, detail } from './shareFixture.js';

async function harness(run) {
  const server = await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const originalFetch=globalThis.fetch, originalDocument=globalThis.document;
  let renderer;
  const {setSession}=await server.ssrLoadModule('/src/services/session.js');
  try {
    const {DestinationThemeProvider}=await server.ssrLoadModule('/src/themes/DestinationTheme.jsx');
    const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');
    const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
    const {default:Generated}=await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');
    const {default:Routes}=await server.ssrLoadModule('/src/components/PlannerRoutes.jsx');
    const {MemoryRouter,useNavigate}=await server.ssrLoadModule('react-router-dom');
    const tokens=new Map(), root={dataset:{},style:{getPropertyValue:key=>tokens.get(key)||'',setProperty:(key,value)=>tokens.set(key,value),removeProperty:key=>tokens.delete(key)}};
    globalThis.document={documentElement:root,querySelector:()=>null};
    const catalogue=async()=>COUNTRY_THEMES;
    const env={Page,Form,Generated,Routes,MemoryRouter,useNavigate,setSession,root,tokens,
      mount:async element=>act(async()=>{renderer=create(React.createElement(DestinationThemeProvider,{loadCatalogue:catalogue},element));}),
      unmount:async()=>act(async()=>{renderer.unmount();renderer=null;}),
      text:()=>JSON.stringify(renderer.toJSON()),
      props:()=>renderer.root.findByType(Form).props,
      change:async(name,value)=>act(async()=>renderer.root.findByType(Form).props.onChange({target:{name,value}})),
      click:async label=>act(async()=>{const button=renderer.root.findAllByType('button').find(node=>node.children.some(child=>typeof child==='string'&&child.includes(label)));assert.ok(button,label);button.props.onClick();}),
      theme:code=>{assert.equal(root.dataset.destinationTheme,code);if(code!=='WORLD')assert.equal(tokens.get('--sea'),COUNTRY_THEMES.find(theme=>theme.code===code).primary);},
    };
    await run(env);
  } finally {
    if(renderer)await act(async()=>renderer.unmount());
    setSession(null);globalThis.fetch=originalFetch;globalThis.document=originalDocument;await server.close();
  }
}
const response=body=>({status:200,json:async()=>body});

test('chosen country follows loading, error, edited destination and new result without retaining the previous palette',()=>harness(async env=>{
  const calls=[];let finish;
  globalThis.fetch=async(url,options)=>{assert.equal(url,'/api/itineraries/generate');calls.push(JSON.parse(options.body));return new Promise(resolve=>{finish=resolve;});};
  await env.mount(React.createElement(env.Page));env.theme('WORLD');
  for(const [name,value] of Object.entries({...preferences,destination:'Japan'}))await env.change(name,value);
  env.theme('JP');
  const review=async()=>{await act(async()=>env.props().onSubmit({preventDefault(){}}));await act(async()=>env.props().onSubmit({preventDefault(){}}));};
  await review();await act(async()=>env.props().onGenerateItinerary());env.theme('JP');assert.match(env.text(),/Your trip is taking shape/);
  await act(async()=>finish({status:502,json:async()=>({error:{code:'AI_PROVIDER_FAILED'}})}));
  env.theme('JP');assert.match(env.text(),/The planning service couldn’t finish/);assert.doesNotMatch(env.text(),/needs a little more time/);
  await env.click('Edit trip details');assert.equal(env.props().step,0);assert.equal(env.props().form.destination,'Japan');env.theme('JP');
  await env.change('destination','Paris, France');env.theme('FR');await review();
  await act(async()=>env.props().onGenerateItinerary());env.theme('FR');
  await act(async()=>finish(response({...plan(),destination:'Paris, France'})));
  env.theme('FR');assert.match(env.text(),/Make the days your own/);assert.doesNotMatch(env.text(),/Japan/);assert.deepEqual(calls.map(call=>call.destination),['Japan','Paris, France']);
  await env.click('Trip preferences');await env.change('destination','Paris, Texas');env.theme('WORLD');assert.doesNotMatch(env.text(),/Return to your itinerary/);
  await env.unmount();assert.equal(env.root.dataset.destinationTheme,undefined);
  await env.mount(React.createElement(env.Page));env.theme('WORLD');assert.equal(env.props().form.destination,'');assert.doesNotMatch(env.text(),/Make the days your own/);
}));

test('saved-trip route changes select their own country and returning to the planner clears the old theme',()=>harness(async env=>{
  const japan='32345678-1234-1234-1234-123456789abc', france='42345678-1234-1234-1234-123456789abc';
  const reads=[];let navigate;
  globalThis.fetch=async(url,options)=>{assert.equal(options.method,'GET');reads.push(url);const id=url.split('/').at(-1);assert.ok([japan,france].includes(id));const destination=id===japan?'Japan':'France';return response({...detail(),id,preferences:{...preferences,destination},itinerary:{...plan(),destination}});};
  env.setSession({user:{id:'synthetic-owner'},access_token:'TEST_ONLY_TOKEN',expires_at:Date.now()/1000+3600});
  function NavigationProbe(){navigate=env.useNavigate();return null;}
  await env.mount(React.createElement(env.MemoryRouter,{initialEntries:[`/itineraries/${japan}`]},React.createElement(NavigationProbe),React.createElement(env.Routes,{signedIn:true,ownershipEnabled:true})));
  env.theme('JP');assert.match(env.text(),/Your saved trip/);
  await act(async()=>navigate(`/itineraries/${france}`));env.theme('FR');assert.doesNotMatch(env.text(),/Japan/);
  await act(async()=>navigate('/'));env.theme('WORLD');assert.equal(env.props().form.destination,'');assert.doesNotMatch(env.text(),/Your saved trip"/);
  assert.deepEqual(reads,[`/api/saved-itineraries/${japan}`,`/api/saved-itineraries/${france}`]);
}));

test('date-range guidance is accessible and invalid-date recovery edits details instead of repeating a failed request',()=>harness(async env=>{
  const form=renderToStaticMarkup(React.createElement(env.Form,{form:preferences,step:0,onChange(){},errors:{endDate:'Choose a trip of 1–14 days.'}}));
  assert.match(form,/id="trip-length-hint">Plan 1–14 days at a time/);
  assert.match(form,/name="startDate"[^>]*aria-describedby="trip-length-hint"/);
  assert.match(form,/name="endDate"[^>]*aria-describedby="endDate-error trip-length-hint"/);
  const invalid=renderToStaticMarkup(React.createElement(env.Generated,{error:'Choose a trip of 1–14 days.',errorCode:'ITINERARY_DURATION_UNSUPPORTED',onRetry(){},onEditPreferences(){}}));
  assert.match(invalid,/cannot handle the whole date range/);assert.match(invalid,/Edit trip details/);assert.doesNotMatch(invalid,/Try again|needs a little more time/);
  const transient=renderToStaticMarkup(React.createElement(env.Generated,{error:'The request timed out.',onRetry(){},onEditPreferences(){}}));
  assert.match(transient,/Try again/);assert.match(transient,/Edit trip details/);assert.doesNotMatch(transient,/needs a little more time/);
}));
