import {savedFixture} from './savedAdaptiveFixture.js';
export function continuousDayFixture(){
 const f=savedFixture(),preferences={...f.base.preferences,endDate:'2028-01-17'};
 const all=[...f.page(0).sections,...f.page(3).sections];
 all.at(-1).endDate='2028-01-17';all.at(-1).checkpoint.itinerary.days.pop();all.at(-1).checkpoint.itinerary.estimatedTotalGroupCost=300;all.at(-1).checkpoint.itinerary.remainingBudget=preferences.budget-300;all.at(-1).checkpoint.spentCents=30000;
 all.forEach((section,i)=>{section.sequence=[1,4,5,6,7,8][i];section.id=`52345678-1234-1234-1234-${String(i+1).padStart(12,'0')}`;section.checkpoint.journeyStrategy.stays[0].endDate=preferences.endDate;});
 const plan={...f.base.plan,totalDays:17,completedDays:17,estimatedSections:6,spentCents:255000};
 return{plan,preferences,all,page(cursor=0){return{plan:structuredClone(plan),preferences:structuredClone(preferences),sections:structuredClone(cursor===0?all.slice(0,1):cursor===3?all.slice(1,4):all.slice(4)),nextCursor:cursor===0?3:cursor===3?6:null};}};
}
