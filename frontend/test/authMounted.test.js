import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

test('mounted auth form blocks duplicate/cooldown submits, preserves mode and cleans up', async () => {
  const server = await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const original={fetch:globalThis.fetch,now:Date.now,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
  const intervals=new Map(); let nextId=0,now=100000,renderer,finish,signal;
  const calls=[];
  try {
    Date.now=()=>now;
    globalThis.setInterval=callback=>{const id=++nextId;intervals.set(id,callback);return id;};
    globalThis.clearInterval=id=>intervals.delete(id);
    globalThis.fetch=async(url,options)=>{
      if(url==='/api/auth/config')return {status:200,json:async()=>({enabled:true,mode:'production',ownership_enabled:false,saved_only:true})};
      assert.ok(['/api/auth/login','/api/auth/register'].includes(url),'Unexpected request must never reach a real transport');
      calls.push(url); signal=options.signal;
      return new Promise(resolve=>{finish=resolve;});
    };
    const {default:Boundary}=await server.ssrLoadModule('/src/components/AuthBoundary.jsx');
    await act(async()=>{renderer=create(React.createElement(Boundary));});
    const submit=()=>renderer.root.findByType('form').props.onSubmit({preventDefault(){}});
    const primary=()=>renderer.root.findAllByType('button').find(node=>node.props.className==='generate-btn');
    const switchMode=()=>renderer.root.findAllByType('button').find(node=>node.props.type==='button');
    const text=()=>JSON.stringify(renderer.toJSON());
    const fill=()=>{for(const input of renderer.root.findAllByType('input'))input.props.onChange({target:{value:input.props.type==='email'?'fixture@example.invalid':'synthetic-password'}});};
    await act(async()=>{switchMode().props.onClick();});
    assert.equal(primary().props.children,'Register account');
    await act(async()=>{fill();});
    let pending;
    await act(async()=>{pending=submit();void submit();});
    assert.deepEqual(calls,['/api/auth/register']);assert.equal(primary().props.disabled,true);
    await act(async()=>{finish({status:429,headers:{get:()=> '2'},json:async()=>({error:{message:'PRIVATE_ERROR'}})});await pending;});
    assert.match(text(),/paused for.*2/);assert.doesNotMatch(text(),/PRIVATE_ERROR/);
    await act(async()=>{switchMode().props.onClick();void submit();});
    assert.equal(primary().props.children,'Sign in');assert.equal(primary().props.disabled,true);assert.equal(calls.length,1);
    await act(async()=>{now+=1000;for(const tick of intervals.values())tick();});
    assert.match(text(),/paused for.*1/);assert.equal(primary().props.disabled,true);
    await act(async()=>{now+=1000;for(const tick of [...intervals.values()])tick();});
    assert.equal(primary().props.disabled,false);assert.equal(intervals.size,0);assert.equal(calls.length,1);
    await act(async()=>{switchMode().props.onClick();fill();});
    await act(async()=>{pending=submit();});
    await act(async()=>{finish({status:401,json:async()=>({error:{message:'PRIVATE_ERROR'}})});await pending;});
    assert.match(text(),/Registration could not be completed/);
    assert.equal(primary().props.children,'Register account');
    await act(async()=>{fill();pending=submit();});
    await act(async()=>{finish({status:200,json:async()=>({pending_confirmation:true})});await pending;});
    assert.match(text(),/does not verify account creation or email delivery/);
    assert.equal(primary().props.children,'Register account');
    await act(async()=>{fill();pending=submit();});
    await act(async()=>{finish({status:429,json:async()=>({})});await pending;});
    assert.match(text(),/paused for.*60/);assert.equal(intervals.size,1);
    await act(async()=>{renderer.unmount();});renderer=null;
    assert.equal(intervals.size,0);

    // A separate mount verifies cleanup during an unfinished request, not just a timer.
    await act(async()=>{renderer=create(React.createElement(Boundary));});
    await act(async()=>{fill();pending=submit();});
    assert.equal(signal.aborted,false);
    await act(async()=>{renderer.unmount();});renderer=null;
    assert.equal(signal.aborted,true);
    await act(async()=>{finish({status:429,json:async()=>({})});await pending;});
    assert.equal(intervals.size,0);
  } finally {
    if(renderer)await act(async()=>renderer.unmount());
    globalThis.fetch=original.fetch;Date.now=original.now;
    globalThis.setInterval=original.setInterval;globalThis.clearInterval=original.clearInterval;
    await server.close();
  }
});
