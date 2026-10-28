const DAY_MS=86400000;
export class ContinuousDaysError extends Error {
  constructor(code){super(code);this.code=code;}
}
const stop=code=>{throw new ContinuousDaysError(code);};
const aborted=signal=>{if(signal?.aborted)throw new DOMException('Aborted','AbortError');};

/** Read validated API pages sequentially. This helper never submits planning work. */
export async function readContinuousDays({firstPage,readPage,identity,expectedDays,startDate,signal,onPage=()=>{},maxBytes=24*1024*1024,maxPages=1024}) {
  if(!Number.isSafeInteger(expectedDays)||expectedDays<0||typeof identity!=='function'||!/^\d{4}-\d{2}-\d{2}$/.test(startDate||'')||!Number.isFinite(Date.parse(startDate)))stop('DAYS_INVALID');
  const key=identity(firstPage),sections=[],ids=new Set(),encoder=new TextEncoder();
  let cursor=0,sequence=0,loadedDays=0,bytes=0,pageReads=0,page=firstPage;
  if(typeof key!=='string'||!key)stop('DAYS_INVALID');
  for(;;){
    aborted(signal);
    if(++pageReads>maxPages)stop('DAYS_DISPLAY_LIMIT');
    if(identity(page)!==key)stop('DAYS_CHANGED');
    if(!Array.isArray(page?.sections)||page.sections.length>3)stop('DAYS_INVALID');
    const added=[];
    for(const section of page.sections){
      if(!section||typeof section.id!=='string'||ids.has(section.id)||!Number.isSafeInteger(section.sequence)||section.sequence<=Math.max(cursor,sequence))stop('DAYS_INVALID');
      const days=section.checkpoint?.itinerary?.days;
      if(!Array.isArray(days)||!days.length||days.length>3||section.startDate!==days[0]?.date||section.endDate!==days.at(-1)?.date)stop('DAYS_INVALID');
      for(const day of days){
        const expected=new Date(Date.parse(startDate)+loadedDays*DAY_MS).toISOString().slice(0,10);
        if(day.date!==expected||loadedDays>=expectedDays)stop('DAYS_INVALID');
        loadedDays++;
      }
      bytes+=encoder.encode(JSON.stringify(section)).byteLength;
      if(bytes>maxBytes)stop('DAYS_DISPLAY_LIMIT');
      sequence=section.sequence;ids.add(section.id);added.push(section);
    }
    const next=page.nextCursor;
    if(next!==null&&(!Number.isSafeInteger(next)||next<=cursor||next<sequence))stop('DAYS_INVALID');
    sections.push(...added);
    const result={...firstPage,sections:[...sections],nextCursor:next,loadedDays,complete:next===null&&loadedDays===expectedDays,pageReads};
    onPage(result);
    if(next===null){if(loadedDays!==expectedDays)stop('DAYS_INCOMPLETE');return result;}
    if(pageReads>=maxPages)stop('DAYS_DISPLAY_LIMIT');
    aborted(signal);cursor=next;page=await readPage(cursor,{signal});
  }
}

export const continuousDaysMessage=error=>error?.code==='DAYS_DISPLAY_LIMIT'
  ? 'This trip is too large to show fully in this browser view. You can try downloading the itinerary PDF; no planned days were removed.'
  : error?.code==='DAYS_CHANGED'
    ? 'More days became ready while this view was loading. Your displayed days are kept; check the full view again.'
    : 'Some planned days could not be loaded yet. The days below are kept. Check the remaining days without generating a new trip.';
