from copy import deepcopy
from uuid import uuid4
import hashlib,json
import httpx
import pytest
from app.adaptive_archive_repository import ArchiveClient,ArchiveRepository,canonical,wire
from app.supabase_clients import DatabaseError
OWNER=str(uuid4());OTHER=str(uuid4());ID=str(uuid4());REQUEST=str(uuid4())

def row():
    manifest={'format':'adaptive-sections-v1','sourcePlanId':str(uuid4()),'sourceVersion':1,'sectionCount':1,'totalDays':2,'spentCents':100}
    manifest['sourceDigest']=wire(manifest,32768)['hash']
    return {'owner':OWNER,'id':ID,'requestId':REQUEST,'title':'Saved','status':'staging','version':1,'manifest':manifest,
        'createdAt':'2026-10-27T00:00:00Z','updatedAt':'2026-10-27T00:00:00Z','stagingExpiresAt':'2026-10-28T00:00:00Z',
        'savedSections':0,'coveredDays':0,'spentCents':0,'lastSourceSequence':0,'endLocation':'Home'}

class Client:
    elevated=False;owner_id=OWNER
    def __init__(self,value):self.value=value;self.calls=[]
    async def call(self,operation,payload):self.calls.append((operation,payload));return deepcopy(self.value)

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
async def test_begin_forwards_canonical_strings_and_binds_identity():
    value=row();client=Client(value);repo=ArchiveRepository(client)
    assert await repo.begin(REQUEST,'Saved',value['manifest'])==value
    op,payload=client.calls[0]
    assert op=='begin' and payload['requestId']==REQUEST
    assert payload['hash']==hashlib.sha256(payload['canonical'].encode()).hexdigest()
    assert json.loads(payload['canonical'])==value['manifest']
    assert 'sourceDigest' not in json.loads(payload['sourceCanonical'])

@pytest.mark.anyio
@pytest.mark.parametrize('field,value',[('owner',OTHER),('id','bad'),('requestId',str(uuid4())),('version',True),('savedSections',2),('createdAt','no'),('status','running'),('coveredDays',3)])
async def test_untrusted_status_never_accepted(field,value):
    result=row();result[field]=value
    with pytest.raises(DatabaseError):await ArchiveRepository(Client(result)).lookup(REQUEST)

@pytest.mark.anyio
async def test_absence_is_distinct_from_transport_unknown():
    assert await ArchiveRepository(Client(None)).lookup(REQUEST) is None
    client=Client(None)
    async def broken(*args):raise RuntimeError('private credential')
    client.call=broken
    with pytest.raises(DatabaseError,match='SAVED_ADAPTIVE_STORAGE_UNCONFIRMED'):await ArchiveRepository(client).lookup(REQUEST)

@pytest.mark.anyio
async def test_bounded_append_and_source_hash_no_request_on_invalid():
    client=Client(row());repo=ArchiveRepository(client)
    with pytest.raises(DatabaseError):await repo.append_sections(ID,[{}]*4)
    with pytest.raises(DatabaseError):await repo.append_sources(ID,[{'hash':'bad','data':{}}])
    assert client.calls==[]

@pytest.mark.anyio
async def test_http_fixed_rpc_same_jwt_and_no_retry():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.path=='/rest/v1/rpc/adaptive_saved_archive'
        assert request.headers['Authorization']=='Bearer synthetic-token'
        assert request.headers['apikey']=='sb_publishable_synthetic'
        return httpx.Response(200,json=row())
    client=ArchiveClient('https://synthetic.supabase.co','sb_publishable_synthetic','synthetic-token',OWNER,transport=httpx.MockTransport(handler))
    assert (await ArchiveRepository(client).lookup(REQUEST))['owner']==OWNER
    assert len(calls)==1

@pytest.mark.anyio
@pytest.mark.parametrize('status,body,code',[(500,{'message':'secret sql user password'},'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED'),(400,{'message':'SAVED_ADAPTIVE_QUOTA_EXCEEDED'},'SAVED_ADAPTIVE_QUOTA_EXCEEDED'),(403,{},'SAVED_ADAPTIVE_FORBIDDEN')])
async def test_http_errors_are_fixed_and_never_replayed(status,body,code):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,json=body)
    client=ArchiveClient('https://synthetic.supabase.co','sb_publishable_synthetic','synthetic-token',OWNER,transport=httpx.MockTransport(handler))
    with pytest.raises(DatabaseError,match=code):await client.call('lookup',{'requestId':REQUEST})
    assert len(calls)==1

@pytest.mark.anyio
async def test_response_limit_and_method_allowlist():
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,content=b'x'*(2*1024*1024+1))
    client=ArchiveClient('https://synthetic.supabase.co','sb_publishable_synthetic','synthetic-token',OWNER,transport=httpx.MockTransport(handler))
    with pytest.raises(DatabaseError):await client.call('arbitrary',{})
    assert not calls
    with pytest.raises(DatabaseError):await client.call('lookup',{'requestId':REQUEST})
    assert len(calls)==1

def test_elevated_client_rejected():
    client=Client(None);client.elevated=True
    with pytest.raises(DatabaseError):ArchiveRepository(client)

from test_itineraries import generated
from test_adaptive_planning import spec_for,section_wire
from app.adaptive_planning import SectionContract
from datetime import date,timedelta

@pytest.mark.anyio
async def test_read_valid_checkpoint_then_reject_even_rehashed_malformed_content(payload,generated):
    prefs={**payload,'endDate':(date.fromisoformat(payload['startDate'])+timedelta(days=1)).isoformat()}
    spec=spec_for(prefs);checkpoint=SectionContract(spec).decode(section_wire(prefs,generated,spec))
    chunk={'sequence':1,'sourceSequence':2,'startDate':spec.start.isoformat(),'endDate':spec.end.isoformat(),
        'checkpoint':checkpoint,'sourceHashes':[],'sourceAssociation':'none_recorded'}
    result=row();m=result['manifest'];m.update(preferences=prefs,journeyStrategy=checkpoint['journeyStrategy'],currency=prefs['currency'],totalBudgetCents=int(prefs['budget']*100),spentCents=checkpoint['spentCents'])
    m['sourceDigest']=wire({k:v for k,v in m.items() if k!='sourceDigest'},32768)['hash']
    result.update(status='complete',savedSections=1,lastSourceSequence=2,coveredDays=2,spentCents=checkpoint['spentCents'],endLocation=prefs['departureCity'],persisted=True,format='adaptive-sections-v1',sections=[{**chunk,'hash':wire(chunk,262144)['hash']}],sources=[],nextCursor=None)
    assert (await ArchiveRepository(Client(result)).get(ID))['sections'][0]['checkpoint']==checkpoint
    bad=deepcopy(chunk);del bad['checkpoint']['provenance']
    result['sections']=[{**bad,'hash':wire(bad,262144)['hash']}]
    with pytest.raises(DatabaseError):await ArchiveRepository(Client(result)).get(ID)

@pytest.mark.anyio
async def test_missing_schema_fixed_code():
    client=ArchiveClient('https://synthetic.supabase.co','sb_publishable_synthetic','synthetic-token',OWNER,
        transport=httpx.MockTransport(lambda _:httpx.Response(404,json={'code':'PGRST202','message':'private schema details'})))
    with pytest.raises(DatabaseError,match='SAVED_ADAPTIVE_NOT_CONFIGURED'):await client.call('lookup',{'requestId':REQUEST})
