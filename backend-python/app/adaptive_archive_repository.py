"""Fixed user-JWT archive RPC; bounded pages, no service key or provider calls."""
import hashlib
import json
from uuid import UUID
from datetime import datetime
import httpx
from .auth import SupabaseAuthService
from .supabase_clients import DatabaseError

MAX_RESPONSE=2*1024*1024
ERRORS={
 'SAVED_ADAPTIVE_FORBIDDEN':403,'SAVED_ADAPTIVE_NOT_FOUND':404,
 'SAVED_ADAPTIVE_CONFLICT':409,'SAVED_ADAPTIVE_SOURCE_EXPIRED':410,
 'SAVED_ADAPTIVE_TOO_LARGE':413,'SAVED_ADAPTIVE_QUOTA_EXCEEDED':413,
 'SAVED_ADAPTIVE_INVALID_SNAPSHOT':409,'SAVED_ADAPTIVE_INVALID_OPERATION':400,
 'SAVED_ADAPTIVE_NOT_CONFIGURED':503,'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED':502,
}

def fail(code='SAVED_ADAPTIVE_STORAGE_UNCONFIRMED'):
    raise DatabaseError(ERRORS[code],code)

def canonical(value):
    try:return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
    except Exception:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')

def wire(value,limit):
    raw=canonical(value)
    if len(raw.encode())>limit:fail('SAVED_ADAPTIVE_TOO_LARGE')
    return {'canonical':raw,'hash':hashlib.sha256(raw.encode()).hexdigest()}

def identity(value):
    try:
        if type(value) is not str:raise ValueError()
        return str(UUID(value))
    except Exception:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')

def integer(value,minimum=0,maximum=2**53-1):
    if type(value) is not int or not minimum<=value<=maximum:fail()
    return value

class ArchiveClient:
    def __init__(self,url,key,token,owner_id,*,transport=None):
        self._url,self._key=SupabaseAuthService(configuration=lambda:(url,key)).settings()
        if type(token) is not str or not 1<=len(token)<=16384 or any(ord(c)<33 or ord(c)>126 for c in token):fail('SAVED_ADAPTIVE_FORBIDDEN')
        self.owner_id=identity(owner_id);self._token=token;self._transport=transport
        self.elevated=False

    async def call(self,operation,payload):
        if operation not in {'begin','lookup','append_sources','append_sections','finalize','get','list','delete','cleanup'}:fail('SAVED_ADAPTIVE_INVALID_OPERATION')
        if len(canonical(payload).encode())>1024*1024:fail('SAVED_ADAPTIVE_TOO_LARGE')
        headers={'apikey':self._key,'Authorization':'Bearer '+self._token,'Accept':'application/json'}
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False,transport=self._transport) as client:
                async with client.stream('POST',self._url+'/rest/v1/rpc/adaptive_saved_archive',headers=headers,json={'operation':operation,'payload':payload}) as response:
                    body=bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body)>MAX_RESPONSE:fail()
                    if response.status_code in {401,403}:fail('SAVED_ADAPTIVE_FORBIDDEN')
                    if response.status_code!=200:
                        try:
                            error=json.loads(body);code=error.get('message')
                            if error.get('code')=='PGRST202':fail('SAVED_ADAPTIVE_NOT_CONFIGURED')
                        except DatabaseError:raise
                        except Exception:code=None
                        if code in ERRORS:fail(code)
                        fail()
            return json.loads(body)
        except DatabaseError:raise
        except Exception:fail()

