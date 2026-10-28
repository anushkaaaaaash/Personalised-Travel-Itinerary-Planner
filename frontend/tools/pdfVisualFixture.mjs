import assert from 'node:assert/strict';
/** A real one-page PDF with correct xref offsets, exclusively synthetic offline QA. */
export function syntheticPdf(label) {
  assert.match(label,/^[\x20-\x7e]+$/);
  const content=`BT /F1 14 Tf 40 740 Td (${label.replace(/[\\()]/g,'\\$&')}) Tj ET\n`;
  const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}endstream`];
  let output='%PDF-1.4\n';const offsets=[0];
  for(const [i,object] of objects.entries()){offsets.push(Buffer.byteLength(output));output+=`${i+1} 0 obj\n${object}\nendobj\n`;}
  const xref=Buffer.byteLength(output);
  output+=`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset=>String(offset).padStart(10,'0')+' 00000 n \n').join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(output);
}
export async function assertPdfDownload(download,id,label) {
  assert.equal(download.suggestedFilename(),`personalised-travel-itinerary-${id}.pdf`);
  assert.equal(await download.failure(),null);
  const stream=await download.createReadStream(),chunks=[];
  for await(const chunk of stream)chunks.push(chunk);
  assert.deepEqual(Buffer.concat(chunks),syntheticPdf(label));
}
