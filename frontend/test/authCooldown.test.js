import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuthCooldown } from '../src/services/authCooldown.js';
import { authFailure } from '../src/services/authFeedback.js';
import { requestJson } from '../src/services/readRequest.js';
import { sessionFetch, setSession, subscribeSession } from '../src/services/session.js';

test('registration rejection is neutral and does not claim a sign-in or delivered email', () => {
  const message = authFailure(401, {message:'PRIVATE_PROVIDER_DETAIL'}, 'register');
  assert.match(message, /Registration could not be completed/);
  assert.match(message, /have not been verified/);
  assert.doesNotMatch(message, /Sign-in could|PRIVATE_PROVIDER_DETAIL/);
  assert.match(authFailure(401), /Sign-in could not be verified/);
});

test('429 passes only bounded seconds and makes a single request', async () => {
  for (const [header, expected] of [['3600',3600],['86400',86400],['86401',undefined],['-2',undefined],['0',undefined],['PRIVATE_VALUE',undefined],[null,undefined]]) {
    let calls=0;
    await assert.rejects(requestJson('/auth/register', {
      failure: (status, diagnostic) => authFailure(status, diagnostic, 'register'),
      fetchImpl: async () => {calls++; return {status:429,headers:{get:()=>header},json:async()=>({error:{message:'PRIVATE_BODY'}})};},
    }), error => {
      assert.equal(error.status,429); assert.equal(error.retryAfterSeconds,expected);
      assert.doesNotMatch(error.message,/PRIVATE_/); return true;
    });
    assert.equal(calls,1);
  }
});

test('cooldown gates successive manual submits without automatic retry or mode-dependent reset', () => {
  let now=1000, calls=0;
  const cooldown=createAuthCooldown(()=>now);
  const submit=()=>{if(cooldown.remaining())return; calls++;};
  submit(); cooldown.record({status:429,retryAfterSeconds:3600});
  submit(); submit(); assert.equal(calls,1);
  now+=3599001; assert.equal(cooldown.remaining(),1); submit(); assert.equal(calls,1);
  now+=999; assert.equal(cooldown.remaining(),0); assert.equal(calls,1);
  submit(); assert.equal(calls,2);
});

test('missing or invalid delay uses a conservative UI pause and never shortens an existing delay', () => {
  let now=0; const cooldown=createAuthCooldown(()=>now);
  cooldown.record({status:401,retryAfterSeconds:3600}); assert.equal(cooldown.remaining(),0);
  cooldown.record({status:429,retryAfterSeconds:'PRIVATE_VALUE'}); assert.equal(cooldown.remaining(),60);
  cooldown.record({status:429,retryAfterSeconds:3600}); now+=1000;
  cooldown.record({status:429,retryAfterSeconds:1}); assert.equal(cooldown.remaining(),3599);
});

test('signed-out registration 401 does not broadcast another logout or reset planner state', async () => {
  const original=globalThis.fetch; setSession(null); let changes=0;
  const unsubscribe=subscribeSession(()=>changes++);
  try {
    globalThis.fetch=async()=>({status:401});
    await sessionFetch('/api/auth/register'); assert.equal(changes,0);
  } finally {unsubscribe();globalThis.fetch=original;}
});
