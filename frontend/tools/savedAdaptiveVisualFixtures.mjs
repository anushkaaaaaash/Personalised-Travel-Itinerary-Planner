import {syntheticPdf,assertPdfDownload} from './pdfVisualFixture.mjs';
import assert from 'node:assert/strict';
import {savedFixture,savedId} from '../test/savedAdaptiveFixture.js';
export function createSavedAdaptiveVisualFixture(){
 const f=savedFixture();let submitted=null,saved=false,deleted=false,writes=0;
 const fixture={savedEnabled:true,policy:{sectionDays:3,maxSubmissionsPerRun:12},requests:[],handle:async(route,url)=>{
  const method=route.request().method();fixture.requests.push({method,path:url.pathname});
  if(url.pathname==='/api/adaptive-plans/current')return route.fulfill({status:404,json:{error:{code:'SECTION_CURRENT_NOT_FOUND'}}});
  if(url.pathname==='/api/adaptive-plans'&&method==='POST'){const body=route.request().postDataJSON();assert.equal(body.preferences.endDate,'2028-01-18');f.base.plan.requestId=body.requestId;return route.fulfill({json:f.base});}
  if(url.pathname===`/api/adaptive-plans/${f.base.plan.id}/save`&&method==='POST'){
   const body=route.request().postDataJSON();if(submitted)assert.deepEqual(body,submitted);submitted=body;writes++;saved=writes===2;f.summary.requestId=body.requestId;f.summary.title=body.title;
   return route.fulfill({json:f.operation(saved?6:3,{requestId:body.requestId,title:body.title,...(saved?{saved:f.summary}:{})})});
  }
  if(url.pathname==='/api/saved-adaptive-trips')return route.fulfill({json:{items:saved&&!deleted?[f.summary]:[],hasMore:false,offset:0}});
  if(url.pathname===`/api/saved-adaptive-trips/${savedId}/export`){assert.equal(method,'GET');assert.equal(route.request().headers().accept,'application/pdf');assert.ok(saved&&!deleted);return route.fulfill({contentType:'application/pdf',body:syntheticPdf('Saved itinerary: 18 of 18 days')});}
  if(url.pathname===`/api/saved-adaptive-trips/${savedId}`){
   if(method==='DELETE'){assert.deepEqual(route.request().postDataJSON(),{version:1});deleted=true;return route.fulfill({json:{id:savedId,deleted:true,version:1}});}
   assert.equal(method,'GET');if(deleted)return route.fulfill({status:404,json:{error:{code:'SAVED_ADAPTIVE_NOT_FOUND'}}});return route.fulfill({json:f.page(Number(url.searchParams.get('afterSequence')||0))});
  }
  throw Error(`Unexpected synthetic saved trip request: ${method} ${url.pathname}`);
 }};return fixture;
}
export async function checkSavedAdaptiveVisuals({newPage,origin,settleTheme,noOverflow,snapshot,findings}){
 findings.savedAdaptiveWidths=[];
 for(const width of [1440,390]){
  const adaptive=createSavedAdaptiveVisualFixture(),{page,context}=await newPage({width,production:true,adaptive});
  await page.goto(origin);await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('input[name=destination]').fill('Kyoto');await page.locator('input[name=departureCity]').fill('Tokyo');await page.locator('input[name=startDate]').fill('2028-01-01');await page.locator('input[name=endDate]').fill('2028-01-18');
  await page.getByRole('button',{name:/Next:/}).click();await page.locator('input[name=budget]').fill('5000');await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:'Build my trip →',exact:true}).click();
  await page.getByRole('heading',{name:'Save this version to your account',exact:true}).waitFor();await settleTheme(page,'JP');await page.getByLabel('Trip name',{exact:true}).fill('Eighteen days in Kyoto');
  await noOverflow(page,`adaptive-save-ready-${width}`);await snapshot(page,`adaptive-save-ready-${width}`);
  await page.getByRole('button',{name:'Save this trip',exact:true}).click();await page.getByRole('link',{name:'Open saved trip',exact:true}).waitFor();assert.equal(adaptive.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/save')).length,2);
  await noOverflow(page,`adaptive-save-confirmed-${width}`);await snapshot(page,`adaptive-save-confirmed-${width}`);
  await page.getByRole('link',{name:'Open saved trip',exact:true}).click();await page.getByText('Costs cover all 18 saved days',{exact:false}).waitFor();await settleTheme(page,'JP');
  await page.locator('.adaptive-day > summary').first().click();await page.getByText(/Example Garden Café \(synthetic venue\)/).waitFor();await noOverflow(page,`saved-adaptive-trip-${width}`);await snapshot(page,`saved-adaptive-trip-${width}`);
  const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'Download itinerary PDF',exact:true}).click();await assertPdfDownload(await downloaded,savedId,'Saved itinerary: 18 of 18 days');
  await page.getByRole('button',{name:'Next days',exact:true}).click();await page.getByRole('region',{name:'Saved trip days 2028-01-16 to 2028-01-18',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Next days',exact:true}).isDisabled(),true);
  await page.getByRole('link',{name:'← Back to saved trips',exact:true}).click();await page.getByRole('heading',{name:'Your complete saved trips',exact:true}).waitFor();await page.getByRole('link',{name:'Eighteen days in Kyoto',exact:true}).waitFor();await noOverflow(page,`saved-adaptive-collection-${width}`);await snapshot(page,`saved-adaptive-collection-${width}`);
  await page.getByRole('link',{name:'Eighteen days in Kyoto',exact:true}).click();await page.getByRole('button',{name:'Delete saved copy',exact:true}).click();assert.equal(adaptive.requests.filter(r=>r.method==='DELETE').length,0);await noOverflow(page,`saved-adaptive-delete-confirm-${width}`);await snapshot(page,`saved-adaptive-delete-confirm-${width}`);
  await page.getByRole('button',{name:'Confirm delete saved copy',exact:true}).click();await page.getByText('This saved account copy was deleted. The original temporary plan is unchanged.',{exact:true}).waitFor();assert.equal(adaptive.requests.filter(r=>r.method==='DELETE').length,1);
  findings.savedAdaptiveWidths.push(width);await context.close();
 }
}
