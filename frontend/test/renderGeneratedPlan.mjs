// Python integration bridge: actual serialized FastAPI result, no network.
import assert from 'node:assert/strict';
import React from 'react';
import {act,create} from 'react-test-renderer';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {validItinerary} from '../src/services/itineraries.js';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {result,preferences}=JSON.parse(input);
assert.equal(validItinerary(result,preferences),true);
const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
let renderer;
globalThis.fetch=()=>{throw Error('Network forbidden');};
try{
 const {default:Generated}=await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');
 await act(async()=>{renderer=create(React.createElement(Generated,{result,preferences}));});
 const text=JSON.stringify(renderer.toJSON());
 const cards=renderer.root.findAll(n=>n.type==='article'&&n.props.className==='card day-card');
 assert.equal(cards.length,result.days.length);assert.ok(cards.length>1);
 for(const day of result.days){assert.ok(text.includes(day.date));for(const activity of day.activities){assert.ok(text.includes(activity.startTime));assert.ok(text.includes(JSON.stringify(activity.title).slice(1,-1)));}}
 for(const warning of result.warnings)assert.ok(text.includes(JSON.stringify(warning).slice(1,-1)));
 assert.ok(text.includes('Schedule times are computed'));
 console.log(JSON.stringify({days:cards.length,mounted:true,liveCalls:0}));
}finally{if(renderer)await act(async()=>renderer.unmount());await server.close();}
