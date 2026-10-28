import test from 'node:test';
import assert from 'node:assert/strict';
import {createSavedAdaptiveVisualFixture} from '../tools/savedAdaptiveVisualFixtures.mjs';
import {createSavedAdaptiveClient} from '../src/services/savedAdaptiveTrips.js';
import {validateAdaptivePage} from '../src/services/adaptivePlanning.js';
import {savedFixture,saveRequestId,savedId} from './savedAdaptiveFixture.js';
test('synthetic Save browser fixture uses verified production DTOs for all six retained sections and explicit delete',async()=>{
 const fixture=createSavedAdaptiveVisualFixture(),source=savedFixture();
 const fetchImpl=async(path,options={})=>{let result;await fixture.handle({request:()=>({method:()=>options.method||'GET',postDataJSON:()=>JSON.parse(options.body)}),fulfill:value=>{result={status:value.status||200,json:async()=>value.json};}},new URL(path,'http://fixture.local'));return result;};
 const body=await(await fetchImpl('/api/adaptive-plans',{method:'POST',body:JSON.stringify({requestId:source.base.plan.requestId,preferences:source.base.preferences})})).json();assert.equal(validateAdaptivePage(body).plan.version,21);
 const client=createSavedAdaptiveClient({fetchImpl});const params={requestId:saveRequestId,title:'Eighteen days in Kyoto',expectedVersion:21};assert.equal((await client.save(body.plan.id,params)).status,'staging');assert.equal((await client.save(body.plan.id,params)).status,'complete');assert.equal((await client.list()).items.length,1);const first=await client.get(savedId),second=await client.get(savedId,{afterSequence:first.nextCursor});assert.equal(first.sections.length+second.sections.length,6);assert.equal(second.sections.at(-1).endDate,'2028-01-18');assert.equal((await client.remove(savedId,1)).deleted,true);await assert.rejects(client.get(savedId),{code:'SAVED_ADAPTIVE_NOT_FOUND'});assert.equal((await client.list()).items.length,0);
});
