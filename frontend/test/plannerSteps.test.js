import test from 'node:test';
import assert from 'node:assert/strict';
import { createInitialForm, buildTripPayload } from '../src/utils/tripPreferences.js';
import { PLANNER_STEPS, FINAL_STEP, validatePlannerStep, nextPlannerStep, firstErrorStep } from '../src/utils/plannerSteps.js';
import { PREFERENCE_FIELDS } from '../../shared/tripPreferences.mjs';

const validForm = () => ({ ...createInitialForm(), destination: 'Kyoto', departureCity: 'Mumbai',
  startDate: '2028-02-28', endDate: '2028-02-29' });

test('every preference belongs to exactly one editable step', () => {
  const fields = PLANNER_STEPS.flatMap(({ fields }) => fields);
  assert.equal(new Set(fields).size, fields.length);
  assert.deepEqual([...fields].sort(), [...PREFERENCE_FIELDS].sort());
});

test('first step reports only its errors and blocks advancement', () => {
  const result = nextPlannerStep({ ...createInitialForm(), budget: '' }, 0);
  assert.equal(result.step, 0);
  assert.ok(result.errors.destination);
  assert.ok(result.errors.startDate);
  assert.ok(!result.errors.budget);
});

test('valid earlier step advances despite incomplete future preferences', () => {
  assert.deepEqual(nextPlannerStep({ ...validForm(), budget: '' }, 0), { step: 1, errors: {} });
});

test('preferences step rejects invalid amounts and counts without losing values', () => {
  const form = { ...validForm(), budget: '', travelers: '2.5' };
  const before = structuredClone(form);
  const result = nextPlannerStep(form, 1);
  assert.equal(result.step, 1);
  assert.ok(result.errors.budget);
  assert.ok(result.errors.travelers);
  assert.deepEqual(form, before);
});

test('navigation validation preserves form and exact final API payload', () => {
  const form = validForm();
  const before = structuredClone(form);
  const payload = buildTripPayload(form).value;
  assert.equal(nextPlannerStep(form, 0).step, 1);
  assert.equal(nextPlannerStep(form, 1).step, FINAL_STEP);
  assert.equal(nextPlannerStep(form, FINAL_STEP).step, FINAL_STEP);
  assert.deepEqual(form, before);
  assert.deepEqual(buildTripPayload(form).value, payload);
});

test('final review validates all steps and routes to earliest invalid field', () => {
  const errors = validatePlannerStep({ ...validForm(), destination: '', budget: 0 }, FINAL_STEP);
  assert.ok(errors.destination);
  assert.ok(errors.budget);
  assert.equal(firstErrorStep(errors), 0);
  assert.equal(firstErrorStep({ budget: 'Invalid' }), 1);
  assert.equal(firstErrorStep({ form: 'Invalid' }), 0);
  assert.equal(firstErrorStep({}), FINAL_STEP);
});

test('date ordering is validated on trip-details step', () => {
  assert.ok(validatePlannerStep({ ...validForm(), endDate: '2028-02-27' }, 0).endDate);
});

test('optional style and mobility errors block their step and route back there', () => {
  const form = { ...validForm(), travelStyle: 'unknown', mobilityConcerns: 'x'.repeat(501) };
  assert.equal(nextPlannerStep(form, 0).step, 1);
  const result = nextPlannerStep(form, 1);
  assert.equal(result.step, 1);
  assert.ok(result.errors.travelStyle);
  assert.ok(result.errors.mobilityConcerns);
  assert.equal(firstErrorStep(result.errors), 1);
});

test('reported 24-day trip is blocked before Review without changing its dates',()=>{
  const form={...validForm(),startDate:'2026-10-27',endDate:'2026-11-19'};const before=structuredClone(form);
  const first=nextPlannerStep(form,0);assert.equal(first.step,0);assert.match(first.errors.endDate,/24 days/);
  assert.match(validatePlannerStep(form,FINAL_STEP).endDate,/1–14 days/);assert.deepEqual(form,before);
});
test('planning duration is inclusive across month/year/leap boundaries',()=>{
  for(const [start,end] of [['2026-12-25','2027-01-07'],['2028-02-20','2028-03-04'],['2026-10-27','2026-10-27']])assert.equal(validatePlannerStep({...validForm(),startDate:start,endDate:end},0).endDate,undefined);
  assert.match(validatePlannerStep({...validForm(),startDate:'2026-12-25',endDate:'2027-01-08'},0).endDate,/15 days/);
});
