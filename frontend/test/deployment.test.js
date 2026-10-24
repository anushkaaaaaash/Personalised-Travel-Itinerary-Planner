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
test('review-only SPA deployment handles direct detail links and root workspace build',()=>{
  const config=JSON.parse(fs.readFileSync(new URL('../../deployment/vercel.REVIEW_ONLY.json',import.meta.url)));
  assert.equal(config.outputDirectory,'frontend/dist');assert.deepEqual(config.rewrites,[{source:'/(.*)',destination:'/index.html'}]);assert.equal(config.installCommand,'npm ci --ignore-scripts');
});
