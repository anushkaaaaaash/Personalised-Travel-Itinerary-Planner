import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { plan } from './shareFixture.js';

let server,Progress;
before(async()=>{server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});({default:Progress}=await server.ssrLoadModule('/src/components/GroundedPlanningProgress.jsx'));});
after(async()=>server?.close());
const render=props=>renderToStaticMarkup(React.createElement(Progress,props));
const research=patch=>({status:'succeeded',toolCallsReserved:2,toolCallLimit:6,receivedAt:'2028-01-01T12:00:00Z',expiresAt:'2028-01-02T12:00:00Z',sources:[{url:'https://www.example.com/visitor-info',title:'Visitor information'}],text:'A museum visit may fit the afternoon. Confirm the opening hours with the venue.',...patch});
const day=()=>({...structuredClone(plan().days[0]),date:'2028-01-01'});
const draftProps=patch=>({draft:{status:'draft',accepted:false,days:[day()],notice:'PRIVATE_NOTICE_MUST_NOT_APPEAR'},currency:'EUR',sectionStart:'2028-01-01',sectionEnd:'2028-01-03',...patch});

test('research shows consulted HTTPS links and receipt/freshness times without verified-fact claims',()=>{
  const html=render({research:research(),now:Date.parse('2028-01-01T13:00:00Z')});
  assert.match(html,/2 of 6 search\/tool requests reserved/);assert.match(html,/Reservations are not completed searches/);assert.match(html,/Research received/);assert.match(html,/not when a publisher updated/);assert.match(html,/Research freshness expires/);
  assert.match(html,/href="https:\/\/www.example.com\/visitor-info" target="_blank" rel="noopener noreferrer"/);assert.match(html,/not verified opening hours, prices, closures or journey times/);assert.match(html,/Confirm the opening hours/);assert.doesNotMatch(html,/window has expired|100%|<progress/);
  assert.match(render({research:research(),now:Date.parse('2028-01-03T00:00:00Z')}),/freshness window has expired/);
  const untitled=render({research:research({sources:[{url:'https://official.example.com/travel',title:''}]})});assert.match(untitled,/>official.example.com<\/a>/);assert.doesNotMatch(untitled,/could not be checked/);
});

test('untrusted notes and titles remain literal text, never markdown HTML or instructions',()=>{
  const html=render({research:research({text:'<script>alert(1)</script>\n[unsafe](javascript:alert(2))',sources:[{url:'https://example.com/page',title:'<img src=x onerror=alert(3)>'}]})});
  assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script|<img|href="javascript:/);
});

test('unsafe links, oversized sources or text, and malformed receipts fail closed',()=>{
  for(const url of ['javascript:alert(1)','http://example.com','https://user:password@example.com','https://127.0.0.1','https://localhost','https://example.internal','https://[::1]','https://example.com:8443']){
    const html=render({research:research({sources:[{url,title:'Hidden unsafe source'}]})});assert.match(html,/could not be checked/);assert.doesNotMatch(html,/Hidden unsafe source|href=/);
  }
  for(const patch of [{sources:Array.from({length:49},()=>({url:'https://example.com',title:'Source'}))},{sources:[{url:'https://example.com',title:'x'.repeat(301)}]},{text:'x'.repeat(24001)},{receivedAt:undefined},{receivedAt:'publisher updated yesterday'},{expiresAt:'2028-01-03T12:00:00Z'},{toolCallsReserved:7},{toolCallsReserved:-1},{toolCallLimit:12},{status:'verified'}])assert.match(render({research:research(patch)}),/could not be checked/);
  assert.doesNotMatch(render({research:research({text:'x'.repeat(24000),sources:Array.from({length:48},(_,index)=>({url:`https://example.com/${index}`,title:'Source'}))})}),/could not be checked/);
});

