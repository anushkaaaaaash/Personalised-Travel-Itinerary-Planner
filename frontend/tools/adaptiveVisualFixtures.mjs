import assert from 'node:assert/strict';
import { plan as itinerary } from '../test/shareFixture.js';

const id='11111111-1111-4111-8111-111111111111';
const sectionId=sequence=>`52345678-1234-1234-1234-${String(sequence).padStart(12,'0')}`;
const dateAt=(start,offset)=>new Date(Date.parse(`${start}T00:00:00Z`)+offset*86400000).toISOString().slice(0,10);

export function createAdaptiveFixture() {
  const fixture={phase:'active',preferences:null,requestId:null,requests:[],pendingCancel:null,finalTravelDay:false};
  fixture.snapshot=()=>{
    const p=fixture.preferences;
    const totalDays=(Date.parse(p.endDate)-Date.parse(p.startDate))/86400000+1;
    const completedDays=fixture.phase==='completed'?totalDays:fixture.phase==='active'?3:9;
    const sections=Array.from({length:Math.min(3,Math.ceil(completedDays/3))},(_,index)=>{
      const days=Math.min(3,completedDays-index*3),sequence=index+1,startDate=dateAt(p.startDate,index*3),endDate=dateAt(startDate,days-1);
      const result=itinerary();result.destination=p.destination;result.currency=p.currency;result.travelPace=p.travelPace;result.travelStyle=p.travelStyle;result.provider='openai';result.model='gpt-6-luna';
      result.days=Array.from({length:days},(_,day)=>({...structuredClone(result.days[0]),date:dateAt(startDate,day)}));
      if(fixture.finalTravelDay)for(const day of result.days){
        if(day.date===p.endDate){day.mainActivityCount=0;day.activities=[{...day.activities[0],id:'return-transfer',title:'Return journey',kind:'transfer',durationMinutes:120}];day.morning='Return travel';day.afternoon='Arrival and rest';day.evening='Rest at home';}
        else{day.activities.push({...day.activities[0],id:'c',title:'Local experience',startTime:'14:00'});day.mainActivityCount=3;}
      }
      result.estimatedTotalGroupCost=days*150;result.remainingBudget=p.budget-days*150;result.explanation='A synthetic section with space for activities, transfers and rest.';
      return {id:sectionId(sequence),sequence,startDate,endDate,checkpoint:{itinerary:result,startLocation:sequence===1?p.departureCity:p.destination,endLocation:endDate===p.endDate?p.departureCity:p.destination,spentCents:days*15000,journeyStrategy:{summary:'A synthetic single-destination trip for interface checks.',stays:[{startDate:p.startDate,endDate:p.endDate,location:p.destination}]},provenance:{provider:'openai',model:'gpt-6-luna',validationVersion:'adaptive-section-v1'}}};
    });
    let status='paused',pauseReason='RESOURCE_ALLOWANCE_REACHED',remainingCreates=0,activeSection=null;
    if(fixture.phase==='active'){status='active';pauseReason=null;remainingCreates=2;activeSection={id:sectionId(99),status:'running',errorCode:null};}
    if(fixture.phase==='constraint') {pauseReason='SECTION_FAILED';remainingCreates=2;activeSection={id:sectionId(99),status:'failed',errorCode:'SECTION_CONSTRAINT_CONFLICT',failureDetails:{applicability:'proposed',explanation:'The proposed transfers leave too little rest for this section.',recommendations:[{field:'travelPace',reason:'The proposed daily schedule leaves too little time between activities and transfers.',suggestion:'Consider a slower pace for the remaining activities, then review the new plan.'}]}};}
    if(fixture.phase==='unknown'){pauseReason='SUBMISSION_UNKNOWN';remainingCreates=2;activeSection={id:sectionId(99),status:'submission_unknown',errorCode:'SUBMISSION_UNKNOWN'};}
    if(fixture.phase==='cancelled'){status='cancelled';pauseReason=null;remainingCreates=2;}
    if(fixture.phase==='completed'){status='completed';pauseReason=null;remainingCreates=0;}
    return {preferences:p,plan:{id,requestId:fixture.requestId,status,completedDays,totalDays,estimatedSections:Math.ceil(totalDays/3),runAllowance:3,remainingCreates,spentCents:completedDays*15000,totalBudgetCents:Math.round(p.budget*100),pauseReason,activeSection,expiresAt:'2029-01-01T00:00:00Z'},sections,nextCursor:null};
  };
  fixture.handle=async(route,url)=>{
    const method=route.request().method();fixture.requests.push({method,path:url.pathname});
    if(method==='POST'&&url.pathname==='/api/adaptive-plans') {const body=route.request().postDataJSON();fixture.preferences=body.preferences;fixture.requestId=body.requestId;return route.fulfill({status:202,json:fixture.snapshot()});}
    if(method==='POST'&&url.pathname.endsWith('/continue')) {fixture.phase='constraint';return route.fulfill({json:fixture.snapshot()});}
    if(method==='POST'&&url.pathname.endsWith('/cancel')) {fixture.pendingCancel=async()=>{fixture.phase='cancelled';await route.fulfill({json:fixture.snapshot()});};return;}
    if(method==='GET'&&url.pathname===`/api/adaptive-plans/${id}/export`)return route.fulfill({status:200,contentType:'text/plain; charset=utf-8',body:`ROAMORA RETAINED PLAN\n${fixture.phase==='completed'?'Full':'Partial'} snapshot: ${fixture.snapshot().plan.completedDays} of ${fixture.snapshot().plan.totalDays} days planned.\nSynthetic interface test; estimates, not bookings.\nEND OF ROAMORA EXPORT\n`});
    if(method==='GET'&&url.pathname===`/api/adaptive-plans/${id}`) return route.fulfill({json:fixture.snapshot()});
    throw Error(`Unexpected synthetic adaptive request: ${method} ${url.pathname}`);
  };
  return fixture;
}

