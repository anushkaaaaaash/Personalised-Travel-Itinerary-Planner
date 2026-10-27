/** TEMPORARY preview-only visual QA. Remove public/__qa before production merge. */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createInitialForm } from '../src/utils/tripPreferences.js';
import { validItinerary } from '../src/services/itineraries.js';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('..',import.meta.url));
const output=new URL('../public/__qa/',import.meta.url);
const server=await createServer({root,logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
const originalFetch=globalThis.fetch;globalThis.fetch=()=>{throw Error('QA rendering forbids network requests.');};
const h=React.createElement;
try {
 const load=async name=>(await server.ssrLoadModule(`/src/components/${name}.jsx`)).default;
 const [Header,Discovery,Form,Loading,Generated]=await Promise.all(['SiteHeader','DestinationDiscovery','PlannerForm','DestinationLoading','GeneratedItinerary'].map(load));
 const css=await readFile(new URL('../src/index.css',import.meta.url),'utf8');
 const preferences={...createInitialForm(),destination:'Kyoto',departureCity:'Tokyo',startDate:'2028-04-12',endDate:'2028-04-13',travelers:2,budget:2500,currency:'USD',interests:['culture','food'],travelPace:'balanced'};
 const days=['2028-04-12','2028-04-13'].map((date,index)=>({date,mainActivityCount:2,interestTags:['culture','food'],morning:'A neighborhood walk',afternoon:'A slower afternoon',evening:'Time to unwind',dining:'A neighborhood table',transitAndRest:'Leave a little room between stops for the journey and a quiet break.',dietaryNotes:'Check the menu and ingredients when choosing a restaurant.',mobilityNotes:'Confirm step-free access with each venue.',costs:{accommodation:80,meals:45,localTransport:20,activities:20,departureTravel:10},activities:[{id:`${index}-walk`,title:index?'A garden morning':'A walk along the river',startTime:'09:30',durationMinutes:90,notes:'Start slowly, with time to pause along the way.',kind:'main',fixedTime:false,latitude:null,longitude:null},{id:`${index}-transfer`,title:'Time to get there',startTime:'11:00',durationMinutes:30,notes:'A planning buffer between stops; check the route before leaving.',kind:'transfer',fixedTime:false,latitude:null,longitude:null},{id:`${index}-lunch`,title:'Lunch, without rushing',startTime:'11:30',durationMinutes:60,notes:'Find a table nearby and take your time.',kind:'meal',fixedTime:false,latitude:null,longitude:null},{id:`${index}-gallery`,title:index?'Explore a different neighborhood':'An afternoon gallery visit',startTime:'14:00',durationMinutes:90,notes:'Leave the rest of the afternoon open for something unexpected.',kind:'main',fixedTime:false,latitude:null,longitude:null}]}));
 const result={source:'ai',saved:false,provider:'synthetic-fixture',model:'offline-fixture',status:'planned',vibe:null,destination:'Kyoto',currency:'USD',travelStyle:'',travelPace:'balanced',explanation:'Two days of quiet discoveries, neighborhood tables and room to follow your curiosity.',warnings:['Confirm opening hours and reservations before setting out.'],estimatedTotalGroupCost:350,remainingBudget:2150,days};
 assert.equal(validItinerary(result,preferences),true);
 const noop=()=>{};
 const form=step=>h(Form,{form:step?preferences:createInitialForm(),step,onChange:noop,onToggleInterest:noop,onSubmit:noop,onBack:noop,onGenerateItinerary:noop,loading:false});
 const wrap=(content,plan=false)=>h('div',{className:'page'},h(Header),h('main',{className:`layout journey-layout${plan?' journey-layout--plan':''}`},content));
 const discovery=step=>wrap([h(Discovery,{key:'discovery',destination:step?'Kyoto':'',onSelect:noop}),h('div',{key:'form'},form(step)),h('div',{key:'results',className:'results-wrap','aria-label':'Trip results'})]);
 const screens={discovery:discovery(0),preferences:discovery(1),review:discovery(2),loading:wrap(h(Loading,{destination:'Kyoto',status:'Putting your trip together.',onCancel:noop,cancelLabel:'Cancel planning'}),true),itinerary:wrap(h(Generated,{result,preferences,onEditDay:noop,onRefine:noop,refinement:{}}),true),error:wrap(h(Generated,{error:'timeout',onRetry:noop}),true)};
 const escaped=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const shell=(name,body)=>`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><title>Travel Planner — ${escaped(name)} layout QA</title><style>${css}\n.qa-notice{padding:8px 18px;text-align:center;background:#e7ebdf;font:11px system-ui;color:#304c3d}.qa-notice a{color:inherit}.qa-index{max-width:600px;margin:60px auto;padding:24px}.qa-index a{display:block;padding:14px;color:#214d40}</style></head><body><div class="qa-notice">Preview only · synthetic fixtures · static layout review · <a href="/ __qa/index.html">All screens</a></div>${body}</body></html>`.replace('/ __qa','/__qa');
 await mkdir(output,{recursive:true});
 for(const [name,element] of Object.entries(screens))await writeFile(new URL(`${name}.html`,output),shell(name,renderToStaticMarkup(element)));
 await writeFile(new URL('index.html',output),shell('screens',`<main class="qa-index"><h1>Travel Planner layout review</h1><p>Real components and CSS, rendered offline with synthetic data. Use a 1440px desktop or 390px mobile viewport. These static pages do not exercise auth, form submissions or background jobs.</p>${Object.keys(screens).map(name=>`<a href="${name}.html">${name}</a>`).join('')}<p>Temporary preview artifacts. Remove this directory before final production merge.</p></main>`));
 console.log(JSON.stringify({screens:Object.keys(screens),output:'frontend/public/__qa',networkCalls:0,synthetic:true}));
} finally {globalThis.fetch=originalFetch;await server.close();}
