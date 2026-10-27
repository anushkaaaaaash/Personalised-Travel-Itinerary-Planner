import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {checkFrontendEnvironment} from '../../deployment/frontend_config.mjs';
test('local frontend retains relative API proxy while hosted builds require explicit backend',()=>{
  assert.equal(checkFrontendEnvironment({}),'/api');
  assert.throws(()=>checkFrontendEnvironment({},{hosted:true}),/explicit HTTPS/);
  assert.equal(checkFrontendEnvironment({VITE_API_BASE_URL:'https://api.example.test/api'},{hosted:true}),'https://api.example.test/api');
});
for(const value of ['http://api.example.test/api','https://user:password@api.example.test/api','https://api.example.test/api?key=x','https://api.example.test/wrong','https://api.example.test:8443/api'])test(`reject unsafe frontend API URL ${value}`,()=>assert.throws(()=>checkFrontendEnvironment({VITE_API_BASE_URL:value},{hosted:true})));
test('frontend key-like variables rejected without echoing values',()=>{
  assert.throws(()=>checkFrontendEnvironment({VITE_GROQ_API_KEY:'PRIVATE_SENTINEL'}),e=>!e.message.includes('PRIVATE_SENTINEL'));
});
test('Fly deployment has no Vercel routing dependency',()=>{
  for(const name of ['../vercel.json','../../deployment/vercel.REVIEW_ONLY.json'])assert.equal(fs.existsSync(new URL(name,import.meta.url)),false);
});

test('explicit same-origin hosted build permits only relative /api and still rejects secrets',()=>{
  assert.equal(checkFrontendEnvironment({VITE_API_BASE_URL:'/api'},{hosted:true,sameOrigin:true}),'/api');
  assert.throws(()=>checkFrontendEnvironment({VITE_API_BASE_URL:'/api'},{hosted:true,sameOrigin:'true'}));
  for(const value of ['//evil.example/api','/wrong','http://localhost/api'])assert.throws(()=>checkFrontendEnvironment({VITE_API_BASE_URL:value},{hosted:true,sameOrigin:true}));
  assert.throws(()=>checkFrontendEnvironment({VITE_API_BASE_URL:'/api',VITE_OPENAI_API_KEY:'PRIVATE'},{hosted:true,sameOrigin:true}));
});
