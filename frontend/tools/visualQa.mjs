import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { COUNTRY_THEMES } from '../src/themes/countryThemes.js';
import { plan as fixturePlan, detail as fixtureDetail } from '../test/shareFixture.js';
import { checkAdaptiveVisuals } from './adaptiveVisualFixtures.mjs';

const { chromium } = await import(pathToFileURL(path.join(process.env.QA_NODE_MODULES, 'playwright/index.mjs')).href);
const dist = path.resolve(fileURLToPath(new URL('../dist/', import.meta.url)));
const output = process.env.QA_OUTPUT;
assert.ok(output, 'QA_OUTPUT must point to the runner temporary artifact directory');
await mkdir(output, { recursive: true });
const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml' };
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (pathname.startsWith('/api/')) { response.writeHead(500); response.end('Unexpected unmocked request'); return; }
    const candidate = path.resolve(dist, '.' + pathname);
    if (candidate !== dist && !candidate.startsWith(dist + path.sep)) { response.writeHead(404); response.end(); return; }
    const filename = path.extname(candidate) ? candidate : path.join(dist, 'index.html');
    const body = await readFile(filename);
    response.writeHead(200, { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream' }); response.end(body);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless:true });
const findings = { screenshots:[], viewports:[], themes:[], errors:[], unexpectedRequests:[], confirmations:[], snapshotReadinessErrors:[], savedTrip:false, reducedMotion:false, destinationRecovery:false, adaptiveWidths:[], adaptiveUncertainty:false, adaptiveExports:[], adaptiveCompleteExport:false, adaptiveTravelDay:false };
const liveConfig = { enabled:true, mode:'production', ownership_enabled:true, planning_jobs_enabled:false };
const localConfig = { enabled:false, mode:'local', ownership_enabled:false, planning_jobs_enabled:false };
let pendingGeneration;
const result = fixturePlan();
result.destination = 'Kyoto, Japan';
result.explanation = 'Quiet gardens, a little culture, and time to enjoy the city at your own pace.';
result.days[0].activities[0].title = 'Explore the museum collection';
result.days[0].activities[0].notes = 'Leave time to follow the exhibits that catch your eye.';
result.days[0].activities[1].title = 'A slower walk through the gardens';
result.days[0].dietaryNotes = 'Confirm ingredients and dietary requirements with each venue.';
result.days[0].mobilityNotes = 'Check step-free routes with the venues before visiting.';

async function newPage({width=1440,height=1050,production=false,reducedMotion='no-preference',confirmation='verified',adaptive=null}={}) {
  const context = await browser.newContext({viewport:{width,height},reducedMotion});
  const page = await context.newPage();
  const generationRequests = [];
  page.on('pageerror',error=>findings.errors.push(error.message));
  await context.route('**/*',route=>{
    const url = new URL(route.request().url());
    if(url.origin!==origin){findings.unexpectedRequests.push(url.origin+url.pathname);return route.abort();}
    return route.continue();
  });
  await context.route('**/api/**', async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/auth/config')return route.fulfill({json:adaptive?{...liveConfig,adaptive_planning_enabled:true,adaptive_planning_policy:{sectionDays:3,maxSubmissionsPerRun:3}}:production?liveConfig:localConfig});
    if(adaptive&&url.pathname.startsWith('/api/adaptive-plans'))return adaptive.handle(route,url);
    if(url.pathname==='/api/auth/login') return route.fulfill({json:{session:{access_token:'synthetic-ui-session',token_type:'bearer',expires_at:Date.now()/1000+3600},user:{id:'12345678-1234-1234-1234-123456789abc',email:'traveler@example.test'}}});
    if(url.pathname==='/api/saved-itineraries/32345678-1234-1234-1234-123456789abc')return route.fulfill({json:fixtureDetail()});
    if(url.pathname==='/api/auth/confirmation')return confirmation==='verified' ? route.fulfill({json:{confirmed:true}}) : route.fulfill({status:confirmation==='unverified'?401:503,json:{error:'Synthetic test response'}});
    if(url.pathname==='/api/itineraries/generate') {generationRequests.push(route.request().postDataJSON());pendingGeneration=(json=result,status=200)=>route.fulfill({status,json});return;}
    findings.unexpectedRequests.push(url.pathname);return route.abort();
  });
  return {page,context,generationRequests};
}
async function snapshot(page,name) {
  const selector = '.page, .welcome-hero__copy, .account-shell--welcome, .email-confirmation, .planner-fields, .results-hero, .day-card, .destination-loading__postcard';
  try {
    await page.waitForFunction(selector => [...document.querySelectorAll(selector)].every(element => {
      const style = getComputedStyle(element);
      const hidden = !element.getClientRects().length || element.closest('details:not([open])') || style.display === 'none' || ['hidden','collapse'].includes(style.visibility);
      return hidden || Number(style.opacity) >= .99;
    }), selector);
  } catch(error) {
    const elements = await page.evaluate(selector => [...document.querySelectorAll(selector)].slice(0,30).map(element => {
      const style = getComputedStyle(element);
      return {className:element.getAttribute('class'),display:style.display,visibility:style.visibility,opacity:style.opacity,rects:element.getClientRects().length,closedDetails:Boolean(element.closest('details:not([open])'))};
    }), selector);
    findings.snapshotReadinessErrors.push({name,elements});
    throw error;
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path:path.join(output,name+'.png'),fullPage:true,animations:'disabled'});findings.screenshots.push(name+'.png');
}
async function noOverflow(page,label) {
  const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  findings.viewports.push({label,...layout});assert.ok(layout.scroll<=layout.width+1&&layout.body<=layout.width+1,`${label}: horizontal overflow ${JSON.stringify(layout)}`);
}
async function settleTheme(page,code) { await page.waitForFunction(code=>document.documentElement.dataset.destinationTheme===code,code);await page.waitForTimeout(500); }

