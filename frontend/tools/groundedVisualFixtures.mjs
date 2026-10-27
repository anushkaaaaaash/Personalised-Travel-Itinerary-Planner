import assert from 'node:assert/strict';
import {expenseFixture} from './revisionVisualFixtures.mjs';
import { groundedPage,groundedPreferences } from '../test/groundedPlanningFixture.js';

export function createGroundedFixture() {
  const fixture={phase:'draft-only',requestId:null,requests:[],currentAvailable:false,policy:{sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,maxWebSearchCalls:6,researchMode:'on_demand',provisionalDayPreviews:true,responseDeadlineMinutes:8}};
  fixture.snapshot=()=>{
    const status={researching:'running',failed:'failed',allowance:'failed',unknown:'submission_unknown',cancelled:'cancelled'}[fixture.phase] || 'succeeded';
    const page=groundedPage({status,days:fixture.phase==='draft-three'?3:1});page.plan.requestId=fixture.requestId;page.plan.runAllowance=12;page.plan.remainingCreates=9;
    if(fixture.phase==='draft-only')page.research=null;
    if(fixture.phase==='allowance'){page.plan.pauseReason='RESEARCH_ALLOWANCE_REACHED';page.research.toolCallsReserved=6;}
    if(fixture.phase==='cancelled')page.plan.status='cancelled';
    return page;
  };
  fixture.handle=async(route,url)=>{
    const method=route.request().method();fixture.requests.push({method,path:url.pathname});
    if(url.pathname.endsWith('/expenses')&&method==='GET')return route.fulfill({json:expenseFixture(fixture.snapshot())});
    if(url.pathname.endsWith('/current')&&method==='GET')return fixture.currentAvailable?route.fulfill({json:fixture.snapshot()}):route.fulfill({status:404,json:{error:{code:'SECTION_CURRENT_NOT_FOUND'}}});
    if(url.pathname==='/api/adaptive-plans'&&method==='POST'){const body=route.request().postDataJSON();assert.equal(body.preferences.startDate,groundedPreferences.startDate);assert.equal(body.preferences.endDate,groundedPreferences.endDate);fixture.requestId=body.requestId;fixture.currentAvailable=true;return route.fulfill({status:202,json:fixture.snapshot()});}
    if(url.pathname.endsWith('/research/retry')&&method==='POST'){assert.equal(fixture.phase,'failed');fixture.phase='researching';return route.fulfill({json:fixture.snapshot()});}
    if(url.pathname.endsWith('/continue')&&method==='POST'){assert.equal(fixture.phase,'allowance');fixture.phase='researching';return route.fulfill({json:fixture.snapshot()});}
    if(url.pathname.endsWith('/cancel')&&method==='POST'){fixture.phase='cancelled';return route.fulfill({json:fixture.snapshot()});}
    if(url.pathname===`/api/adaptive-plans/${fixture.snapshot().plan.id}`&&method==='GET')return route.fulfill({json:fixture.snapshot()});
    throw Error(`Unexpected grounded fixture request: ${method} ${url.pathname}`);
  };
  return fixture;
}

export async function checkGroundedVisuals({newPage,origin,settleTheme,noOverflow,snapshot,findings}) {
  findings.groundedPlanning=[];
  for(const width of [1440,390]) {
    const fixture=createGroundedFixture(),{page,context}=await newPage({width,production:true,adaptive:fixture});
    await page.goto(origin);await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();
    for(const name of ['destination','departureCity','startDate','endDate'])await page.locator(`input[name=${name}]`).fill(groundedPreferences[name]);
    await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
    await page.getByText('Research is requested only when planning needs outside information.',{exact:false}).waitFor();await noOverflow(page,`grounded-review-${width}`);await snapshot(page,`grounded-review-${width}`);
    await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByRole('heading',{name:'Days taking shape',exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'Research notes',exact:true}).count(),0);
    await page.getByText('3 of 9 days planned',{exact:true}).waitFor();await settleTheme(page,'JP');await noOverflow(page,`grounded-draft-only-${width}`);await snapshot(page,`grounded-draft-only-${width}`);
    const expenses=page.getByRole('region',{name:'Retained plan cost summary',exact:true});await expenses.getByText('Whole retained-plan category breakdown',{exact:true}).click();await expenses.locator('.budget-list').nth(1).waitFor();await expenses.getByText('Optional 10% contingency suggestion',{exact:true}).click();await expenses.scrollIntoViewIfNeeded();await snapshot(page,`partial-retained-expenses-${width}`);
    fixture.phase='researching';await page.getByRole('heading',{name:'Researching your journey.',exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'Days taking shape',exact:true}).count(),0);assert.equal(fixture.requests.filter(item=>item.method==='POST').length,1);
    fixture.phase='draft-three';await page.getByRole('region',{name:'Provisional day 2028-01-06',exact:true}).waitFor();await page.getByText('3 of 9 days planned',{exact:true}).waitFor();
    await page.getByText('Read the research notes',{exact:true}).click();await page.getByText('Sources consulted (1)',{exact:true}).click();const link=page.getByRole('link',{name:'Visitor information',exact:true});assert.equal(await link.getAttribute('href'),'https://example.com/visitor-info');assert.equal(await link.getAttribute('rel'),'noopener noreferrer');
    await noOverflow(page,`grounded-sources-drafts-${width}`);await snapshot(page,`grounded-sources-drafts-${width}`);
    fixture.phase='failed';await page.getByRole('button',{name:'Retry research',exact:true}).waitFor();await noOverflow(page,`grounded-research-failure-${width}`);await snapshot(page,`grounded-research-failure-${width}`);
    await page.getByRole('button',{name:'Retry research',exact:true}).click();await page.getByRole('heading',{name:'Researching your journey.',exact:true}).waitFor();assert.equal(fixture.requests.filter(item=>item.path.endsWith('/research/retry')).length,1);
    fixture.phase='allowance';await page.getByRole('button',{name:'Continue with another run',exact:true}).waitFor();const before=fixture.requests.filter(item=>item.method==='POST').length;await page.getByRole('button',{name:'Continue with another run',exact:true}).click();assert.equal(fixture.requests.filter(item=>item.method==='POST').length,before);
    await noOverflow(page,`grounded-continue-confirmation-${width}`);await snapshot(page,`grounded-continue-confirmation-${width}`);await page.getByRole('button',{name:'Not now',exact:true}).click();assert.equal(fixture.requests.filter(item=>item.method==='POST').length,before);
    await page.getByRole('button',{name:'Continue with another run',exact:true}).click();await page.getByRole('button',{name:'Yes, continue this trip',exact:true}).click();await page.getByRole('heading',{name:'Researching your journey.',exact:true}).waitFor();
    fixture.phase='unknown';await page.getByRole('button',{name:'Check planning status',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Retry research',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Continue with another run',exact:true}).count(),0);await noOverflow(page,`grounded-uncertain-${width}`);await snapshot(page,`grounded-uncertain-${width}`);
    assert.deepEqual(fixture.requests.filter(item=>item.method==='POST').map(item=>item.path),['/api/adaptive-plans',`/api/adaptive-plans/${fixture.snapshot().plan.id}/research/retry`,`/api/adaptive-plans/${fixture.snapshot().plan.id}/continue`]);findings.groundedPlanning.push(width);await context.close();
  }
}
