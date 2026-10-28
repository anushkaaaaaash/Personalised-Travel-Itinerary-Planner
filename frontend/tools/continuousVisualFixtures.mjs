import assert from 'node:assert/strict';
import {continuousDayFixture} from '../test/continuousDayFixture.js';
export async function checkContinuousDayVisuals({newPage,origin,settleTheme,noOverflow,snapshot,findings}){
 findings.continuousDays=[];
 for(const width of [1440,390]){
  const f=continuousDayFixture(),requests=[];
  const adaptive={policy:{sectionDays:3,maxSubmissionsPerRun:12,researchEnabled:true,maxWebSearchCalls:6,researchMode:'on_demand',provisionalDayPreviews:true,responseDeadlineMinutes:30},handle:async(route,url)=>{
   const method=route.request().method();requests.push({method,path:url.pathname,cursor:url.searchParams.get('afterSequence')});
   if(method==='GET'&&url.pathname==='/api/adaptive-plans/current')return route.fulfill({status:404,json:{error:{code:'SECTION_CURRENT_NOT_FOUND'}}});
   if(method==='POST'&&url.pathname==='/api/adaptive-plans'){f.plan.requestId=route.request().postDataJSON().requestId;return route.fulfill({status:202,json:f.page(0)});}
   if(method==='GET'&&url.pathname===`/api/adaptive-plans/${f.plan.id}`)return route.fulfill({json:f.page(Number(url.searchParams.get('afterSequence')||0))});
   throw Error(`Unexpected synthetic continuous-day request: ${method} ${url.pathname}`);
  }};
  const{page,context}=await newPage({width,production:true,adaptive});await page.goto(origin);
  await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  for(const key of ['destination','departureCity','startDate','endDate'])await page.locator(`input[name=${key}]`).fill(f.preferences[key]);
  await page.getByRole('button',{name:/Next:/}).click();await page.locator('input[name=budget]').fill(String(f.preferences.budget));await page.getByRole('button',{name:/Next:/}).click();
  await page.getByText('Planning usage & limits',{exact:true}).click();await page.getByText(/up to 30 minutes while available/).waitFor();await snapshot(page,`continuous-usage-${width}`);
  await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByText('17 of 17 days planned',{exact:true}).waitFor();await page.getByText(/17 of 17 planned days loaded/).waitFor();await settleTheme(page,'JP');
  const cards=page.locator('details.card.adaptive-day');assert.equal(await cards.count(),17);assert.match(await cards.first().locator(':scope > summary').innerText(),/Day 01/);assert.match(await cards.last().locator(':scope > summary').innerText(),/Day 17/);assert.equal(await page.getByRole('button',{name:'Next days',exact:true}).count(),0);
  await cards.last().locator(':scope > summary').click();await noOverflow(page,`continuous-seventeen-days-${width}`);await snapshot(page,`continuous-seventeen-days-${width}`);
  assert.equal(requests.filter(r=>r.method==='POST').length,1);assert.deepEqual(requests.filter(r=>r.cursor!==null).map(r=>r.cursor),['3','6']);findings.continuousDays.push(width);await context.close();
 }
}
