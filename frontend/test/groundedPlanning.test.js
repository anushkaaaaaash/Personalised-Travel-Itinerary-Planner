import test from 'node:test';
import assert from 'node:assert/strict';
import { validateAdaptivePage,createAdaptivePlanningClient,validAdaptivePolicy } from '../src/services/adaptivePlanning.js';
import { groundedPage } from './groundedPlanningFixture.js';
const invalid=body=>assert.throws(()=>validateAdaptivePage(body),{code:'ADAPTIVE_INVALID_RESPONSE'});
test('public research and complete day prefixes are whitelisted without private stream state',()=>{
  const page=groundedPage();page.research.query='PRIVATE_QUERY';page.research.provider_response_id='PRIVATE_PROVIDER';page.draft.stream_output_text='PRIVATE_RAW_STREAM';page.draft.days[0].privateNote='PRIVATE_DAY';page.draft.days[0].activities[0].privateNote='PRIVATE_ACTIVITY';
  const copy=structuredClone(page),value=validateAdaptivePage(page);assert.deepEqual(page,copy);assert.equal(value.research.applicability,'unknown');assert.equal(value.draft.accepted,false);assert.equal(value.draft.days.length,1);assert.equal(value.plan.completedDays,3);assert.equal(value.sections.length,1);assert.doesNotMatch(JSON.stringify(value),/PRIVATE_/);
  value.draft.days[0].interestTags.push('different');assert.deepEqual(page,copy);
  for(const days of [0,1,2,3])assert.equal(validateAdaptivePage(groundedPage({days})).draft.days.length,days);
  const legacy=groundedPage();delete legacy.research;delete legacy.draft;assert.equal(validateAdaptivePage(legacy).research,null);assert.equal(validateAdaptivePage(legacy).draft,null);
});
test('pending and stopped research envelopes accept empty notes without invented evidence',()=>{
  for(const status of ['queued','submitting','running','failed','submission_unknown','cancelled']){const value=validateAdaptivePage(groundedPage({status}));assert.equal(value.research.status,status);assert.equal(value.research.text,'');assert.equal(value.draft,null);}
});
test('research rejects unsupported claims, unbound citations, unsafe links and oversized data',()=>{
  for(const mutate of [p=>p.research.applicability='verified',p=>p.research.citations=[],p=>p.research.citations[0].url='https://other.example.com',p=>p.research.citations[0].title='Other title',p=>p.research.citations[0].end=99999,p=>p.research.citations[0].start=-1,p=>p.research.citations[0].end=0,p=>p.research.citations=Array(49).fill(p.research.citations[0]),p=>p.research.sources.push(p.research.sources[0]),p=>p.research.toolCallsReserved=7,p=>p.research.expiresAt='2028-01-03T12:00:00Z',p=>p.research.text='x'.repeat(24001),p=>p.research.sources[0].url='javascript:alert(1)',p=>p.research.sources[0].url='https://visitor.internal',p=>p.research.errorCode='PROVIDER_PRIVATE_TEXT',p=>p.research.receivedAt=null,p=>p.research.receivedAt='2028-02-31T12:00:00Z',p=>p.research.text='\ud800']){const page=groundedPage();mutate(page);invalid(page);}
  const pending=groundedPage({status:'running'});pending.research.text='Unfinished prose is not public research';invalid(pending);
  const unicode=groundedPage();unicode.research.text='🗺️ Trip';unicode.research.citations[0].end=Array.from(unicode.research.text).length;assert.equal(validateAdaptivePage(unicode).research.text,unicode.research.text);unicode.research.citations[0].end=unicode.research.text.length;invalid(unicode);
  const failed=groundedPage({status:'failed'});failed.research.errorCode='PRIVATE_DIAGNOSTIC';assert.equal(validateAdaptivePage(failed).research.errorCode,'REQUEST_FAILED');
});
test('draft matches current unfinished section, explicit currency, complete chronology and original date bounds',()=>{
  for(const mutate of [p=>p.plan.status='paused',p=>p.plan.activeSection.status='failed',p=>p.draft.currency='EUR',p=>p.draft.sectionStart='2028-01-03',p=>p.draft.sectionEnd='2028-01-07',p=>p.draft.days[0].date='2028-01-05',p=>p.draft.accepted=true,p=>p.draft.days[0].activities=[],p=>p.draft.days[0].mainActivityCount=0,p=>delete p.draft.days[0].activities[0].kind,p=>p.draft.days[0].costs.meals=Infinity,p=>p.draft.days[0].morning='',p=>p.draft.days=Array(4).fill(p.draft.days[0])]){const page=groundedPage();mutate(page);invalid(page);}
});
test('transport preserves optional public context without triggering another request while reading it',async()=>{
  let calls=0;const page=groundedPage();const client=createAdaptivePlanningClient({fetchImpl:async(_url,options)=>{calls++;assert.equal(options.method,'GET');return{status:200,json:async()=>page};}});
  const value=await client.get(page.plan.id);assert.equal(value.research.sources.length,1);assert.equal(value.draft.days.length,1);assert.equal(calls,1);
});

