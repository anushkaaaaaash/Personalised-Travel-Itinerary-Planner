import test from 'node:test';
import assert from 'node:assert/strict';
import { savedRequest, snapshot, createSavedOperation, createPendingSaveRecovery } from '../src/services/savedItineraries.js';
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

test('uncertain create then confirmed 404 permits only explicit same-ID original-snapshot retry',async()=>{
 const recovery=createPendingSaveRecovery(),record=snapshot('Saved test',p,plan());
 const original=JSON.stringify(record),calls=[];
 recovery.begin(id,record);
 const request=(input,options)=>savedRequest(input,{...options,fetchImpl:async(url,options)=>{
  calls.push({url,options});
  if(calls.length===1)throw new Error('PRIVATE_NETWORK_FAILURE');
  if(calls.length===2)return {status:404,json:async()=>({error:{message:'PRIVATE_DETAIL'}})};
  assert.deepEqual(JSON.parse(options.body),{...JSON.parse(original),id});
  return {status:200,json:async()=>detail()};
 }});
 const op=createSavedOperation(()=>{},request);
 recovery.reconcile(id,await op.run({action:'create',id,record}));
 assert.equal(recovery.view().retryAllowed,false);assert.throws(()=>recovery.retry());
 // Edits made after the uncertain request must not alter its stored retry snapshot.
 record.title='New local title';record.itinerary.days[0].activities[0].notes='New local note';
 const edited=JSON.stringify(record);
 const absent=await op.run({action:'load',id});assert.equal(absent.status,404);
 recovery.reconcile(id,absent,{checked:true});
 assert.equal(recovery.view().retryAllowed,true);assert.equal(calls.length,2);
 const retry=recovery.retry();assert.equal(retry.id,id);assert.equal(JSON.stringify(retry.record),original);
 assert.throws(()=>recovery.retry()); // double click cannot obtain a second retry
 recovery.reconcile(id,await op.run(retry));
 assert.equal(recovery.view(),null);assert.equal(calls.length,3);assert.equal(JSON.stringify(record),edited);
});

test('successful pending reconciliation resolves metadata only and preserves newer editor and selection',()=>{
 const recovery=createPendingSaveRecovery(),record=snapshot('Saved test',p,plan());
 recovery.begin(id,record);
 const editor={...record,title:'Newer local work'},selected={id:'42345678-1234-1234-1234-123456789abc',version:8};
 const before=JSON.stringify({editor,selected});
 const result=recovery.reconcile(id,{result:detail()},{checked:true});
 assert.deepEqual(result,{resolved:true});assert.equal(result.result,undefined);
 assert.equal(JSON.stringify({editor,selected}),before);assert.equal(recovery.view(),null);
});

test('network, auth, server errors and ignored checks never authorize a retry',async()=>{
 for(const status of [401,403,500,503,undefined]) {
  const recovery=createPendingSaveRecovery();recovery.begin(id,snapshot('Saved test',p,plan()));
  const op=createSavedOperation(()=>{},(input,options)=>savedRequest(input,{...options,fetchImpl:async()=>{
   if(status===undefined)throw new Error('network');
   return {status,json:async()=>({error:{message:'not found PRIVATE'}})};
  }}));
  recovery.reconcile(id,await op.run({action:'load',id}),{checked:true});
  assert.equal(recovery.view().retryAllowed,false);assert.throws(()=>recovery.retry());
  recovery.reconcile(id,{ignored:true,status:404},{checked:true});assert.equal(recovery.view().retryAllowed,false);
 }
});

test('late first commit conflicts with same-ID retry and is reconciled without another insert',async()=>{
 const recovery=createPendingSaveRecovery(),record=snapshot('Saved test',p,plan());
 recovery.begin(id,record);recovery.reconcile(id,{error:'missing',status:404},{checked:true});
 const calls=[];
 const op=createSavedOperation(()=>{},(input,options)=>savedRequest(input,{...options,fetchImpl:async(url,options)=>{
  calls.push(options.method);
  if(options.method==='POST'){
   assert.equal(JSON.parse(options.body).id,id);
   return {status:409,json:async()=>({error:{message:'duplicate'}})};
  }
  return {status:200,json:async()=>detail()};
 }}));
 recovery.reconcile(id,await op.run(recovery.retry()));
 assert.equal(recovery.view().retryAllowed,false);
 recovery.reconcile(id,await op.run({action:'load',id}),{checked:true});
 assert.equal(recovery.view(),null);assert.deepEqual(calls,['POST','GET']);
});

