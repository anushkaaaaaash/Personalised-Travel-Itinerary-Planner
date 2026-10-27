import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdaptiveFixture} from '../tools/adaptiveVisualFixtures.mjs';
import {validateAdaptivePage} from '../src/services/adaptivePlanning.js';
import {preferences} from './shareFixture.js';

const requestId='22345678-1234-1234-1234-123456789abc';
const fullTrip={...preferences,destination:'Japan',departureCity:'Mumbai',startDate:'2028-01-01',endDate:'2028-02-15'};

test('adaptive visual states obey the actual bounded-page contract and preserve all 46 days',()=>{
  const fixture=createAdaptiveFixture();fixture.preferences=fullTrip;fixture.requestId=requestId;
  for(const phase of ['active','allowance','constraint','unknown','cancelled']) {
    fixture.phase=phase;const value=validateAdaptivePage(fixture.snapshot(),{requestId});
    assert.equal(value.plan.totalDays,46);assert.equal(value.preferences.endDate,'2028-02-15');
    assert.equal(value.plan.completedDays,phase==='active'?3:9);assert.ok(value.sections.length<=3);
    assert.equal(value.plan.spentCents,value.sections.reduce((sum,section)=>sum+section.checkpoint.spentCents,0));
    if(phase==='constraint'){assert.equal(value.plan.pauseReason,'SECTION_FAILED');assert.equal(value.plan.activeSection.errorCode,'SECTION_CONSTRAINT_CONFLICT');assert.equal(value.plan.activeSection.failureDetails.applicability,'proposed');}
  }
});

test('synthetic cancellation stays pending until explicitly acknowledged and reads never create work',async()=>{
  const fixture=createAdaptiveFixture();let last;
  const route=(method,body)=>({request:()=>({method:()=>method,postDataJSON:()=>body}),fulfill:async value=>{last=value;}});
  await fixture.handle(route('POST',{preferences:fullTrip,requestId}),new URL('http://127.0.0.1/api/adaptive-plans'));
  const id=last.json.plan.id;fixture.phase='constraint';
  await fixture.handle(route('GET'),new URL(`http://127.0.0.1/api/adaptive-plans/${id}`));
  assert.equal(fixture.requests.filter(item=>item.method==='POST').length,1);
  await fixture.handle(route('POST',{}),new URL(`http://127.0.0.1/api/adaptive-plans/${id}/cancel`));
  assert.equal(fixture.phase,'constraint');assert.equal(last.json.plan.status,'paused');
  await fixture.pendingCancel();assert.equal(last.json.plan.status,'cancelled');
});

test('completed export fixture covers all requested dates and retains a valid bounded page',()=>{
  const fixture=createAdaptiveFixture();fixture.phase='completed';fixture.preferences={...fullTrip,endDate:'2028-01-03'};fixture.requestId=requestId;
  const value=validateAdaptivePage(fixture.snapshot());assert.equal(value.plan.status,'completed');assert.equal(value.plan.completedDays,3);assert.equal(value.plan.totalDays,3);assert.equal(value.sections.length,1);assert.equal(value.sections[0].checkpoint.endLocation,'Mumbai');
});

test('completed mobile fixture permits a true final transfer day without a main-activity quota',()=>{
  const fixture=createAdaptiveFixture();fixture.phase='completed';fixture.finalTravelDay=true;fixture.preferences={...fullTrip,endDate:'2028-01-03',travelPace:'fast'};fixture.requestId=requestId;
  const value=validateAdaptivePage(fixture.snapshot());const days=value.sections[0].checkpoint.itinerary.days;assert.deepEqual(days.map(day=>day.mainActivityCount),[3,3,0]);assert.equal(days[2].activities[0].kind,'transfer');assert.equal(days[2].activities[0].durationMinutes,120);assert.equal(value.plan.completedDays,3);
});

test('owner recovery fixture discovers only a retained plan and never creates or changes it on reads',async()=>{
  const fixture=createAdaptiveFixture();fixture.phase='constraint';fixture.preferences=fullTrip;fixture.requestId=requestId;fixture.startError='SECTION_OWNER_PLAN_EXISTS';let last;
  const route=(method,body)=>({request:()=>({method:()=>method,postDataJSON:()=>body}),fulfill:async value=>{last=value;}});
  const current=new URL('http://127.0.0.1/api/adaptive-plans/current');
  await fixture.handle(route('GET'),current);assert.equal(last.status,404);assert.equal(last.json.error.code,'SECTION_CURRENT_NOT_FOUND');
  await fixture.handle(route('POST',{preferences:{...fullTrip,destination:'France'},requestId:'other'}),new URL('http://127.0.0.1/api/adaptive-plans'));
  assert.equal(last.status,429);assert.equal(last.json.error.code,'SECTION_OWNER_PLAN_EXISTS');
  await fixture.handle(route('GET'),current);assert.equal(validateAdaptivePage(last.json).preferences.destination,'Japan');assert.equal(fixture.requestId,requestId);assert.equal(fixture.requests.filter(item=>item.method==='POST').length,1);
  fixture.startError='SECTION_CAPACITY_LIMIT';await fixture.handle(route('POST'),new URL('http://127.0.0.1/api/adaptive-plans'));assert.equal(last.json.error.code,'SECTION_CAPACITY_LIMIT');
});
