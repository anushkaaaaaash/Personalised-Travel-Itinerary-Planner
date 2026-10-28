import { useEffect, useState } from 'react';
import { fetchAdaptiveExpenses } from '../services/adaptiveExpenses.js';
import { getSession, subscribeSession } from '../services/session.js';
import { COST_LABELS } from '../services/itineraries.js';
const cents=value=>Number.isSafeInteger(value)&&value>=0;
export function retainedCostSummary(plan) {
  if(!cents(plan?.spentCents)||!cents(plan.totalBudgetCents)||plan.spentCents>plan.totalBudgetCents)return null;
  const accepted=BigInt(plan.spentCents),budget=BigInt(plan.totalBudgetCents),contingency=(accepted+9n)/10n,withContingency=accepted+contingency;
  return {accepted,budget,unallocated:budget-accepted,contingency,withContingency,shortfall:withContingency>budget?withContingency-budget:0n,afterContingency:withContingency<budget?budget-withContingency:0n};
}
const money=(currency,value)=>`${currency} ${(value/100n).toLocaleString()}.${String(value%100n).padStart(2,'0')}`;
export default function AdaptiveCostSummary({plan,currency,travelers,fetchExpenses=fetchAdaptiveExpenses}) {
  const [open,setOpen]=useState(false),[reload,setReload]=useState(0),[snapshot,setSnapshot]=useState({loading:false,value:null,error:''});
  useEffect(()=>{
    if(!open)return;const controller=new AbortController(),session=getSession();let mounted=true;const unsubscribe=subscribeSession(next=>{if(next!==session){controller.abort();if(mounted)setSnapshot({loading:false,value:null,error:'Sign in again to view this summary.'});}});
    setSnapshot({loading:true,value:null,error:''});
    fetchExpenses({plan,preferences:{currency,travelers}},{signal:controller.signal}).then(value=>{if(mounted&&!controller.signal.aborted&&getSession()===session)setSnapshot({loading:false,value,error:''});}).catch(()=>{if(mounted&&!controller.signal.aborted)setSnapshot({loading:false,value:null,error:'The retained expense summary could not be checked. Your plan has not been changed.'});});
    return()=>{mounted=false;controller.abort();unsubscribe();};
  },[open,reload,plan.id,plan.completedDays,plan.spentCents,plan.totalDays,plan.totalBudgetCents,currency,travelers,fetchExpenses]);
  const costs=retainedCostSummary(plan);if(!costs||plan.completedDays<1)return null;
  const complete=plan.completedDays===plan.totalDays;
  const currentSnapshot=snapshot.value&&snapshot.value.planId===plan.id&&snapshot.value.acceptedDays===plan.completedDays&&snapshot.value.totalSpentCents===plan.spentCents&&snapshot.value.totalDays===plan.totalDays&&snapshot.value.totalBudgetCents===plan.totalBudgetCents&&snapshot.value.currency===currency&&snapshot.value.travelers===travelers?snapshot.value:null;
  return <section className="adaptive-export" aria-label="Retained plan cost summary"><h3>Retained plan costs</h3>
    <p className="hint">{currency} estimates for the whole group{Number.isSafeInteger(travelers)&&travelers>0?` (${travelers} ${travelers===1?'traveler':'travelers'})`:''}, not per person. Not live quotes or bookings.</p>
    <p className="hint">{complete?`Covers all ${plan.totalDays} requested days.`:`Covers only ${plan.completedDays} of ${plan.totalDays} days. Unplanned days are not estimated; this is not a whole-trip total.`}</p>
    <ul className="budget-list"><li><span>Planned-day estimate</span><strong>{money(currency,costs.accepted)}</strong></li><li><span>Your total group budget</span><span>{money(currency,costs.budget)}</span></li><li><span>Unallocated budget</span><span>{money(currency,costs.unallocated)}</span></li></ul>
    {!complete&&<p className="hint">Unallocated money still needs to cover the remaining days; it is not all spare spending money.</p>}
    <details className="secondary-tools" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Whole retained-plan category breakdown</summary><p className="hint">All planned days, not just the page you are viewing. Unplanned days are excluded.</p>{snapshot.loading&&<p role="status">Checking retained expenses…</p>}{currentSnapshot&&<ul className="budget-list">{Object.entries(COST_LABELS).map(([key,label])=><li key={key}><span>{label}</span><span>{money(currency,BigInt(currentSnapshot.categories[key]))}</span></li>)}</ul>}{snapshot.error&&<><p role="status">{snapshot.error}</p><button className="preview-btn" type="button" onClick={()=>setReload(value=>value+1)}>Check expenses again</button></>}</details>
    <details className="secondary-tools"><summary>Optional 10% contingency suggestion</summary><p className="hint">A cushion based only on planned-day estimates. It is not included in those costs, charged or reserved, and it does not change your budget.{!complete&&' Recalculate it when the remaining days are planned.'}</p><ul className="budget-list"><li><span>Suggested cushion</span><span>{money(currency,costs.contingency)}</span></li><li><span>Estimate plus suggested cushion</span><strong>{money(currency,costs.withContingency)}</strong></li><li><span>{costs.shortfall>0n?'Shortfall against your budget':'Budget left after this suggestion'}</span><span>{money(currency,costs.shortfall>0n?costs.shortfall:costs.afterContingency)}</span></li></ul>{costs.shortfall>0n&&<p className="hint">This suggestion would exceed your current budget by {money(currency,costs.shortfall)}. Consider cheaper choices or a smaller cushion; no budget increase has been applied.</p>}</details>
  </section>;
}
