import { createAdaptiveFixture } from '../tools/adaptiveVisualFixtures.mjs';
import { preferences } from './shareFixture.js';
export const groundedPreferences={...preferences,startDate:'2028-01-01',endDate:'2028-01-09'};
export function researchFixture(patch={}) {
  return {status:'succeeded',toolCallsReserved:4,toolCallLimit:6,errorCode:null,receivedAt:'2028-01-01T12:00:00Z',expiresAt:'2028-01-02T12:00:00Z',sources:[{url:'https://example.com/visitor-info',title:'Visitor information'}],citations:[{start:0,end:6,url:'https://example.com/visitor-info',title:'Visitor information'}],text:'Museum hours should be confirmed before booking.',applicability:'unknown',...patch};
}
export function groundedPage({days=1,status='succeeded'}={}) {
  const fixture=createAdaptiveFixture();fixture.preferences=groundedPreferences;fixture.requestId='22222222-2222-4222-8222-222222222222';
  const page=fixture.snapshot();page.research=researchFixture();
  page.draft={status:'draft',accepted:false,sectionStart:'2028-01-04',sectionEnd:'2028-01-06',currency:groundedPreferences.currency,days:Array.from({length:days},(_,index)=>({...structuredClone(page.sections[0].checkpoint.itinerary.days[0]),date:`2028-01-0${index+4}`}))};
  if(status!=='succeeded'){
    page.research=researchFixture({status,text:'',sources:[],citations:[],receivedAt:null,expiresAt:null});page.draft=null;page.plan.activeSection=null;
    if(['failed','submission_unknown'].includes(status)){page.plan.status='paused';page.plan.pauseReason=status==='failed'?'RESEARCH_FAILED':'RESEARCH_SUBMISSION_UNKNOWN';page.research.errorCode=status==='failed'?'RESEARCH_PROVIDER_FAILED':'RESEARCH_SUBMISSION_UNCONFIRMED';}
  }
  return page;
}
