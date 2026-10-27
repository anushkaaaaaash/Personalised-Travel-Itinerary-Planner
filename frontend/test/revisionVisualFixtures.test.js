import test from 'node:test';
import assert from 'node:assert/strict';
import {createRevisionFixture,expenseFixture} from '../tools/revisionVisualFixtures.mjs';
import {validateAdaptivePage} from '../src/services/adaptivePlanning.js';
import {validateRevision} from '../src/services/adaptiveRevision.js';
import {validateAdaptiveExpenses} from '../src/services/adaptiveExpenses.js';
test('synthetic expense and revision mobile fixtures validate whole-retained totals and explicit separate accepted version',()=>{const fixture=createRevisionFixture();for(const revised of [false,true]){const page=validateAdaptivePage(fixture.snapshot(revised));assert.equal(validateAdaptiveExpenses(expenseFixture(page),page).acceptedDays,9);}for(const phase of ['candidate','accepted']){fixture.phase=phase;const row=validateRevision(fixture.revision(),{basePlanId:fixture.base.plan.id,preferences:fixture.base.preferences});assert.equal(row.status,phase);assert.equal(row.accepted,phase==='accepted');}});
