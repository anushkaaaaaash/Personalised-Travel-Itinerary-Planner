import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import {syntheticPdf,assertPdfDownload} from '../tools/pdfVisualFixture.mjs';
import {createAdaptiveFixture} from '../tools/adaptiveVisualFixtures.mjs';
const id='11111111-1111-4111-8111-111111111111';
test('synthetic PDF has correct xref offsets and download check rejects changed bytes',async()=>{
 const label='Partial snapshot: 9 of 46 days',data=syntheticPdf(label),text=data.toString();
 const offset=Number(text.match(/startxref\n(\d+)/)[1]);assert.equal(text.slice(offset,offset+4),'xref');
 const rows=text.slice(offset).split('\n').slice(3,8);rows.forEach((row,i)=>assert.equal(text.slice(Number(row.slice(0,10))).startsWith(`${i+1} 0 obj`),true));
 const download={suggestedFilename:()=>`personalised-travel-itinerary-${id}.pdf`,failure:async()=>null,createReadStream:async()=>Readable.from([data])};
 await assertPdfDownload(download,id,label);await assert.rejects(assertPdfDownload(download,id,'Changed fixture'));
});
test('adaptive fixture returns PDF MIME type and actual PDF bytes for both plan states',async()=>{
 for(const phase of ['allowance','completed']){const fixture=createAdaptiveFixture();fixture.phase=phase;fixture.preferences={destination:'Paris',departureCity:'London',startDate:'2028-01-01',endDate:'2028-01-09',budget:5000,currency:'EUR',travelers:2,travelPace:'balanced',travelStyle:''};let response;await fixture.handle({request:()=>({method:()=> 'GET',headers:()=>({accept:'application/pdf'})}),fulfill:async value=>response=value},new URL(`http://localhost/api/adaptive-plans/${id}/export`));assert.equal(response.contentType,'application/pdf');assert.deepEqual(response.body,syntheticPdf(`${phase==='completed'?'Full':'Partial'} snapshot: 9 of 9 days`));}
});
