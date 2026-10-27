const kinds = new Set(['opening_hours','closure','route','weather','transit','booking']);
export function safeEvidenceSource(value) {
  try { const url=new URL(value);return url.protocol==='https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}
/** Evidence is displayable only for the exact stop/date/destination. Freshness is checked again at render time. */
export function evidenceForActivity(evidence, { destinationId, date, activityId, timeZone, now=Date.now() }) {
  if(!Array.isArray(evidence))return [];
  return evidence.slice(0,20).flatMap(item=>{
    const scope=item?.scope;
    if(!scope || !destinationId || scope.destinationId!==destinationId || scope.localDate!==date || scope.subjectId!==activityId || !kinds.has(scope.kind) || typeof scope.timeZone!=='string' || (timeZone && scope.timeZone!==timeZone))return [];
    try { new Intl.DateTimeFormat('en',{timeZone:scope.timeZone}); } catch { return []; }
    const source=safeEvidenceSource(item.sourceURL), checked=Date.parse(item.checkedAt), expires=Date.parse(item.expiresAt);
    const current=source && Number.isFinite(checked) && Number.isFinite(expires) && checked<=now && expires>now && expires>checked;
    const dateMatches=(!item.validFrom || date>=item.validFrom) && (!item.validUntil || date<=item.validUntil);
    const verified=Boolean(item.status==='verified' && current && dateMatches);
    const status=verified?'Checked':item.status==='stale' || (item.status==='verified' && !current)?'Needs rechecking':'Not checked';
    const summary=verified && typeof item.summary==='string'?item.summary.slice(0,600):typeof item.fallback==='string'?item.fallback.slice(0,600):'Confirm details before you go.';
    return [{kind:scope.kind,status,summary,source,checkedAt:Number.isFinite(checked)?new Date(checked).toISOString():null,blocker:verified && item.severity==='blocker'}];
  });
}
