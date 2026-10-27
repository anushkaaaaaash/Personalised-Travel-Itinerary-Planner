import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';
import { COUNTRY_THEMES, THEME_COVERAGE_SOURCE } from '../src/themes/countryThemes.js';
import { DEFAULT_THEME, normalizeDestination, resolveDestinationTheme, themeTokens } from '../src/themes/themeTokens.js';

const baseline = 'FR ES US TR IT MX GB DE JP CN GR TH AT AE SA PT MY HK NL IN CA PL DK VN MA HR KR RU MO EG CZ ID HU SG CH AL KZ TN UZ BE KG ZA SE BG DO AU TW IR CO BR'.split(' ');
function luminance(hex) { return hex.slice(1).match(/../g).map(value => parseInt(value,16)/255).map(value => value <= .04045 ? value/12.92 : ((value+.055)/1.055)**2.4).reduce((total,value,index) => total+value*[.2126,.7152,.0722][index],0); }
function contrast(a,b) { const values=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (values[0]+.05)/(values[1]+.05); }

test('60 independent destination palettes cover the complete documented provisional top-50 baseline', () => {
  assert.equal(COUNTRY_THEMES.length,60);
  assert.equal(new Set(COUNTRY_THEMES.map(theme=>theme.code)).size,60);
  assert.equal(new Set(COUNTRY_THEMES.map(theme=>theme.name)).size,60);
  assert.equal(new Set(COUNTRY_THEMES.map(theme=>JSON.stringify(themeTokens(theme)))).size,60);
  for(const code of baseline) assert.ok(COUNTRY_THEMES.some(theme=>theme.code===code),code);
  assert.equal(THEME_COVERAGE_SOURCE.rankingYear,2024);
  assert.match(THEME_COVERAGE_SOURCE.note,/provisional/);
  assert.match(THEME_COVERAGE_SOURCE.note,/territories/);
});

test('all themes retain WCAG AA normal-text contrast on their button, wash and canvas surfaces', () => {
  for(const theme of [DEFAULT_THEME,...COUNTRY_THEMES]) {
    for(const property of ['primary','accent','canvas','wash','glow']) assert.match(theme[property],/^#[0-9a-f]{6}$/i);
    assert.ok(contrast('#ffffff',theme.primary)>=4.5,`${theme.name} primary button`);
    for(const surface of [theme.canvas,theme.wash,'#fffefa']) {
      assert.ok(contrast(theme.primary,surface)>=4.5,`${theme.name} themed text`);
      assert.ok(contrast('#24332e',surface)>=4.5,`${theme.name} body text`);
      assert.ok(contrast('#525f58',surface)>=4.5,`${theme.name} supporting text`);
    }
  }
});

test('country and curated city resolution is exact, accent-insensitive and never substring-based', () => {
  const resolve=value=>resolveDestinationTheme(value,COUNTRY_THEMES).code;
  for(const theme of COUNTRY_THEMES) {
    assert.equal(resolve(theme.name),theme.code);
    assert.equal(resolve(`A new city, ${theme.name}`),theme.code);
    for(const alias of theme.aliases) assert.equal(resolve(alias),theme.code);
    for(const city of theme.cities) assert.equal(resolve(city),theme.code);
  }
  for(const [input,expected] of [['  KYOTO , JAPAN  ','JP'],['İstanbul, Türkiye','TR'],['São Paulo','BR'],['Prague, Czech Republic','CZ'],['Dubai, U.A.E.','AE'],['London, UK','GB'],['Hong Kong, China','HK']]) assert.equal(resolve(input),expected);
  for(const input of ['',null,[],{},'constructor','__proto__','toString','New England','Paris, Texas','Japanland','London and Paris','Tokyo, Unknown Country','Unknown city']) assert.equal(resolve(input),'WORLD',String(input));
  assert.equal(normalizeDestination('  São   Paulo '),'sao paulo');
});

test('theme catalogue is deferred, visual-only and entirely local; motion and mobile safeguards stay present',async()=>{
  const provider=await readFile(new URL('../src/themes/DestinationTheme.jsx',import.meta.url),'utf8');
  assert.match(provider,/import\('\.\/countryThemes\.js'\)/);
  assert.match(provider,/requestIdleCallback/);
  assert.match(provider,/cancelIdleCallback/);
  assert.doesNotMatch(provider,/localStorage|sessionStorage|fetch\(/);
  const css=await readFile(new URL('../src/themes/roamora.css',import.meta.url),'utf8');
  assert.match(css,/prefers-reduced-motion: reduce/);assert.match(css,/forced-colors: active/);
  assert.match(css,/min-height: 44px/);assert.match(css,/max-width: 340px/);
});

test('late catalogue arrival uses the latest destination; fallback and unmount restore root tokens',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const priorDocument=globalThis.document;let renderer,resolveLoad;
  const style=new Map([['--sea','#123456']]);const root={dataset:{},style:{getPropertyValue:key=>style.get(key)||'',setProperty:(key,value)=>style.set(key,value),removeProperty:key=>style.delete(key)}};
  try {
    const {DestinationThemeProvider,useDestinationTheme}=await server.ssrLoadModule('/src/themes/DestinationTheme.jsx');
    globalThis.document={documentElement:root,querySelector:()=>null};
    const pending=new Promise(resolve=>{resolveLoad=resolve;});const loadCatalogue=()=>pending;
    function Probe({destination}) {const {theme}=useDestinationTheme(destination);return React.createElement('span',null,theme.code);}
    const element=destination=>React.createElement(DestinationThemeProvider,{loadCatalogue},React.createElement(Probe,{destination}));
    await act(async()=>{renderer=create(element('Kyoto, Japan'));});
    await act(async()=>renderer.update(element('Paris, France')));
    await act(async()=>resolveLoad(COUNTRY_THEMES));
    assert.equal(renderer.root.findByType('span').children.join(''),'FR');assert.equal(root.dataset.destinationTheme,'FR');
    assert.equal(style.get('--sea'),COUNTRY_THEMES.find(theme=>theme.code==='FR').primary);
    await act(async()=>renderer.update(element('Unknown place')));assert.equal(root.dataset.destinationTheme,'WORLD');
    await act(async()=>renderer.unmount());renderer=null;
    assert.equal(style.get('--sea'),'#123456');assert.equal(root.dataset.destinationTheme,undefined);
  }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.document=priorDocument;await server.close();}
});

test('idle background warmup is cancelled on unmount and rejection leaves the default usable',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
  const priorWindow=globalThis.window;let renderer,idle,cancelled=0,loads=0;
  try{
    const {DestinationThemeProvider,useTheme}=await server.ssrLoadModule('/src/themes/DestinationTheme.jsx');
    globalThis.window={requestIdleCallback:fn=>{idle=fn;return 42;},cancelIdleCallback:id=>{assert.equal(id,42);cancelled++;}};
    function Probe(){return React.createElement('span',null,useTheme().theme.code);}
    await act(async()=>{renderer=create(React.createElement(DestinationThemeProvider,{loadCatalogue:async()=>{loads++;throw Error('offline');}},React.createElement(Probe)));});
    assert.equal(loads,0);
    await act(async()=>idle());assert.equal(loads,1);assert.equal(renderer.root.findByType('span').children.join(''),'WORLD');
    await act(async()=>renderer.unmount());renderer=null;assert.equal(cancelled,1);
  }finally{if(renderer)await act(async()=>renderer.unmount());globalThis.window=priorWindow;await server.close();}
});
