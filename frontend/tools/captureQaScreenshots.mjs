/** CI-only renderer for approved synthetic static QA; never run against account pages. */
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { createRequire } from 'node:module';
const dist=resolve('frontend/dist');
const out=resolve(process.env.QA_ARTIFACT_DIR || 'visual-qa-artifacts');
const require=createRequire(resolve(process.env.QA_TOOLS_DIR,'package.json'));
const {chromium}=require('playwright');
const report={commit:process.env.GITHUB_SHA || 'unknown',synthetic:true,scope:'Static real-component fixtures only; no auth/API/provider requests.',screens:[],errors:[],networkRequests:[]};
await mkdir(out,{recursive:true});
let browser;
const server=createServer(async(req,res)=>{
 try{
  const url=new URL(req.url,'http://127.0.0.1');
  if(!/^\/__qa\/(?:discovery|loading|itinerary)\.html$/.test(url.pathname)){res.writeHead(404);res.end('Only approved static QA pages are served.');return;}
  const file=resolve(dist,`.${url.pathname}`);
  if(!file.startsWith(`${dist}${sep}`)||!(await stat(file)).isFile())throw Error('Missing static QA page');
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(await readFile(file));
 }catch{res.writeHead(404);res.end('Static QA fixture unavailable.');}
});
try{
 await new Promise(resolve=>server.listen(4173,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true});
 report.browserVersion=browser.version();
 for(const [device,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
  const context=await browser.newContext({viewport,deviceScaleFactor:1,reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin==='http://127.0.0.1:4173' && url.pathname==='/favicon.ico'){await route.fulfill({status:204,body:''});return;}
   const allowed=url.origin==='http://127.0.0.1:4173' && /^\/__qa\/(?:discovery|loading|itinerary)\.html$/.test(url.pathname);
   report.networkRequests.push({method:route.request().method(),url:url.href,allowed});
   if(!allowed){report.errors.push(`Blocked unexpected browser request: ${url.href}`);await route.abort();return;}
   await route.continue();
  });
  for(const screen of ['discovery','loading','itinerary']){
   const page=await context.newPage();const entry={screen,device,viewport,errors:[]};report.screens.push(entry);
   page.on('pageerror',error=>entry.errors.push(`Page error: ${error.message}`));
   page.on('console',message=>{if(message.type()==='error')entry.errors.push(`Console error: ${message.text()}`);});
   try{
    const response=await page.goto(`http://127.0.0.1:4173/__qa/${screen}.html`,{waitUntil:'networkidle',timeout:30000});
    if(response.status()!==200)throw Error(`HTTP ${response.status()}`);
    await page.evaluate(async()=>{await document.fonts.ready;});
    await page.locator('h1').waitFor({state:'visible'});
    entry.title=await page.title();entry.fontsStatus=await page.evaluate(()=>document.fonts.status);
    entry.layout=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,overflowElements:[...document.querySelectorAll('body *')].filter(el=>{const box=el.getBoundingClientRect();return box.width>0 && (box.right>innerWidth+1 || box.left < -1) && getComputedStyle(el).position!=='absolute';}).slice(0,15).map(el=>({tag:el.tagName,className:el.className,left:Math.round(el.getBoundingClientRect().left),right:Math.round(el.getBoundingClientRect().right)}))}));
    if(entry.layout.document>viewport.width+1 || entry.layout.body>viewport.width+1)entry.errors.push('Horizontal page overflow detected.');
    entry.screenshot=`${device}-${screen}.png`;
    await page.screenshot({path:resolve(out,entry.screenshot),fullPage:true,animations:'disabled',timeout:30000});
   }catch(error){entry.errors.push(error.message);try{await page.screenshot({path:resolve(out,`${device}-${screen}-error.png`),fullPage:true});}catch{}}
   report.errors.push(...entry.errors.map(error=>`${device}/${screen}: ${error}`));await page.close();
  }
  await context.close();
 }
}catch(error){report.errors.push(`Render setup failed: ${error.message}`);}
finally{
 await browser?.close();await new Promise(resolve=>server.close(resolve));
 await writeFile(resolve(out,'render-report.json'),JSON.stringify(report,null,2));
 await writeFile(resolve(out,'README.txt'),'Travel Planner synthetic visual QA\nReal components and CSS, rendered from static preview fixtures.\nScreenshots: desktop 1440x1000 and mobile 390x844; full-page PNGs.\nReduced motion enabled for deterministic captures.\nSee render-report.json for network allowlist, layout and render errors.\nNo account, API, database or provider requests are allowed.\n');
}
console.log(JSON.stringify({screens:report.screens.length,errors:report.errors.length,artifactDirectory:out}));
if(report.errors.length || report.screens.length!==6)process.exitCode=1;
