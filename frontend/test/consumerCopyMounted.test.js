import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {plan,preferences} from './shareFixture.js';
const forbidden=/\bAI\b|\bprovider\b|\bmodel\b|not saved|does not save|JSON\s*(upload|import)|Upload\s*JSON/i;
function visible(node){if(typeof node==='string')return node;if(!node)return '';if(Array.isArray(node))return node.map(visible).join(' ');return [node.type==='textarea'?node.props.value:'',...(node.children||[]).map(visible)].join(' ');}
test('mounted consumer journey and sharing show only travel-focused copy',async()=>{
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});const original=globalThis.fetch;let renderer,finish;
 try{
  globalThis.fetch=async()=>new Promise(resolve=>{finish=resolve;});
  const {default:Page}=await server.ssrLoadModule('/src/pages/PlannerPage.jsx');const {default:Form}=await server.ssrLoadModule('/src/components/PlannerForm.jsx');
  await act(async()=>{renderer=create(React.createElement(Page));});const clean=()=>assert.doesNotMatch(visible(renderer.toJSON()),forbidden);const props=()=>renderer.root.findByType(Form).props;clean();
  await act(async()=>{for(const name of ['destination','departureCity','startDate','endDate','budget','currency','travelers'])props().onChange({target:{name,value:preferences[name]}});});await act(async()=>props().onSubmit({preventDefault(){}}));clean();await act(async()=>props().onSubmit({preventDefault(){}}));clean();await act(async()=>props().onGenerateItinerary());clean();
  await act(async()=>finish({status:200,json:async()=>plan()}));clean();
  await act(async()=>renderer.root.findAllByType('button').find(n=>n.children.some(child=>typeof child==='string'&&child.includes('Copy summary'))).props.onClick());clean();
  assert.match(visible(renderer.toJSON()),/Check current prices/);
 }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.fetch=original;await server.close();}
});

test('ordinary route import graph cannot reach preserved developer panels',async()=>{
 const visited=new Set();async function visit(file){if(visited.has(file))return;visited.add(file);const code=await readFile(file,'utf8');for(const match of code.matchAll(/(?:from\s*|import\s*)['"](\.[^'"]+)['"]/g)){const target=path.resolve(path.dirname(file),match[1]);if(/\.(jsx?|mjs)$/.test(target))await visit(target);}}
 await visit(fileURLToPath(new URL('../src/App.jsx',import.meta.url)));
 for(const name of ['RecommendationResults','TripHistory','ItineraryResults','CoordinateConfirmation','RouteSummary','ImportItinerary'])assert.ok(![...visited].some(file=>file.endsWith(`/${name}.jsx`)),`${name} must stay out of consumer routes`);
});