test('research states and failure categories are fixed copy, with no automatic-action controls',()=>{
  for(const status of ['queued','submitting','running','submission_unknown']){
    const html=render({research:research({status,text:null,sources:[],receivedAt:null,expiresAt:null})});assert.doesNotMatch(html,/<button|<progress|Read the research notes|Sources consulted/);if(status==='submission_unknown')assert.match(html,/Check its status before making another request/);
  }
  const cases={RESEARCH_PROVIDER_REJECTED:/did not accept/,RESEARCH_DEADLINE_REACHED:/processing time limit/,RESEARCH_SOURCES_UNCONFIRMED:/usable source information/,RESEARCH_SUBMISSION_UNCONFIRMED:/confirm whether research started/,RESEARCH_POLL_UNCONFIRMED:/does not prove that research failed/,RESEARCH_PROVIDER_FAILED:/not evidence that your dates or budget are wrong/};
  for(const [errorCode,expected] of Object.entries(cases)){const html=render({research:research({status:'failed',errorCode,error:'PRIVATE_RAW_FAILURE'})});assert.match(html,expected);assert.doesNotMatch(html,/PRIVATE_RAW_FAILURE|Read the research notes|<button/);}
  for(const errorCode of ['PRIVATE_RAW_FAILURE','toString','__proto__'])assert.match(render({research:research({status:'failed',errorCode})}),/complete research result is not available/);
  const polling=render({research:research({status:'running',errorCode:'RESEARCH_POLL_UNCONFIRMED'})});assert.match(polling,/latest research status could not be checked/);assert.doesNotMatch(polling,/Research is in progress/);
});

test('complete provisional days retain useful descriptions, schedule and cost categories without acceptance or exports',()=>{
  const props=draftProps(),copy=structuredClone(props),html=render(props);assert.deepEqual(props,copy);
  assert.match(html,/Draft — not yet accepted/);assert.match(html,/do not count as completed days/);assert.match(html,/border-style:dashed/);assert.match(html,/Museum/);assert.match(html,/09:00/);assert.match(html,/60 min/);assert.match(html,/Private activity note/);assert.match(html,/Rest between visits/);assert.match(html,/Private dietary note/);assert.match(html,/EUR 50.00/);assert.match(html,/Departure \/ return travel/);
  assert.doesNotMatch(html,/PRIVATE_NOTICE_MUST_NOT_APPEAR|<progress|Download|Save this|<button|days planned/);
});

test('partial or out-of-section draft objects never render and required metadata is not inferred',()=>{
  const base=draftProps();
  for(const patch of [{currency:undefined},{currency:'JPY'},{sectionStart:undefined},{sectionEnd:'2028-01-04'},{sectionEnd:'2028-02-31'},{draft:{...base.draft,accepted:true}},{draft:{...base.draft,status:'accepted'}},{draft:{...base.draft,days:Array.from({length:4},()=>day())}},{draft:{...base.draft,days:[{...day(),date:'2028-01-02'}]}},{draft:{...base.draft,days:[{...day(),activities:[]}]}},{draft:{...base.draft,days:[{...day(),transitAndRest:''}]}},{draft:{...base.draft,days:[{...day(),costs:{...day().costs,activities:NaN}}]}}]){
    const html=render({...base,...patch});assert.match(html,/not available to display safely/);assert.doesNotMatch(html,/Museum|EUR 50.00/);
  }
  const html=render(draftProps({draft:{status:'draft',accepted:false,days:[]}}));assert.match(html,/Complete draft days will appear/);assert.doesNotMatch(html,/not available to display safely/);
});

test('a complete draft prefix grows day by day but never mutates preceding accepted content',()=>{
  const first=day(),second={...day(),date:'2028-01-02'},third={...day(),date:'2028-01-03'};
  const accepted=React.createElement('article',{'data-accepted':'yes'},'Already accepted section');
  for(const days of [[first],[first,second],[first,second,third]]){
    const html=renderToStaticMarkup(React.createElement('main',null,accepted,React.createElement(Progress,draftProps({draft:{status:'draft',accepted:false,days}}))));assert.match(html,/Already accepted section/);assert.equal((html.match(/aria-label="Provisional day /g)||[]).length,days.length);assert.doesNotMatch(html,/<progress|days planned/);
  }
  assert.equal(render({}), '');
});
