import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlanningJobsClient, validateJobSnapshot, jobMessage } from '../src/services/planningJobs.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const id = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const requestId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const preferences = { ...createInitialForm(), destination:'Kyoto', departureCity:'Tokyo', startDate:'2028-02-28', endDate:'2028-02-29' };
const snapshot = () => ({ id, requestId, status:'running', result:null, error:null, createdAt:'2028-01-01T00:00:00Z', expiresAt:'2028-01-02T00:00:00Z' });
test('jobs are default off with zero calls', async () => {
  let calls = 0;
  await assert.rejects(createPlanningJobsClient({fetchImpl:()=>calls++}).start(preferences,requestId), {code:'JOB_DISABLED'});
  assert.equal(calls,0);
});
test('one create sends stable request identity; only whitelisted response fields escape', async () => {
  let calls=0;
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async (url,options)=>{
    calls++; assert.equal(url,'/api/planning-jobs');assert.equal(JSON.parse(options.body).requestId,requestId);
    return {status:200,json:async()=>({...snapshot(),private:'SECRET'})};
  }});
  assert.equal((await client.start(preferences,requestId)).private,undefined);assert.equal(calls,1);
});
test('ambiguous creation never retries or leaks response content', async () => {
  let calls=0;
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async()=>{calls++;throw Error('PRIVATE');}});
  await assert.rejects(client.start(preferences,requestId),e=>e.code==='JOB_OUTCOME_UNCONFIRMED'&&!e.message.includes('PRIVATE'));
  assert.equal(calls,1);
});
test('mismatched identity, unknown state and invalid terminal result fail closed', () => {
  for (const mutate of [x=>x.id='bad',x=>x.status='almost done',x=>x.result={},x=>x.expiresAt=x.createdAt,x=>{x.status='succeeded';x.result={};}]) {
    const value=snapshot();mutate(value);assert.throws(()=>validateJobSnapshot(value,preferences),{code:'JOB_INVALID_RESPONSE'});
  }
  assert.throws(()=>validateJobSnapshot(snapshot(),preferences,{id:requestId}),{code:'JOB_INVALID_RESPONSE'});
});
test('cancel is explicit server operation, browser abort is not represented as cancellation', async () => {
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async(url,options)=>{
    assert.equal(url,`/api/planning-jobs/${id}/cancel`);assert.equal(options.method,'POST');
    return {status:200,json:async()=>({...snapshot(),status:'cancelled'})};
  }});
  assert.equal((await client.cancel(id,preferences)).status,'cancelled');
  assert.equal(jobMessage({status:'running'}),'Putting your trip together.');
});
test('lost create response can be reconciled read-only by request identity', async () => {
  let call;
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async(url,options)=>{
    call={url,options};return {status:200,json:async()=>snapshot()};
  }});
  const found=await client.findRequest(requestId,preferences);
  assert.equal(found.id,id);assert.equal(call.options.method,'GET');
  assert.equal(call.url,`/api/planning-jobs/requests/${requestId}`);
});
test('resume rehydrates preferences only from authenticated context and verifies binding', async () => {
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async(url)=>{
    assert.equal(url,`/api/planning-jobs/requests/${requestId}/context`);
    return {status:200,json:async()=>({preferences,job:snapshot()})};
  }});
  const resumed=await client.resumeRequest(requestId);
  assert.equal(resumed.preferences.destination,'Kyoto');assert.equal(resumed.job.id,id);
});
test('expired context contains no retained trip preferences', async () => {
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async()=>({status:200,json:async()=>({preferences:null,job:{...snapshot(),status:'expired'}})})});
  assert.equal((await client.resume(id)).preferences,null);
});
test('server evidence binds exact itinerary and rejects edited dates, venues or forged scope', async () => {
  const { validateBoundEvidence, itineraryEvidenceDigest }=await import('../src/services/planningJobs.js');
  const { createHash }=await import('node:crypto');
  const result={days:[{date:'2028-01-01',activities:[{id:'museum',title:'Museum',startTime:'10:00',durationMinutes:60}]}]};
  const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
  const envelope={version:1,destinationId:'city-id',timeZone:'UTC',itineraryDigest:await itineraryEvidenceDigest(result),
    assessments:[{scope:{destinationId:'city-id',localDate:'2028-01-01',subjectId:'museum',timeZone:'UTC',kind:'closure'},status:'verified',severity:'none',summary:'Official notice checked.',fallback:'Check again before leaving.',sourceURL:'https://official.example/notices',checkedAt:new Date(Date.now()-60000).toISOString(),expiresAt:new Date(Date.now()+60000).toISOString(),validFrom:'2028-01-01',validUntil:'2028-01-01'}]};
  assert.equal((await validateBoundEvidence(envelope,result)).assessments[0].status,'verified');
  const edited=structuredClone(result);edited.days[0].activities[0].title='Another venue';
  await assert.rejects(validateBoundEvidence(envelope,edited),{code:'JOB_INVALID_EVIDENCE'});
  const forged=structuredClone(envelope);forged.assessments[0].scope.subjectId='other';
  await assert.rejects(validateBoundEvidence(forged,result),{code:'JOB_INVALID_EVIDENCE'});
});
test('unsupported duration and definitive rejection never become ambiguous creates', async () => {
  let calls=0;
  const client=createPlanningJobsClient({enabled:true,fetchImpl:async()=>{calls++;return {status:400};}});
  assert.throws(()=>client.start({...preferences,endDate:'2028-03-30'},requestId),{code:'VALIDATION_ERROR'});
  assert.equal(calls,0);
  await assert.rejects(client.start(preferences,requestId),{code:'JOB_REJECTED'});assert.equal(calls,1);
});
