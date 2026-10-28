"""Explicit bounded save steps; account reads never depend on live checkpoints."""
from datetime import datetime,timezone
from .adaptive_archive_snapshot import prepare_archive,archive_chunks,_plan,invalid,integer
from .adaptive_archive_views import validate_manifest,save_status,summary,page,title


class ArchiveService:
    def __init__(self,archive,repository=None,research_repository=None,*,clock=lambda:datetime.now(timezone.utc)):
        self.archive=archive;self.repository=repository;self.research_repository=research_repository;self.clock=clock
        self.owner=archive.owner_id

    async def _current(self,manifest):
        if self.repository is None:invalid('SAVED_ADAPTIVE_SOURCE_UNAVAILABLE',503)
        plan=await self.repository.get_plan(self.owner,manifest['sourcePlanId'])
        prefs,route,days=_plan(plan,self.owner,manifest['sourcePlanId'],manifest['sourceVersion'],self.clock())
        if (prefs.model_dump(mode='json')!=manifest['preferences'] or route!=manifest['journeyStrategy']
            or days!=manifest['totalDays'] or plan['expires_at']!=manifest['sourceExpiresAt']
            or plan['spent_cents']!=manifest['spentCents'] or plan['total_budget_cents']!=manifest['totalBudgetCents']):
            invalid('SAVED_ADAPTIVE_VERSION_CONFLICT')
        return plan

    async def save(self,plan_id,request_id,expected_version,requested_title):
        requested_title=title(requested_title);integer(expected_version,1)
        row=await self.archive.lookup(request_id)
        if row is None:
            if self.repository is None:invalid('SAVED_ADAPTIVE_SOURCE_UNAVAILABLE',503)
            await self.archive.cleanup()  # Bounded owner-expired staging only; never completed saves.
            snapshot=await prepare_archive(self.repository,self.research_repository,self.owner,plan_id,expected_version,now=self.clock())
            row=await self.archive.begin(request_id,requested_title,snapshot.manifest)
        manifest=validate_manifest(row['manifest'])
        if (manifest['sourcePlanId']!=plan_id or manifest['sourceVersion']!=expected_version or row['title']!=requested_title):
            invalid('SAVED_ADAPTIVE_REQUEST_CONFLICT')
        if row['status']=='complete':return save_status(row)
        if row['status']=='expired':invalid('SAVED_ADAPTIVE_SOURCE_EXPIRED',410)
        plan=await self._current(manifest)
        count=integer(row['savedSections']);chunks=[];sources={}
        if count<manifest['sectionCount']:
            stream=archive_chunks(self.repository,self.research_repository,self.owner,plan,now=self.clock(),
                after_sequence=row['lastSourceSequence'],section_offset=count,covered_days=row['coveredDays'],
                spent_cents=row['spentCents'],last_location=row['endLocation'])
            try:
                async for chunk,notes in stream:
                    chunks.append(chunk)
                    for source in notes:sources[source['hash']]=source
                    if len(chunks)==3:break
            finally:await stream.aclose()
            if not chunks:invalid()
            if sources:await self.archive.append_sources(row['id'],list(sources.values()))
            row=await self.archive.append_sections(row['id'],chunks)
            if row['manifest']!=manifest or row['savedSections']!=count+len(chunks):invalid()
        if row['savedSections']==manifest['sectionCount']:
            await self._current(manifest)
            row=await self.archive.finalize(row['id'])
        return save_status(row)

    async def lookup(self,request_id):
        row=await self.archive.lookup(request_id)
        if row is None:invalid('SAVED_ADAPTIVE_REQUEST_NOT_FOUND',404)
        return save_status(row)

    async def get(self,saved_id,after_sequence=0):
        return page(await self.archive.get(saved_id,after_sequence),saved_id,after_sequence,now=self.clock())

    async def list(self,offset=0):
        result=await self.archive.list(offset)
        if type(result) is not dict or type(result.get('items')) is not list or len(result['items'])>20 or type(result.get('hasMore')) is not bool or result.get('offset')!=offset:invalid()
        return {'items':[summary(row) for row in result['items']],'hasMore':result['hasMore'],'offset':offset}

    async def delete(self,saved_id,version):
        row=await self.archive.get(saved_id,0)
        if row['version']!=version:invalid('SAVED_ADAPTIVE_VERSION_CONFLICT')
        result=await self.archive.delete(saved_id,version)
        if result!={'id':saved_id,'owner':self.owner,'deleted':True,'version':version}:invalid()
        return {'id':saved_id,'deleted':True,'version':version}
