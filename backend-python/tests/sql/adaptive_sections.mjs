// Offline per-section checkpoint persistence proof. No database URL or live services.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
const {PGlite}=await import(process.env.PLANNING_SQL_TEST_MODULE || '@electric-sql/pglite');
const db=new PGlite();
const owner=randomUUID(),other=randomUUID(),worker=randomUUID();
const prefs={destination:'Goa',departureCity:'Mumbai',startDate:'2026-12-01',endDate:'2027-01-09',budget:40000,currency:'INR'};
const rpc=async(name,args=[]) => {const rows=(await db.query(`select * from public.adaptive_${name}(${args.map((_,i)=>'$'+(i+1)).join(',')})`,args)).rows; for(const row of rows) for(const key of ['start_date','end_date','next_date']) if(row[key] instanceof Date) row[key]=row[key].toISOString().slice(0,10);return rows;};
const plan=async(p=prefs,allowance=3,request=randomUUID())=>(await rpc('create_plan',[owner,request,p,'a'.repeat(64),p.budget*100,allowance]))[0];
const get=async p=>(await rpc('get_plan',[owner,p.id]))[0];
const next=async(p,days=3,request=randomUUID())=>(await rpc('next_section',[owner,p.id,request,days]))[0];
const claim=async s=>(await rpc('claim_section',[owner,s.id,worker]))[0];
const change=async(s,status,response=null,checkpoint=null,code=null)=>(await rpc('transition_section',[owner,s.id,s.lease_token,s.version,status,response,code,checkpoint]))[0];
const run=async s=>{s=await claim(s);s=await change(s,'submitting');return change(s,'running','resp_fixture');};
const checkpoint=s=>{
 const days=[];let d=new Date(s.start_date+'T00:00:00Z');const end=new Date(s.end_date+'T00:00:00Z');
 for(;d<=end;d.setUTCDate(d.getUTCDate()+1)) days.push({date:d.toISOString().slice(0,10),costs:{accommodation:1,meals:1,localTransport:1,activities:1,departureTravel:0},activities:[{startTime:'09:00',durationMinutes:60,kind:'main',title:'Visit '+d.toISOString().slice(0,10)}]});
 return {journeyStrategy:{summary:'One coherent Goa stay with departure and return in Mumbai.',stays:[{startDate:prefs.startDate,endDate:prefs.endDate,location:'Goa'}]},itinerary:{status:'planned',days},startLocation:s.input_boundary.location,endLocation:s.final_section?s.departure_city:'Goa',spentCents:days.length*400,provenance:{provider:'openai',model:'gpt-6-luna',validationVersion:'adaptive-section-v1'}};
};
try {
 await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create table auth.users(id uuid primary key);');
 await db.query('insert into auth.users values ($1),($2)',[owner,other]);
 await db.exec(await fs.readFile(new URL('../../migrations/005_adaptive_section_checkpoints_REVIEW_ONLY.sql',import.meta.url),'utf8'));
 await db.exec('set role anon');
 await assert.rejects(rpc('get_plan',[owner,randomUUID()]),/permission denied/);
 await db.exec('reset role; set role service_role');
 const request=randomUUID();let p=await plan(prefs,3,request);
 assert.equal((await plan(prefs,3,request)).id,p.id);
 await assert.rejects(rpc('create_plan',[owner,request,prefs,'b'.repeat(64),4000000,3]),/conflict/);
 assert.equal((await rpc('get_plan',[other,p.id])).length,0);
 assert.equal(p.end_date,'2027-01-09'); // forty days: no total-duration cap
 const successful=[];
 for(let i=0;i<3;i++) {
  let s=await next(p);assert.equal(s.input_boundary.location,i?'Goa':'Mumbai');
  if(i) assert.equal(s.input_boundary.lastActivityEnd,'10:00');
  assert.equal((await rpc('claim_section',[other,s.id,worker])).length,0);
  await run(s);s=await claim(s);const data=checkpoint(s);
  if(i===0) {
   assert.equal((await rpc('transition_section',[owner,s.id,null,s.version,'succeeded',null,null,data])).length,0);
   assert.equal((await rpc('transition_section',[owner,s.id,s.lease_token,null,'succeeded',null,null,data])).length,0);
   await assert.rejects(change(s,'succeeded',null,{...data,spentCents:1}),/cost/);
   await assert.rejects(change(s,'succeeded',null,{...data,startLocation:'Elsewhere'}),/invalid/);
   await assert.rejects(change(s,'succeeded',null,{...data,provenance:{}}),/invalid/);
   const bad=structuredClone(data);bad.itinerary.days.pop();await assert.rejects(change(s,'succeeded',null,bad),/coverage/);
  }
  if(i===1) {
   const changed=structuredClone(data);changed.journeyStrategy.summary='Different outline';
   await assert.rejects(change(s,'succeeded',null,changed),/immutable/);
   const duplicate=structuredClone(data);duplicate.itinerary.days[0].activities[0].title='  VISIT 2026-12-01  ';
   await assert.rejects(change(s,'succeeded',null,duplicate),/Repeated principal/);
  }
  const done=await change(s,'succeeded',null,data);successful.push(done);
  assert.equal((await rpc('transition_section',[owner,s.id,s.lease_token,s.version,'failed',null,'late',null])).length,0);
 }
 p=await get(p);assert.equal(p.status,'paused');assert.equal(p.pause_reason,'RESOURCE_ALLOWANCE_REACHED');assert.equal(p.completed_days,9);assert.equal(Number(p.spent_cents),3600);
 assert.equal((await rpc('next_section',[owner,p.id,randomUUID(),3])).length,0);
 // Exhausted allowance must retain resume intent when even the control row
 // cannot fit; defensive existing global pauses with zero also grant on Continue.
 for(const reason of ['RESOURCE_ALLOWANCE_REACHED','STORAGE_LIMIT']) {
  await db.query("update adaptive_plans set status='paused',remaining_creates=0,pause_reason=$1,storage_pause_scope=$2 where id=$3",[reason,reason==='STORAGE_LIMIT'?'global':null,p.id]);
  const blocker=(await rpc('create_plan',[other,randomUUID(),prefs,'a'.repeat(64),4000000,3]))[0];
  await db.query('update adaptive_plans set storage_limit_bytes=67108864,storage_used_bytes=67108864-100-(select coalesce(sum(storage_used_bytes),0) from adaptive_plans where id<>$1) where id=$1',[blocker.id]);
  const retryControl=randomUUID(),before=await get(p);
  assert.deepEqual((await rpc('continue_run',[owner,p.id,retryControl,3]))[0],before);
  await db.query("update adaptive_plans set created_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' where id=$1",[blocker.id]);
  await rpc('purge_expired');
  const resumedRun=(await rpc('continue_run',[owner,p.id,retryControl,3]))[0];
  assert.equal(resumedRun.status,'active');assert.equal(resumedRun.remaining_creates,3);
  assert.equal((await rpc('continue_run',[owner,p.id,retryControl,3]))[0].remaining_creates,3);
 }
 await db.query("update adaptive_plans set status='paused',remaining_creates=0,pause_reason='RESOURCE_ALLOWANCE_REACHED' where id=$1",[p.id]);
 const resume=randomUUID();p=(await rpc('continue_run',[owner,p.id,resume,3]))[0];
 assert.equal((await rpc('continue_run',[owner,p.id,resume,3]))[0].remaining_creates,3);
 assert.equal((await rpc('list_sections',[owner,p.id,0,3])).length,3);
 await assert.rejects(rpc('list_sections',[owner,p.id,0,4]),/bound/);
 let s=await next(p);assert.equal(s.start_date,'2026-12-10');await run(s);s=await claim(s);await change(s,'failed',null,null,'OUTPUT_LIMIT');
 const retry=randomUUID();let replacement=(await rpc('retry_section',[owner,s.id,retry,1]))[0];
 assert.equal(replacement.start_date,'2026-12-10');assert.equal(replacement.end_date,'2026-12-10');
 assert.equal((await rpc('retry_section',[owner,s.id,retry,1]))[0].id,replacement.id);
 await assert.rejects(rpc('retry_section',[owner,s.id,retry,2]),/conflict/);
 assert.equal(replacement.sequence,5);
 // Restart claims stored response identity, never a new create.
 await run(replacement);const recovered=(await rpc('claim_next',[worker]))[0];assert.equal(recovered.provider_response_id,'resp_fixture');
 await change(recovered,'succeeded',null,checkpoint(recovered));
 assert.deepEqual((await rpc('recent_checkpoints',[owner,p.id])).map(row=>row.sequence),[5,3,2]);
 assert.equal((await rpc('recent_checkpoints',[other,p.id])).length,0);
 let uncertain=await next(p);uncertain=await claim(uncertain);uncertain=await change(uncertain,'submitting');
 await db.query("update adaptive_sections set lease_until=now()-interval '1 second' where id=$1",[uncertain.id]);
 assert.equal((await rpc('claim_next',[worker])).length,0);
 assert.equal((await rpc('retry_section',[owner,uncertain.id,randomUUID(),1])).length,0);
 assert.equal((await get(p)).pause_reason,'SUBMISSION_UNKNOWN');
 assert.equal((await rpc('cancel_plan',[other,p.id])).length,0);
 await rpc('cancel_plan',[owner,p.id]);
 assert.equal((await rpc('list_sections',[owner,p.id,0,3])).every(x=>x.status==='succeeded'),true);
 // Cancellation cannot revive or remove accepted checkpoint rows.
 assert.equal((await rpc('transition_section',[owner,uncertain.id,uncertain.lease_token,uncertain.version,'running','resp_late',null,null])).length,0);
 await db.query("update adaptive_plans set created_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' where id=$1",[p.id]);
 await rpc('purge_expired');assert.equal((await rpc('list_sections',[owner,p.id,0,3])).length,0);
 // One Generate allowance covers all eight sections of a 24-day trip.
 const p24prefs={...prefs,endDate:'2026-12-24'};const p24=await plan(p24prefs,12);
 for(let i=0;i<8;i++) {
  let segment=await next(p24);await run(segment);segment=await claim(segment);
  const output=checkpoint(segment);output.journeyStrategy.stays[0].endDate=p24prefs.endDate;
  await change(segment,'succeeded',null,output);
 }
 const complete24=await get(p24);assert.equal(complete24.status,'completed');assert.equal(complete24.completed_days,24);assert.equal(complete24.remaining_creates,4);
 // Claimed queued work reserves capacity before any provider create starts.
 const thirdOwner=randomUUID();await db.exec('reset role');await db.query('insert into auth.users values($1)',[thirdOwner]);await db.exec('set role service_role');
 const queueOwners=[owner,other,thirdOwner],queuePlans=[],queueSections=[];
 for(const account of queueOwners) {
  const queuedPlan=(await rpc('create_plan',[account,randomUUID(),prefs,'a'.repeat(64),4000000,12]))[0];queuePlans.push(queuedPlan);
  queueSections.push((await rpc('next_section',[account,queuedPlan.id,randomUUID(),3]))[0]);
 }
 assert.equal((await rpc('claim_section',[owner,queueSections[0].id,worker])).length,1);
 assert.equal((await rpc('claim_section',[other,queueSections[1].id,worker])).length,1);
 assert.equal((await rpc('claim_section',[thirdOwner,queueSections[2].id,worker])).length,0);
 for(let i=0;i<3;i++) await rpc('cancel_plan',[queueOwners[i],queuePlans[i].id]);
 // Crash recovery can schedule a plan whose next section was never queued.
 p=await plan();let auto=(await rpc('claim_next',[worker]))[0];assert.equal(auto.plan_id,p.id);assert.equal(auto.status,'queued');
 const suggestions={applicability:'proposed',explanation:'Budget cannot cover this transfer.',recommendations:[{field:'budget',reason:'Transport cost exceeds remaining funds.',suggestion:'Consider increasing the budget.'}]};
 const rejected=(await rpc('transition_section',[owner,auto.id,auto.lease_token,auto.version,'failed',null,'SECTION_CONSTRAINT_CONFLICT',null,suggestions]))[0];
 assert.deepEqual(rejected.failure_details,suggestions);assert.equal((await get(p)).remaining_creates,3); // no provider create charged
 assert.equal((await rpc('get_section',[other,auto.id])).length,0);
 await db.query('update adaptive_plans set remaining_creates=0 where id=$1',[p.id]);
 for(const code of ['SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED']) {
  await db.query('update adaptive_sections set error_code=$1 where id=$2',[code,auto.id]);
  assert.equal((await rpc('continue_run',[owner,p.id,randomUUID(),12])).length,0);
  assert.equal((await get(p)).remaining_creates,0);
  assert.deepEqual((await rpc('get_section',[owner,auto.id]))[0].failure_details,suggestions);
 }

 await rpc('cancel_plan',[owner,p.id]);
 p=await plan();await db.query('update adaptive_plans set storage_limit_bytes=100000 where id=$1',[p.id]);
 assert.equal((await rpc('next_section',[owner,p.id,randomUUID(),3])).length,0);
 assert.equal((await get(p)).pause_reason,'STORAGE_LIMIT');assert.equal((await get(p)).completed_days,0);
 assert.equal((await rpc('list_sections',[owner,p.id,0,3])).length,0); // no work discarded and no paid request
 assert.equal((await rpc('continue_run',[owner,p.id,randomUUID(),12])).length,0); // per-plan ceiling cannot be bypassed
 await rpc('cancel_plan',[owner,p.id]);
 const globalLimited=await plan();let preserved=await next(globalLimited);await run(preserved);preserved=await claim(preserved);
 preserved=await change(preserved,'succeeded',null,checkpoint(preserved));
 // Synthetic counters exercise the global guard without allocating megabytes.
 await db.query('update adaptive_plans set storage_limit_bytes=67108864,storage_used_bytes=67108864-100000-(select coalesce(sum(storage_used_bytes),0) from adaptive_plans where id<>$1) where id=$1',[p.id]);
 assert.equal((await rpc('next_section',[owner,globalLimited.id,randomUUID(),3])).length,0);
 assert.equal((await get(globalLimited)).storage_pause_scope,'global');
 assert.equal((await get(globalLimited)).remaining_creates,2);assert.equal((await get(globalLimited)).completed_days,3);
 const capacityResume=randomUUID(),beforeProbe=await get(globalLimited);
 const controls=async()=>Number((await db.query('select count(*) as n from adaptive_run_requests where plan_id=$1',[globalLimited.id])).rows[0].n);
 const beforeControls=await controls();
 for(let i=0;i<30;i++) assert.deepEqual((await rpc('continue_run',[owner,globalLimited.id,i===0?capacityResume:randomUUID(),12]))[0],beforeProbe);
 assert.equal(await controls(),beforeControls); // no uncharged/unbounded control rows
 assert.equal((await get(globalLimited)).storage_used_bytes,beforeProbe.storage_used_bytes);
 await db.query("update adaptive_plans set created_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' where id=$1",[p.id]);
 await rpc('purge_expired');
 const resumed=(await rpc('continue_run',[owner,globalLimited.id,capacityResume,12]))[0];assert.equal(resumed.remaining_creates,2);assert.equal(Number(resumed.storage_used_bytes),Number(beforeProbe.storage_used_bytes)+512);assert.equal(await controls(),beforeControls+1);
 assert.equal((await rpc('continue_run',[owner,globalLimited.id,capacityResume,12]))[0].remaining_creates,2);assert.equal(await controls(),beforeControls+1);
 assert.equal((await next(globalLimited)).start_date,'2026-12-04');
 assert.equal((await rpc('recent_checkpoints',[owner,globalLimited.id]))[0].id,preserved.id);
 assert.deepEqual((await rpc('get_section',[owner,preserved.id]))[0].checkpoint,preserved.checkpoint);


 assert.equal((await rpc('checkpoint_health'))[0].cleanup_fresh,true);
 await db.exec('reset role; create role planning_queue_worker nologin;');
 await db.exec(await fs.readFile(new URL('../../../docs/adaptive_section_worker_grants_REVIEW_ONLY.sql',import.meta.url),'utf8'));
 await db.exec('set role planning_queue_worker');
 assert.equal((await rpc('get_plan',[owner,globalLimited.id]))[0].id,globalLimited.id);
 assert.equal((await rpc('checkpoint_health'))[0].cleanup_fresh,true);
 await assert.rejects(db.query('select * from auth.users'),/permission denied/);
 await assert.rejects(rpc('purge_expired'),/permission denied/);
 console.log('PASS adaptive SQL: owner isolation; 40-day manifest; exact date/budget/boundary checkpoints; immutable acceptance; 12-create default policy/24-day completion; explicit3-create pause and idempotent continuation; per-section page; explicit retry/split; restart identity; uncertain quarantine; cascade purge.');
} finally { await db.close(); }
