import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdaptiveExportController} from '../src/services/adaptiveExport.js';
const id='11111111-1111-4111-8111-111111111111';
const bytes=new TextEncoder().encode('%PDF-1.4\nBinary PDF fixture\n%%EOF\n');
function setup({data=bytes,headers={},resource}={}){const files=[];const identity={user:{id:'owner'}};let state;const c=createAdaptiveExportController({resource,getIdentity:()=>identity,subscribe:()=>()=>{},save:(blob,name)=>files.push({blob,name}),onStateChange:s=>state=s,fetchImpl:async(url,options)=>{assert.equal(options.method,'GET');assert.equal(options.headers.Accept,'application/pdf');assert.equal(url,`/api/${resource||'adaptive-plans'}/${id}/export`);return new Response(data,{headers:{'content-type':'application/pdf','content-length':data.length,...headers}});}});return {c,files,state:()=>state};}
test('default download is an actual PDF, including independent saved trip endpoint',async()=>{for(const resource of ['adaptive-plans','saved-adaptive-trips']){const {c,files}=setup({resource});try{assert.equal((await c.download(id)).downloaded,true);assert.equal(files[0].blob.type,'application/pdf');assert.match(files[0].name,/\.pdf$/);assert.deepEqual(new Uint8Array(await files[0].blob.arrayBuffer()),bytes);}finally{c.dispose();}}});
test('PDF errors, truncated responses and length mismatches never create files',async()=>{for(const options of [{data:bytes.slice(0,-4)},{data:new TextEncoder().encode('not a PDF\n%%EOF\n')},{headers:{'content-length':bytes.length+1}},{headers:{'content-type':'text/plain'}}]){const {c,files}=setup(options);try{assert.equal((await c.download(id)).error,true);assert.equal(files.length,0);}finally{c.dispose();}}});

test('visible snapshot PDF is bounded, read-only and never saves truncated content',async()=>{
  const {downloadSnapshotPdf}=await import('../src/services/snapshotPdf.js');
  for(const valid of [true,false]){let saved=0;const operation=downloadSnapshotPdf({status:'planned',days:[]},{destination:'Paris'},{fetchImpl:async(url,options)=>{assert.equal(url,'/api/itineraries/export-pdf');assert.equal(options.method,'POST');assert.deepEqual(JSON.parse(options.body).itinerary.days,[]);return new Response(valid?bytes:bytes.slice(0,-3),{headers:{'content-type':'application/pdf'}});},save:()=>saved++});if(valid)await operation;else await assert.rejects(operation);assert.equal(saved,valid?1:0);}
});