test('logout/disposal and wrong-operation results cannot revive pending recovery',async()=>{
 const recovery=createPendingSaveRecovery();recovery.begin(id,snapshot('Saved test',p,plan()));
 let finish;const op=createSavedOperation(()=>{},()=>new Promise(resolve=>finish=resolve));
 const loading=op.run({action:'load',id});
 assert.deepEqual(await op.run({action:'load',id}),{ignored:true});
 assert.deepEqual(recovery.reconcile('42345678-1234-1234-1234-123456789abc',{status:404},{checked:true}),{ignored:true});
 op.dispose();recovery.dispose();finish(detail());
 assert.deepEqual(recovery.reconcile(id,await loading,{checked:true}),{ignored:true});
 assert.equal(recovery.view(),null);assert.throws(()=>recovery.retry());
});

for(const status of [400,413,422])test(`initial pre-storage ${status} rejection permits corrected explicit new save`,async()=>{
 const recovery=createPendingSaveRecovery(),record=snapshot('Saved test',p,plan()),calls=[];
 const code=status===413?'REQUEST_TOO_LARGE':'VALIDATION_ERROR';
 const nextId='42345678-1234-1234-1234-123456789abc';
 const op=createSavedOperation(()=>{},(input,options)=>savedRequest(input,{...options,fetchImpl:async(url,options)=>{
  calls.push(JSON.parse(options.body));
  if(calls.length===1)return {status,json:async()=>({error:{code,message:'PRIVATE_RAW_VALIDATION'}})};
  return {status:200,json:async()=>({...detail(),id:nextId})};
 }}));
 recovery.begin(id,record);
 const before=JSON.stringify(record),failure=await op.run({action:'create',id,record});
 assert.equal(failure.code,code);assert.ok(!failure.error.includes('PRIVATE_RAW_VALIDATION'));
 assert.deepEqual(recovery.reconcile(id,failure,{initial:true}),{rejected:true});
 assert.equal(recovery.view(),null);assert.equal(JSON.stringify(record),before);assert.equal(calls.length,1);
 record.itinerary.days[0].activities[0].notes='Shorter corrected note';
 recovery.begin(nextId,record); // a new operation only after the user's correction and explicit save
 recovery.reconcile(nextId,await op.run({action:'create',id:nextId,record}),{initial:true});
 assert.equal(recovery.view(),null);assert.equal(calls.length,2);
 assert.equal(calls[1].id,nextId);assert.equal(calls[1].itinerary.days[0].activities[0].notes,'Shorter corrected note');
});

test('validation failure on retry after uncertainty retains the original operation',async()=>{
 const recovery=createPendingSaveRecovery(),record=snapshot('Saved test',p,plan());
 recovery.begin(id,record);
 recovery.reconcile(id,{error:'timeout'},{initial:true});
 recovery.reconcile(id,{error:'not found',status:404},{checked:true});
 const retry=recovery.retry();assert.equal(retry.id,id);
 const op=createSavedOperation(()=>{},(input,options)=>savedRequest(input,{...options,fetchImpl:async()=>({status:400,json:async()=>({error:{code:'VALIDATION_ERROR'}})})}));
 const failure=await op.run(retry);
 assert.deepEqual(recovery.reconcile(id,failure),{resolved:false});
 assert.equal(recovery.view().id,id);assert.equal(recovery.view().retryAllowed,false);
 assert.throws(()=>recovery.begin('42345678-1234-1234-1234-123456789abc',record));
 recovery.reconcile(id,{result:detail()},{checked:true});assert.equal(recovery.view(),null);
});

test('unknown codes or incompatible statuses cannot masquerade as initial validation rejection',async()=>{
 for(const [status,code] of [[400,'PRIVATE_KEY'],[400,undefined],[500,'VALIDATION_ERROR'],[413,'VALIDATION_ERROR']]) {
  const recovery=createPendingSaveRecovery();recovery.begin(id,snapshot('Saved test',p,plan()));
  const op=createSavedOperation(()=>{},(input,options)=>savedRequest(input,{...options,fetchImpl:async()=>({status,json:async()=>({error:{code,message:'PRIVATE'}})})}));
  const failure=await op.run({action:'create',id,record:snapshot('Saved test',p,plan())});
  assert.ok(!JSON.stringify(failure).includes('PRIVATE'));
  recovery.reconcile(id,failure,{initial:true});assert.equal(recovery.view().id,id);
 }
});