export async function checkAdaptiveVisuals({newPage,origin,settleTheme,noOverflow,snapshot,findings}) {
  for(const width of [1440,390]) {
    const adaptive=createAdaptiveFixture();const {page,context}=await newPage({width,production:true,adaptive});
    await page.goto(origin);await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.locator('input[name=destination]').fill('Japan');await settleTheme(page,'JP');
    await page.locator('input[name=departureCity]').fill('Mumbai');await page.locator('input[name=startDate]').fill('2028-01-01');await page.locator('input[name=endDate]').fill('2028-02-15');
    assert.equal(await page.getByText(/Plan 1–14 days at a time/).count(),0);
    await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
    await page.getByText(/46-day trip starts with an estimated 16 sections/).waitFor();
    await noOverflow(page,`adaptive-review-${width}`);await snapshot(page,`adaptive-review-${width}`);
    await page.getByRole('button',{name:'Build my trip →',exact:true}).click();
    await page.getByText('3 of 46 days planned',{exact:true}).waitFor();await settleTheme(page,'JP');
    assert.equal(await page.locator('progress').getAttribute('value'),'3');assert.equal(await page.locator('progress').getAttribute('max'),'46');
    await page.locator('.adaptive-day > summary').first().click();
    await noOverflow(page,`adaptive-progress-${width}`);await snapshot(page,`adaptive-progress-${width}`);
    adaptive.phase='allowance';await page.getByRole('heading',{name:'Ready for the next part?'}).waitFor();
    assert.equal(adaptive.requests.filter(request=>request.method==='POST').length,1);
    await noOverflow(page,`adaptive-paused-${width}`);await snapshot(page,`adaptive-paused-${width}`);
    const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'Download retained plan (.txt)',exact:true}).click();const download=await downloaded;
    assert.equal(download.suggestedFilename(),`roamora-retained-plan-${id}.txt`);assert.equal(await download.failure(),null);
    const stream=await download.createReadStream();const chunks=[];for await(const chunk of stream)chunks.push(chunk);const exported=Buffer.concat(chunks).toString('utf8');
    assert.match(exported,/Partial snapshot: 9 of 46 days/);assert.ok(exported.endsWith('\nEND OF ROAMORA EXPORT\n'));
    findings.adaptiveExports.push(width);
    await page.getByRole('button',{name:'Continue planning',exact:true}).click();
    await page.getByRole('heading',{name:'Suggestions for this part of your trip.'}).waitFor();
    await page.getByRole('button',{name:'Retry remaining section',exact:true}).waitFor();assert.equal(adaptive.requests.filter(request=>request.method==='POST').length,2);
    await noOverflow(page,`adaptive-suggestions-${width}`);await snapshot(page,`adaptive-suggestions-${width}`);
    await page.getByRole('button',{name:'Stop planning and review changes',exact:true}).click();
    await page.getByRole('heading',{name:'Stopping planning…'}).waitFor();assert.equal(await page.locator('select[name=travelPace]').count(),0);
    assert.ok(adaptive.pendingCancel);await adaptive.pendingCancel();
    await page.getByRole('heading',{name:'Suggestions to review'}).waitFor();
    assert.equal(await page.locator('select[name=travelPace]').inputValue(),'balanced');
    assert.match(await page.locator('select[name=travelPace]').getAttribute('aria-describedby'),/travelPace-recovery/);
    await settleTheme(page,'JP');await noOverflow(page,`adaptive-edit-guidance-${width}`);await snapshot(page,`adaptive-edit-guidance-${width}`);
    await page.getByRole('button',{name:'Back',exact:true}).click();assert.equal(await page.locator('input[name=endDate]').inputValue(),'2028-02-15');
    assert.deepEqual(adaptive.requests.filter(request=>request.method==='POST').map(request=>request.path),['/api/adaptive-plans',`/api/adaptive-plans/${id}/continue`,`/api/adaptive-plans/${id}/cancel`]);
    findings.adaptiveWidths.push(width);await context.close();
  }
  const adaptive=createAdaptiveFixture();const {page,context}=await newPage({width:390,production:true,adaptive});
  await page.goto(origin);await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('input[name=destination]').fill('France');await settleTheme(page,'FR');await page.locator('input[name=departureCity]').fill('Mumbai');await page.locator('input[name=startDate]').fill('2028-01-01');await page.locator('input[name=endDate]').fill('2028-02-15');
  await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByText('3 of 46 days planned',{exact:true}).waitFor();
  adaptive.phase='unknown';await page.getByRole('button',{name:'Check planning status',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:/Continue planning|Try this section again/}).count(),0);
  await page.getByRole('button',{name:'Check planning status',exact:true}).click();
  assert.equal(adaptive.requests.filter(request=>request.method==='POST').length,1);
  await settleTheme(page,'FR');await noOverflow(page,'adaptive-uncertain-390');await snapshot(page,'adaptive-uncertain-390');
  findings.adaptiveUncertainty=true;await context.close();
  const complete=createAdaptiveFixture();complete.phase='completed';complete.finalTravelDay=true;const final=await newPage({width:390,production:true,adaptive:complete});
  await final.page.goto(origin);await final.page.locator('input[type=email]').fill('traveler@example.test');await final.page.locator('input[type=password]').fill('synthetic-test-only');await final.page.getByRole('button',{name:'Sign in',exact:true}).click();
  await final.page.locator('input[name=destination]').fill('France');await final.page.locator('input[name=departureCity]').fill('Mumbai');await final.page.locator('input[name=startDate]').fill('2028-01-01');await final.page.locator('input[name=endDate]').fill('2028-01-03');
  await final.page.getByRole('button',{name:/Next:/}).click();await final.page.locator('select[name=travelPace]').selectOption('fast');await final.page.getByRole('button',{name:/Next:/}).click();await final.page.getByRole('button',{name:'Build my trip →',exact:true}).click();
  await final.page.getByRole('heading',{name:'Your full date range is planned.'}).waitFor();await final.page.getByText('Full-date snapshot.',{exact:true}).waitFor();await settleTheme(final.page,'FR');
  const travelDay=final.page.locator('.adaptive-day').last();await travelDay.locator('summary').click();await travelDay.getByText('Return journey',{exact:true}).waitFor();assert.match(await travelDay.locator('summary').innerText(),/0 main activities/);findings.adaptiveTravelDay=true;
  await noOverflow(final.page,'adaptive-complete-export-390');await snapshot(final.page,'adaptive-complete-export-390');
  const downloaded=final.page.waitForEvent('download');await final.page.getByRole('button',{name:'Download retained plan (.txt)',exact:true}).click();const download=await downloaded;
  assert.equal(download.suggestedFilename(),`roamora-retained-plan-${id}.txt`);assert.equal(await download.failure(),null);const stream=await download.createReadStream();const chunks=[];for await(const chunk of stream)chunks.push(chunk);const exported=Buffer.concat(chunks).toString('utf8');
  assert.match(exported,/Full snapshot: 3 of 3 days/);assert.ok(exported.endsWith('\nEND OF ROAMORA EXPORT\n'));assert.equal(complete.requests.filter(request=>request.method==='POST').length,1);findings.adaptiveCompleteExport=true;await final.context.close();
}
