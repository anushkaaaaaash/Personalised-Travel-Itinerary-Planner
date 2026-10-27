import {preferences,plan} from './shareFixture.js';
export const travelPreferences={...preferences,startDate:'2028-01-01',endDate:'2028-01-09',travelPace:'fast'};
export function travelPage(){
 const itinerary=plan();itinerary.travelPace='fast';
 itinerary.days=['2028-01-07','2028-01-08','2028-01-09'].map((date,index)=>{
  const day=structuredClone(itinerary.days[0]);day.date=date;
  day.activities.push({...day.activities[0],id:'c',title:'Local experience',startTime:'14:00'});day.mainActivityCount=3;
  if(index<2){day.costs.localTransport+=day.costs.departureTravel;day.costs.departureTravel=0;}
  else{day.mainActivityCount=0;day.activities=[{...day.activities[0],id:'return-transfer',title:'Return journey',kind:'transfer',durationMinutes:120}];day.morning='Return travel';day.afternoon='Arrival and rest';day.evening='Rest at home';}
  return day;
 });
 itinerary.estimatedTotalGroupCost=450;itinerary.remainingBudget=2050;
 return {preferences:{...travelPreferences},plan:{id:'11111111-1111-4111-8111-111111111111',requestId:'22222222-2222-4222-8222-222222222222',status:'completed',runAllowance:12,estimatedSections:3,completedDays:9,totalDays:9,remainingCreates:9,spentCents:135000,totalBudgetCents:250000,pauseReason:null,expiresAt:'2029-01-01T00:00:00Z',activeSection:null},sections:[{id:'33333333-3333-4333-8333-333333333333',sequence:3,startDate:'2028-01-07',endDate:'2028-01-09',checkpoint:{itinerary,startLocation:'Kyoto',endLocation:'Tokyo',spentCents:45000,provenance:{provider:'openai',model:'gpt-6-luna',validationVersion:'adaptive-section-v1'}}}],nextCursor:null};
}
