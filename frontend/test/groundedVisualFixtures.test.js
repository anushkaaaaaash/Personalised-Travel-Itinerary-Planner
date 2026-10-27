import test from 'node:test';
import assert from 'node:assert/strict';
import {createGroundedFixture} from '../tools/groundedVisualFixtures.mjs';
import {validateAdaptivePage} from '../src/services/adaptivePlanning.js';
test('on-demand research mobile fixtures obey exact public schema without treating drafts as completed',()=>{
  const fixture=createGroundedFixture();fixture.requestId='22222222-2222-4222-8222-222222222222';
  for(const phase of ['draft-only','researching','draft-three','failed','allowance','unknown','cancelled']){fixture.phase=phase;const value=validateAdaptivePage(fixture.snapshot());assert.equal(value.plan.completedDays,3);assert.equal(value.sections.length,1);if(phase==='draft-only')assert.equal(value.research,null);if(phase==='draft-three')assert.equal(value.draft.days.length,3);if(phase==='allowance')assert.equal(value.plan.pauseReason,'RESEARCH_ALLOWANCE_REACHED');}
});
