import test from 'node:test';
import assert from 'node:assert/strict';
import {assertQaPreviewOnly} from '../tools/qaPreviewGuard.mjs';
test('temporary QA artifacts cannot enter a Vercel production build',()=>{assert.throws(()=>assertQaPreviewOnly({vercelEnv:'production',hasQaArtifacts:true}),/Remove temporary/);for(const value of [{vercelEnv:'preview',hasQaArtifacts:true},{vercelEnv:'production',hasQaArtifacts:false}])assert.doesNotThrow(()=>assertQaPreviewOnly(value));});