class ArchiveRepository:
    def __init__(self,client):
        if getattr(client,'elevated',True) is not False:fail('SAVED_ADAPTIVE_FORBIDDEN')
        self.client=client;self.owner_id=identity(client.owner_id)

    def _status(self,row):
        if type(row) is not dict or row.get('owner')!=self.owner_id:fail()
        identity(row.get('id'));identity(row.get('requestId'))
        if row.get('status') not in {'staging','complete','expired'} or integer(row.get('version'),1)!=1:fail()
        if type(row.get('title')) is not str or not 1<=len(row['title'])<=120:fail()
        for key in ('createdAt','updatedAt','stagingExpiresAt'):
            try:
                if datetime.fromisoformat(row[key].replace('Z','+00:00')).tzinfo is None:raise ValueError()
            except Exception:fail()
        manifest=row.get('manifest')
        if type(manifest) is not dict or manifest.get('format')!='adaptive-sections-v1':fail()
        if wire({k:v for k,v in manifest.items() if k!='sourceDigest'},32768)['hash']!=manifest.get('sourceDigest'):fail()
        identity(manifest.get('sourcePlanId'));integer(manifest.get('sourceVersion'),1)
        total=integer(manifest.get('sectionCount'),1,1024)
        integer(row.get('savedSections'),0,total);integer(row.get('lastSourceSequence'))
        integer(row.get('coveredDays'),0,integer(manifest.get('totalDays'),1))
        integer(row.get('spentCents'),0,integer(manifest.get('spentCents')))
        if type(row.get('endLocation')) is not str or not row['endLocation']:fail()
        if row['status']=='complete' and (row['savedSections']!=total or row['coveredDays']!=manifest['totalDays'] or row['spentCents']!=manifest['spentCents']):fail()
        return row

    async def _call(self,operation,payload):
        try:return await self.client.call(operation,payload)
        except DatabaseError:raise
        except Exception:fail()

    async def begin(self,request_id,title,manifest):
        request_id=identity(request_id)
        if type(title) is not str or not title.strip() or len(title)>120 or any(ord(c)<32 or ord(c)==127 for c in title):fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
        row=self._status(await self._call('begin',{'requestId':request_id,'title':title.strip(),'sourceCanonical':canonical({k:v for k,v in manifest.items() if k!='sourceDigest'}),**wire(manifest,32768)}))
        if row['requestId']!=request_id or row['manifest']!=manifest or row['title']!=title.strip():fail()
        return row

    async def lookup(self,request_id):
        request_id=identity(request_id);row=await self._call('lookup',{'requestId':request_id})
        if row is None:return None
        row=self._status(row)
        if row['requestId']!=request_id:fail()
        return row

    async def _write(self,operation,saved_id,**payload):
        saved_id=identity(saved_id);row=self._status(await self._call(operation,{'id':saved_id,**payload}))
        if row['id']!=saved_id:fail()
        return row

    async def append_sources(self,saved_id,sources):
        if type(sources) is not list or not 1<=len(sources)<=3:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
        items=[]
        for source in sources:
            if type(source) is not dict or set(source)!={'hash','data'}:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
            try:
                from .adaptive_archive_sources import validate_archive_sources
                validate_archive_sources(source['data'])
            except Exception:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
            item=wire(source['data'],131072)
            if item['hash']!=source['hash']:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
            items.append(item)
        return await self._write('append_sources',saved_id,items=items)

    async def append_sections(self,saved_id,chunks):
        if type(chunks) is not list or not 1<=len(chunks)<=3:fail('SAVED_ADAPTIVE_INVALID_SNAPSHOT')
        return await self._write('append_sections',saved_id,items=[wire(c,262144) for c in chunks])

    async def finalize(self,saved_id):return await self._write('finalize',saved_id)

    async def get(self,saved_id,after_sequence=0):
        saved_id=identity(saved_id);integer(after_sequence,0,1024)
        row=self._status(await self._call('get',{'id':saved_id,'afterSequence':after_sequence}))
        if row['id']!=saved_id or row['status']!='complete' or row.get('persisted') is not True or row.get('format')!='adaptive-sections-v1':fail()
        sections=row.get('sections');sources=row.get('sources')
        if type(sections) is not list or len(sections)>3 or type(sources) is not list or len(sources)>3:fail()
        previous=after_sequence;needed=set()
        for section in sections:
            if type(section) is not dict or 'hash' not in section:fail()
            cp={k:v for k,v in section.items() if k!='hash'}
            if wire(cp,262144)['hash']!=section['hash'] or integer(cp.get('sequence'),1)!=previous+1:fail()
            try:
                from .section_repository import validate_checkpoint
                checkpoint=cp['checkpoint'];manifest=row['manifest']
                validate_checkpoint(checkpoint,{'start_date':cp['startDate'],'end_date':cp['endDate'],
                    'input_boundary':{'location':manifest['preferences']['departureCity'] if cp['sequence']==1 else checkpoint['startLocation']},
                    'final_section':cp['sequence']==manifest['sectionCount'],'departure_city':manifest['preferences']['departureCity'],
                    'budget_limit_cents':manifest['totalBudgetCents']})
                if checkpoint['journeyStrategy']!=manifest['journeyStrategy'] or checkpoint['itinerary']['currency']!=manifest['currency']:fail()
            except Exception:fail()
            previous=cp['sequence']
            hashes=cp.get('sourceHashes')
            if type(hashes) is not list or len(hashes)>1:fail()
            needed.update(hashes)
        found=set()
        for source in sources:
            if type(source) is not dict or set(source)!={'hash','data'} or wire(source['data'],131072)['hash']!=source['hash']:fail()
            if source['hash'] in found:fail()
            try:
                from .adaptive_archive_sources import validate_archive_sources
                validate_archive_sources(source['data'])
            except Exception:fail()
            found.add(source['hash'])
        if found!=needed:fail()
        expected=previous if previous<row['manifest']['sectionCount'] else None
        if row.get('nextCursor')!=expected or (not sections and expected is not None):fail()
        return row

    async def list(self,offset=0):
        integer(offset,0,10000);result=await self._call('list',{'offset':offset})
        if type(result) is not dict or result.get('offset')!=offset or type(result.get('hasMore')) is not bool or type(result.get('items')) is not list or len(result['items'])>20:fail()
        for item in result['items']:
            if self._status(item)['status']!='complete':fail()
        return result

    async def delete(self,saved_id,version):
        saved_id=identity(saved_id);integer(version,1,1)
        result=await self._call('delete',{'id':saved_id,'version':version})
        if result!={'id':saved_id,'owner':self.owner_id,'version':version,'deleted':True}:fail()
        return result

    async def cleanup(self):
        result=await self._call('cleanup',{})
        if type(result) is not dict or set(result)!={'removed'}:fail()
        integer(result['removed'],0,100);return result
