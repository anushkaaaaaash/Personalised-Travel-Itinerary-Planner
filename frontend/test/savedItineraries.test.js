import test from 'node:test';
import assert from 'node:assert/strict';
import { savedRequest, snapshot, createSavedOperation } from '../src/services/savedItineraries.js';
import { PlannerRequestError } from '../src/services/readRequest.js';
import { createInitialForm } from '../src/utils/tripPreferences.js';
const id='32345678-1234-1234-1234-123456789abc';
const p={...createInitialForm(),destination:'Kyoto',departureCity:'Tokyo',startDate:'2028-02-28',endDate:'2028-02-28'};
const plan=()=>({source:'ai',saved:false,provider:'Synthetic',model:'fixture',status:'planned',vibe:null,destination:'Kyoto',currency:'USD',travelStyle:'',travelPace:'balanced',explanation:'Synthetic example',warnings:['Verify all details.'],estimatedTotalGroupCost:150,remainingBudget:2350,days:[{date:p.startDate,morning:'Museum',afternoon:'Garden',evening:'Rest',dining:'Cafe',dietaryNotes:'Unspecified',mobilityNotes:'Unspecified',transitAndRest:'Rest between visits',activities:[{id:'a',title:'Museum',startTime:'09:00',durationMinutes:60,notes:'Verify access',latitude:null,longitude:null,fixedTime:false,kind:'main'},{id:'b',title:'Garden',startTime:'11:00',durationMinutes:60,notes:'Verify access',latitude:null,longitude:null,fixedTime:false,kind:'main'}],mainActivityCount:2,interestTags:['culture'],costs:{accommodation:50,meals:30,localTransport:20,activities:20,departureTravel:30}}]});
const meta=()=>({id,title:'Saved test',version:1,createdAt:'2026-01-01T00:00:00Z',updatedAt:'2026-01-01T00:00:00Z'});
const detail=()=>({...meta(),persisted:true,preferences:p,itinerary:plan()});
test('snapshot excludes credentials, provider and transport metadata',()=>{
 const input={...plan(),access_token:'PRIVATE_TOKEN',user_id:'OTHER_OWNER'};
 const record=snapshot(' Saved test ',p,input);
 assert.equal(record.title,'Saved test');assert.equal(JSON.stringify(record).includes('PRIVATE_TOKEN'),false);
 assert.equal(record.itinerary.source,undefined);assert.equal(record.itinerary.provider,undefined);
 assert.equal(input.access_token,'PRIVATE_TOKEN');
});
for(const [action,method] of [['create','POST'],['update','PUT'],['delete','DELETE'],['load','GET']])test(`${action} has explicit method, identity and expected revision`,async()=>{
 let calls=0;
 const result=await savedRequest({action,id,record:snapshot('Saved test',p,plan()),expectedVersion:1},{fetchImpl:async(url,options)=>{
  calls++;assert.equal(options.method,method);
  if(action==='update'||action==='delete')assert.equal(JSON.parse(options.body).version,1);
  return {status:200,json:async()=>action==='delete'?{deleted:true,id,version:1}:{...detail(),version:action==='update'?2:1}};
 }});
 assert.equal(calls,1);assert.equal(result.id,id);
});
test('summary history is separate from detail',async()=>{
 const result=await savedRequest({action:'list'},{fetchImpl:async()=>({status:200,json:async()=>({items:[meta()],hasMore:false,offset:0})})});
 assert.equal(result.items.length,1);assert.equal(result.items[0].itinerary,undefined);
});
for(const status of [401,403,404,409,500,503])test(`storage failure ${status} masks response and never retries`,async()=>{
 let calls=0;
 await assert.rejects(savedRequest({action:'update',id,record:snapshot('Saved test',p,plan()),expectedVersion:1},{fetchImpl:async()=>{calls++;return {status,json:async()=>({error:{message:'PRIVATE_SERVER_KEY'}})};}}),error=>!error.message.includes('PRIVATE_SERVER_KEY'));
 assert.equal(calls,1);
});
test('wrong identity and unconfirmed deletion rejected',async()=>{
 await assert.rejects(savedRequest({action:'load',id},{fetchImpl:async()=>({status:200,json:async()=>({...detail(),id:'42345678-1234-1234-1234-123456789abc'})})}));
 await assert.rejects(savedRequest({action:'delete',id,expectedVersion:1},{fetchImpl:async()=>({status:200,json:async()=>({deleted:false,id,version:1})})}));
});
test('duplicate operation suppressed and late response ignored after signout/unmount',async()=>{
 let finish,calls=0;const states=[];
 const op=createSavedOperation(s=>states.push(s),()=>{calls++;return new Promise(resolve=>finish=resolve);});
 const pending=op.run({action:'create'});
 assert.deepEqual(await op.run({action:'create'}),{ignored:true});
 op.dispose();finish(detail());assert.deepEqual(await pending,{ignored:true});
 assert.equal(calls,1);assert.equal(states.length,1);
});
test('write failure retains local input and reports uncertainty',async()=>{
 const current=plan(),before=JSON.stringify(current),states=[];
 const op=createSavedOperation(s=>states.push(s),async()=>{throw new Error('PRIVATE_NETWORK_DETAIL');});
 const outcome=await op.run({action:'update',record:current});
 assert.match(outcome.error,/unconfirmed/);assert.equal(JSON.stringify(current),before);
 assert.equal(states.at(-1).busy,false);assert.ok(!outcome.error.includes('PRIVATE_NETWORK_DETAIL'));
});