try {
  for(const width of [1440,768,390,320]) {
    const {page,context}=await newPage({width});
    await page.goto(origin);await page.locator('input[name=destination]').waitFor();await page.waitForTimeout(500);
    await noOverflow(page,`default-${width}`);await snapshot(page,`planner-default-${width}`);
    await page.locator('input[name=destination]').fill('Kyoto, Japan');await settleTheme(page,'JP');
    await noOverflow(page,`japan-${width}`);
    assert.ok(await page.locator('input[type=date]').evaluateAll(elements=>elements.every(element=>element.getBoundingClientRect().width>=140)),'Dates stay wide enough to read');
    await snapshot(page,`planner-japan-${width}`);
    if(width===1440) {
      for(const theme of COUNTRY_THEMES) {
        await page.locator('input[name=destination]').fill(theme.name);
        await page.waitForFunction(code=>document.documentElement.dataset.destinationTheme===code,theme.code);
        const expected=theme.primary.slice(1).match(/../g).map(value=>parseInt(value,16));
        await page.waitForTimeout(300);
        const finalColor=await page.locator('.generate-btn').evaluate(element=>getComputedStyle(element).backgroundColor);
        assert.equal(finalColor,`rgb(${expected.join(', ')})`,theme.name);findings.themes.push(theme.code);
      }
      for(const [destination,code,name] of [['Goa, India','IN','india'],['Paris, France','FR','france'],['Dubai, UAE','AE','emirates']]){
        await page.locator('input[name=destination]').fill(destination);await settleTheme(page,code);await snapshot(page,`planner-${name}-1440`);
      }
      await page.locator('input[name=destination]').fill('Paris, Texas');await settleTheme(page,'WORLD');
      await page.locator('input[name=destination]').fill('Kyoto, Japan');await settleTheme(page,'JP');
    }
    if([390,768,1440].includes(width)) {
      await page.locator('input[name=departureCity]').fill('Tokyo');
      await page.locator('input[name=startDate]').fill('2028-02-28');await page.locator('input[name=endDate]').fill('2028-02-28');
      await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('heading',{name:/Step 2/}).waitFor();
      assert.equal(await page.locator('.step-heading').evaluate(element=>element===document.activeElement),true);
      await noOverflow(page,`preferences-${width}`);
      assert.ok((await page.locator('input[name=budget]').boundingBox()).width>=120,'Budget value stays readable');
      await snapshot(page,`preferences-${width}`);
      await page.getByRole('button',{name:'Back',exact:true}).click();assert.equal(await page.locator('input[name=destination]').inputValue(),'Kyoto, Japan');
      await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
      await snapshot(page,`review-${width}`);
      await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByRole('heading',{name:'Your trip is taking shape'}).waitFor();
      await noOverflow(page,`loading-${width}`);await snapshot(page,`loading-${width}`);
      await page.getByRole('button',{name:'Pause rotating cards and animation'}).click();
      assert.equal(await page.locator('.destination-loading__plane').evaluate(element=>getComputedStyle(element).animationPlayState),'paused');
      await page.getByRole('button',{name:'Next note',exact:true}).click();
      await pendingGeneration();pendingGeneration=null;
      await page.getByRole('heading',{name:/Make the days your own/}).waitFor();await noOverflow(page,`itinerary-${width}`);await snapshot(page,`itinerary-${width}`);
      await page.locator('summary').filter({hasText:'Make it more you'}).click();
      await page.getByRole('button',{name:'Update my plan',exact:true}).waitFor();
      assert.ok(await page.locator('.refinement-controls .form-grid select').evaluateAll(elements=>elements.every(element=>element.getBoundingClientRect().width>=200)),'Refinement selections stay readable');
      await noOverflow(page,`refinement-${width}`);await snapshot(page,`refinement-${width}`);
      await page.locator('summary').filter({hasText:'Make it more you'}).click();
      await page.getByRole('button',{name:/Trip preferences/}).click();await page.getByRole('button',{name:/Return to your itinerary/}).click();await page.getByRole('heading',{name:/Make the days your own/}).waitFor();
    }
    await context.close();
  }
  {
    const {page,context,generationRequests}=await newPage({width:390});
    await page.goto(origin);await page.locator('input[name=destination]').fill('Japan');await settleTheme(page,'JP');
    await page.locator('input[name=departureCity]').fill('Mumbai');
    await page.locator('input[name=startDate]').fill('2026-10-27');await page.locator('input[name=endDate]').fill('2026-11-19');
    await page.getByRole('button',{name:/Next:/}).click();
    await page.getByText(/Choose a trip of 1–14 days\. These dates cover 24 days/).waitFor();
    assert.equal(await page.locator('input[name=endDate]').inputValue(),'2026-11-19');
    assert.equal(generationRequests.length,0);
    await noOverflow(page,'date-range-recovery-390');await snapshot(page,'date-range-recovery-390');
    await page.locator('input[name=startDate]').fill('2028-02-28');await page.locator('input[name=endDate]').fill('2028-02-28');
    await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
    await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByRole('heading',{name:'Your trip is taking shape'}).waitFor();
    await pendingGeneration({...result,destination:'Japan'});pendingGeneration=null;
    await page.getByRole('heading',{name:/Make the days your own/}).waitFor();await settleTheme(page,'JP');
    await page.getByRole('button',{name:/Trip preferences/}).click();
    await page.getByRole('button',{name:'Back',exact:true}).click();await page.getByRole('button',{name:'Back',exact:true}).click();
    await page.locator('input[name=destination]').fill('France');await settleTheme(page,'FR');
    assert.equal(await page.locator('.generated-itinerary, .return-to-plan').count(),0);
    await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
    await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByRole('heading',{name:'Your trip is taking shape'}).waitFor();await settleTheme(page,'FR');
    await pendingGeneration({error:{code:'AI_PROVIDER_FAILED'}},502);pendingGeneration=null;
    await page.getByRole('heading',{name:'The planning service couldn’t finish.'}).waitFor();await settleTheme(page,'FR');
    await noOverflow(page,'generation-error-france-390');await snapshot(page,'generation-error-france-390');
    await page.getByRole('button',{name:'Edit trip details',exact:true}).click();
    assert.equal(await page.locator('input[name=destination]').inputValue(),'France');
    await page.getByRole('button',{name:/Next:/}).click();await page.getByRole('button',{name:/Next:/}).click();
    await page.getByRole('button',{name:'Build my trip →',exact:true}).click();await page.getByRole('heading',{name:'Your trip is taking shape'}).waitFor();
    await pendingGeneration({...result,destination:'France',explanation:'A fresh plan for France.'});pendingGeneration=null;
    await page.getByRole('heading',{name:/France.*Make the days your own/}).waitFor();await settleTheme(page,'FR');
    assert.equal(await page.locator('.generated-itinerary').getByText('Japan',{exact:true}).count(),0);
    assert.deepEqual(generationRequests.map(request=>request.destination),['Japan','France','France']);
    await noOverflow(page,'fresh-result-france-390');await snapshot(page,'fresh-result-france-390');
    await page.reload();await page.locator('input[name=destination]').waitFor();await settleTheme(page,'WORLD');
    assert.equal(await page.locator('input[name=destination]').inputValue(),'');assert.equal(await page.locator('.generated-itinerary').count(),0);
    findings.destinationRecovery=true;await context.close();
  }
  for(const width of [1440,390,320]){
    const {page,context}=await newPage({width,production:true});await page.goto(origin);await page.locator('input[type=email]').waitFor();await noOverflow(page,`welcome-${width}`);await snapshot(page,`welcome-${width}`);await context.close();
  }
  for(const status of ['verified','unverified','unavailable']) {
    const {page,context}=await newPage({width:390,production:true,confirmation:status});
    await page.goto(`${origin}/#access_token=synthetic-confirmation-token&refresh_token=synthetic-refresh&type=signup&token_type=bearer`);
    await page.locator(`.email-confirmation--${status}`).waitFor();
    assert.equal(new URL(page.url()).hash,'');
    const stored=await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}));assert.doesNotMatch(stored,/synthetic-confirmation|synthetic-refresh/);
    await noOverflow(page,`confirmation-${status}`);await snapshot(page,`confirmation-${status}`);
    await page.getByRole('button',{name:'Continue to sign in',exact:true}).click();await page.locator('input[type=email]').waitFor();
    findings.confirmations.push(status);await context.close();
  }
  for(const width of [1440,390]) {
    const {page,context}=await newPage({width,production:true});
    await page.goto(`${origin}/itineraries/32345678-1234-1234-1234-123456789abc`);
    await page.locator('input[type=email]').fill('traveler@example.test');await page.locator('input[type=password]').fill('synthetic-test-only');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:'Your saved trip',exact:true}).waitFor();await settleTheme(page,'JP');
    await noOverflow(page,`saved-trip-${width}`);await snapshot(page,`saved-trip-${width}`);
    await page.getByLabel('Itinerary title').fill('A quiet day in Kyoto');
    page.once('dialog',dialog=>dialog.dismiss());await page.getByRole('link',{name:'Back to planner',exact:true}).click();
    assert.match(page.url(),/itineraries\/32345678/);
    await page.getByRole('button',{name:'Reload saved revision',exact:true}).click();
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    assert.equal(await page.getByLabel('Itinerary title').inputValue(),'A quiet day in Kyoto');
    findings.savedTrip=true;await context.close();
  }
  const {page,context}=await newPage({width:390,reducedMotion:'reduce'});
  await page.goto(origin);await page.locator('input[name=destination]').waitFor();await page.locator('input[name=destination]').fill('Kyoto, Japan');await settleTheme(page,'JP');
  const motion=await page.locator('.journey-artwork__route').evaluate(element=>({animation:getComputedStyle(element).animationName,transition:getComputedStyle(element).transitionDuration}));
  assert.equal(motion.animation,'none');assert.equal(motion.transition,'0s');findings.reducedMotion=true;await snapshot(page,'reduced-motion-390');await context.close();
  await checkAdaptiveVisuals({newPage,origin,settleTheme,noOverflow,snapshot,findings});
  assert.equal(findings.errors.length,0,findings.errors.join('\n'));assert.equal(findings.unexpectedRequests.length,0,findings.unexpectedRequests.join('\n'));
  assert.equal(findings.themes.length,60);
  console.log(JSON.stringify(findings,null,2));
} finally {
  await writeFile(path.join(output,'results.json'),JSON.stringify(findings,null,2));
  await browser.close();await new Promise(resolve=>server.close(resolve));
}