test('research capability requires the exact bounded public policy and eight-minute response limit',()=>{
 const policy={sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,maxWebSearchCalls:6,researchMode:'on_demand',provisionalDayPreviews:true,responseDeadlineMinutes:8};assert.equal(validAdaptivePolicy(policy),true);assert.equal(validAdaptivePolicy({...policy,responseDeadlineMinutes:30}),true);assert.equal(validAdaptivePolicy({...policy,responseDeadlineMinutes:15}),false);
 for(const patch of [{maxWebSearchCalls:7},{maxWebSearchCalls:undefined},{researchMode:'always'},{provisionalDayPreviews:'true'},{responseDeadlineMinutes:undefined},{researchEnabled:'true'}])assert.equal(validAdaptivePolicy({...policy,...patch}),false);
 assert.equal(validAdaptivePolicy({sectionDays:3,maxSubmissionsPerRun:12}),true);
});

test('explicit shortened section retries can show one or two complete draft days without losing accepted content',()=>{
 for(const [end,days] of [['2028-01-04',1],['2028-01-05',2]]){const page=groundedPage({days});page.draft.sectionEnd=end;const value=validateAdaptivePage(page);assert.equal(value.draft.days.length,days);assert.equal(value.sections.length,1);assert.equal(value.plan.completedDays,3);}
 const overflow=groundedPage({days:2});overflow.draft.sectionEnd='2028-01-04';invalid(overflow);
});
test('research links reject reserved DNS variants after browser IDNA and trailing-dot normalization',()=>{
 for(const url of ['https://venue.test','https://venue.invalid','https://venue.home.arpa','https://venue.localdomain','https://venue.lan','https://venue.home','https://venue.onion','https://venue.example','https://venue.internal.','https://venue。internal','https://venue.ｔｅｓｔ','https://127.1','https://0x7f000001','https://example.123','https://venue.example.com/a b']){const page=groundedPage();page.research.sources[0].url=url;page.research.citations[0].url=url;invalid(page);}
 const publicDns=groundedPage();publicDns.research.sources[0].url='https://example.com./visit';publicDns.research.citations[0].url='https://example.com./visit';assert.equal(validateAdaptivePage(publicDns).research.sources.length,1);
});

test('a model-requested research pause is a bounded active state, not a user preference failure',()=>{
 const page=groundedPage({status:'queued'});page.plan.activeSection={id:page.plan.id,status:'failed',errorCode:'SECTION_RESEARCH_REQUESTED'};const value=validateAdaptivePage(page);assert.equal(value.plan.status,'active');assert.equal(value.plan.activeSection.errorCode,'SECTION_RESEARCH_REQUESTED');assert.equal(value.research.status,'queued');assert.equal(value.draft,null);
});

test('a fresh explicitly continued run may reuse unexpired prior research with zero current-run tool reservations',()=>{
 const page=groundedPage();page.research.toolCallsReserved=0;const value=validateAdaptivePage(page);assert.equal(value.research.sources.length,1);assert.equal(value.research.toolCallsReserved,0);assert.equal(value.plan.completedDays,3);
});
