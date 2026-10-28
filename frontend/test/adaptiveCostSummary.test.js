import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
let server,Summary,calculate,Status;
before(async()=>{server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});({default:Summary,retainedCostSummary:calculate}=await server.ssrLoadModule('/src/components/AdaptiveCostSummary.jsx'));({default:Status}=await server.ssrLoadModule('/src/components/AdaptivePlanningStatus.jsx'));});
after(async()=>server?.close());
const plan=patch=>({completedDays:3,totalDays:9,spentCents:1500000,totalBudgetCents:2500000,...patch});
const render=value=>renderToStaticMarkup(React.createElement(Summary,{plan:value,currency:'INR',travelers:2}));
test('partial retained estimate is group-wide, not the full-trip price, and contingency is separate from actual budget',()=>{
 const value=plan(),copy=structuredClone(value),html=render(value);assert.deepEqual(value,copy);assert.match(html,/whole group \(2 travelers\), not per person/);assert.match(html,/Covers only 3 of 9 days/);assert.match(html,/not a whole-trip total/);assert.match(html,/INR 15,000.00/);assert.match(html,/INR 1,500.00/);assert.match(html,/INR 16,500.00/);assert.match(html,/INR 8,500.00/);assert.match(html,/not included in those costs, charged or reserved/);assert.match(html,/remaining days/);
});
test('complete estimate exposes a contingency shortfall instead of silently increasing budget or prices',()=>{
 const value=plan({completedDays:9,spentCents:2400000}),html=render(value);assert.match(html,/Covers all 9 requested days/);assert.match(html,/INR 26,400.00/);assert.match(html,/Shortfall against your budget/);assert.match(html,/INR 1,400.00/);assert.match(html,/no budget increase has been applied/);assert.doesNotMatch(html,/Unplanned days are not estimated/);
});
test('contingency arithmetic remains exact at cent rounding and maximum supported integers',()=>{
 assert.equal(calculate(plan({spentCents:5})).contingency,1n);assert.equal(calculate(plan({spentCents:4})).contingency,1n);const max=Number.MAX_SAFE_INTEGER;assert.equal(calculate(plan({spentCents:max,totalBudgetCents:max})).withContingency,9907919180215091n);assert.equal(calculate(plan({spentCents:NaN})),null);assert.equal(render(plan({completedDays:0,spentCents:0})),'');
});

test('normal expense copy consistently refers to planned days, not internal sections',()=>{
 for(const value of [plan(),plan({completedDays:9})]){const html=render(value);assert.match(html,/Planned-day estimate/);assert.match(html,/All planned days/);assert.match(html,/planned-day estimates/);assert.doesNotMatch(html,/completed.section|completed sections/i);}
});
