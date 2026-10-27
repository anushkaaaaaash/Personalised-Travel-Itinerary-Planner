import test from 'node:test';
import assert from 'node:assert/strict';
import {assertQaPreviewOnly} from '../tools/qaPreviewGuard.mjs';
test('temporary QA artifacts cannot enter any production build',()=>{assert.throws(()=>assertQaPreviewOnly({production:true,hasQaArtifacts:true}),/Remove temporary/);for(const value of [{production:false,hasQaArtifacts:true},{production:true,hasQaArtifacts:false}])assert.doesNotThrow(()=>assertQaPreviewOnly(value));});
