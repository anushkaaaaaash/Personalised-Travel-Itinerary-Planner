import test from 'node:test';
import assert from 'node:assert/strict';
import { authFailure } from '../src/services/authFeedback.js';
import { requestJson } from '../src/services/readRequest.js';
import { getSession, setSession } from '../src/services/session.js';

test('network/CORS-like fetch failures give connectivity guidance without diagnosing credentials or retrying',async()=>{
  let calls=0;
  await assert.rejects(requestJson('/auth/config',{failure:authFailure,fetchImpl:async()=>{calls++;throw new TypeError('PRIVATE_NETWORK_DETAIL');}}),error=>{
    assert.match(error.message,/could not be reached/);
    assert.match(error.message,/site address is allowed/);
    assert.doesNotMatch(error.message,/PRIVATE_NETWORK_DETAIL/);
    return true;
  });
  assert.equal(calls,1);
});

test('different rejected-account bodies receive the same neutral feedback',async()=>{
  const messages=[];
  for(const code of ['invalid_credentials','email_not_confirmed','user_not_found']) {
    await assert.rejects(requestJson('/auth/login',{failure:authFailure,fetchImpl:async()=>({status:401,json:async()=>({error:{code,message:'PRIVATE_ACCOUNT_DETAIL'}})})}),error=>{messages.push(error.message);return true;});
  }
  assert.equal(new Set(messages).size,1);
  assert.match(messages[0],/Sign-in could not be verified/);
  assert.doesNotMatch(messages[0],/PRIVATE_ACCOUNT_DETAIL|user_not_found/);
});

test('unauthorized response still clears an expired memory session with neutral feedback',async()=>{
  const original=globalThis.fetch;
  try {
    setSession({access_token:'synthetic-test-token',expires_at:Date.now()/1000+60});
    globalThis.fetch=async()=>({status:401,json:async()=>({error:{code:'AUTH_REQUIRED'}})});
    await assert.rejects(requestJson('/auth/logout',{failure:authFailure}),/session expired, sign in again/);
    assert.equal(getSession(),null);
  } finally {globalThis.fetch=original;setSession(null);}
});

test('valid production configuration still passes through unchanged',async()=>{
  const config={enabled:true,mode:'production',ownership_enabled:false,saved_only:true};
  assert.deepEqual(await requestJson('/auth/config',{failure:authFailure,fetchImpl:async()=>({status:200,json:async()=>config})}),config);
});

for(const [status,pattern] of [[503,/not configured/],[429,/Too many attempts/],[504,/timed out/],[403,/blocked/],[502,/could not complete/],[422,/form details/]]) {
  test(`auth HTTP ${status} uses fixed distinct feedback`,()=>assert.match(authFailure(status,{message:'PRIVATE_DETAIL'}),pattern));
}
test('unreadable auth response is not blamed on credentials',async()=>{
  await assert.rejects(requestJson('/auth/config',{failure:authFailure,fetchImpl:async()=>({status:200,json:async()=>{throw new Error('PRIVATE_BODY');}})}),/unreadable response/);
});
