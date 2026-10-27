import { sessionFetch } from './session.js';
import { adaptiveId } from './adaptivePlanning.js';
import { COST_LABELS } from './itineraries.js';
const integer=value=>Number.isSafeInteger(value)&&value>=0;
export function validateAdaptiveExpenses(value,{plan,preferences}) {
  const invalid=()=>{throw new Error('The expense snapshot could not be matched to this plan. Refresh the summary to check again.');};
  if(!value||!adaptiveId(value.planId)||value.planId!==plan.id||!Number.isSafeInteger(value.planVersion)||value.planVersion<1||value.scope!=='whole_group'||value.budgetGapScope!=='accepted_estimates_plus_suggested_buffer'||value.suggestedBufferPercent!==10
    ||value.currency!==preferences.currency||value.travelers!==preferences.travelers||value.totalSpentCents!==plan.spentCents||value.totalBudgetCents!==plan.totalBudgetCents||value.acceptedDays!==plan.completedDays||value.totalDays!==plan.totalDays||value.isComplete!==(plan.completedDays===plan.totalDays)
    ||!['totalSpentCents','totalBudgetCents','acceptedDays','totalDays','remainingBudgetCents','suggestedBufferCents','budgetGapCents'].every(key=>integer(value[key]))||!value.categories||Object.keys(value.categories).sort().join(',')!==Object.keys(COST_LABELS).sort().join(',')||!Object.values(value.categories).every(integer))return invalid();
  const spent=BigInt(value.totalSpentCents),budget=BigInt(value.totalBudgetCents),buffer=(spent+9n)/10n;
  if(Object.values(value.categories).reduce((sum,cost)=>sum+BigInt(cost),0n)!==spent||budget<spent||BigInt(value.remainingBudgetCents)!==budget-spent||BigInt(value.suggestedBufferCents)!==buffer||BigInt(value.budgetGapCents)!==(spent+buffer>budget?spent+buffer-budget:0n))return invalid();
  return {planId:value.planId,planVersion:value.planVersion,categories:{...value.categories},totalSpentCents:value.totalSpentCents,acceptedDays:value.acceptedDays,totalDays:value.totalDays,isComplete:value.isComplete,currency:value.currency,travelers:value.travelers,scope:'whole_group',totalBudgetCents:value.totalBudgetCents,remainingBudgetCents:value.remainingBudgetCents,suggestedBufferPercent:10,suggestedBufferCents:value.suggestedBufferCents,budgetGapCents:value.budgetGapCents,budgetGapScope:value.budgetGapScope};
}
export async function fetchAdaptiveExpenses(expected,{signal,fetchImpl=sessionFetch,timeoutMs=15000}={}) {
  if(!adaptiveId(expected?.plan?.id))throw Error('This plan could not be identified.');
  const controller=new AbortController(),abort=()=>controller.abort(),timer=setTimeout(abort,timeoutMs);if(signal?.aborted)abort();signal?.addEventListener('abort',abort,{once:true});
  try{const response=await fetchImpl(`${(import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/,'')}/adaptive-plans/${expected.plan.id}/expenses`,{method:'GET',signal:controller.signal,headers:{Accept:'application/json'}});if(response.status!==200)throw Error();const body=await response.json();if(controller.signal.aborted)throw Error();return validateAdaptiveExpenses(body,expected);}
  catch{throw Error('The retained expense summary could not be checked. Your plan has not been changed.');}finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
