import {createAdaptiveFixture} from '../tools/adaptiveVisualFixtures.mjs';
import {groundedPreferences} from './groundedPlanningFixture.js';
export const savedId='77777777-7777-4777-8777-777777777777',saveRequestId='88888888-8888-4888-8888-888888888888';
export function savedFixture(){
  const fixture=createAdaptiveFixture();fixture.preferences={...groundedPreferences,endDate:'2028-01-18',budget:5000};fixture.requestId='22222222-2222-4222-8222-222222222222';fixture.phase='completed';
  const base=fixture.snapshot();base.plan.version=21;const all=Array.from({length:6},(_,index)=>{const s=structuredClone(base.sections[index%3]);s.id=`52345678-1234-1234-1234-${String(index+1).padStart(12,'0')}`;s.sequence=index+1;s.startDate=`2028-01-${String(index*3+1).padStart(2,'0')}`;s.endDate=`2028-01-${String(index*3+3).padStart(2,'0')}`;s.checkpoint.startLocation=index===0?'Tokyo':'Kyoto';s.checkpoint.endLocation=index===5?'Tokyo':'Kyoto';s.checkpoint.itinerary.days.forEach((day,i)=>day.date=`2028-01-${String(index*3+i+1).padStart(2,'0')}`);return{...s,sourceAssociation:'none_recorded',historicalSources:[]};});
  base.sections=all.slice(0,3);base.nextCursor=3;
  const summary={id:savedId,requestId:saveRequestId,title:'Eighteen days in Kyoto',version:1,createdAt:'2026-10-01T12:00:00Z',updatedAt:'2026-10-01T12:00:00Z',format:'adaptive-sections-v1',persisted:true,sourcePlanId:base.plan.id,sourceVersion:21,totalDays:18,sectionCount:6,spentCents:270000,totalBudgetCents:500000,currency:'USD',startDate:'2028-01-01',endDate:'2028-01-18',destination:'Kyoto'};
  const operation=(count=3,patch={})=>({requestId:saveRequestId,sourcePlanId:base.plan.id,sourceVersion:21,title:summary.title,status:count===6?'complete':'staging',persisted:count===6,savedId:count===6?savedId:null,savedSections:count,totalSections:6,stagingExpiresAt:count===6?null:'2029-01-01T00:00:00Z',saved:count===6?structuredClone(summary):null,...patch});
  return{base,summary,operation,page:(cursor=0)=>({saved:structuredClone(summary),preferences:base.preferences,journeyStrategy:all[0].checkpoint.journeyStrategy,sections:structuredClone(all.slice(cursor,cursor+3)),nextCursor:cursor===0?3:null})};
}
export const memoryStorage=()=>{const data=new Map();return{getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key),data};};
