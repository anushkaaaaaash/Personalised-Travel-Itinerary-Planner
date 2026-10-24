import asyncio, copy, json
import httpx, pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.auth import SupabaseAuthService
from app.supabase_clients import get_client, get_service_client, DatabaseError
from app.saved_itineraries import SavedItineraryStore
from test_itineraries import generated, NoStorage
A='12345678-1234-1234-1234-123456789abc'
B='22345678-1234-1234-1234-123456789abc'
ID='32345678-1234-1234-1234-123456789abc'

@pytest.fixture
def document(payload,generated):return {'id':ID,'title':'Synthetic saved test','preferences':payload,'itinerary':generated}

def setup(failure=None,wrong_owner=False):
    calls=[]; rows={}; auth_calls=[]
    def auth_handler(request):
        auth_calls.append(request)
        token=request.headers.get('authorization')
        if token not in {'Bearer user-a','Bearer user-b'}:return httpx.Response(401,json={'message':'PRIVATE_AUTH'})
        return httpx.Response(200,json={'id':A if token.endswith('user-a') else B,'email_confirmed_at':'2026-01-01T00:00:00Z'})
    auth=SupabaseAuthService(configuration=lambda:('https://test.supabase.co','sb_publishable_test'),transport=httpx.MockTransport(auth_handler))
    def handler(request):
        calls.append(request)
        assert request.headers['apikey']=='sb_publishable_test'
        owner=A if request.headers['authorization']=='Bearer user-a' else B
        assert request.url.params['user_id']=='eq.'+owner
        if failure:return httpx.Response(failure,json={'message':'PRIVATE_DATABASE_DETAIL'})
        identity=request.url.params.get('id','eq.')[3:]
        visible=[copy.deepcopy(r) for r in rows.values() if r['user_id']==owner and (not identity or r['id']==identity)]
        v=request.url.params.get('version')
        if v:visible=[r for r in visible if r['version']==int(v[3:])]
        if request.method=='POST':
            row=json.loads(request.content); assert row['user_id']==owner
            if row['id'] in rows:return httpx.Response(409,json={})
            row.update(created_at='2026-01-01T00:00:00Z',updated_at='2026-01-01T00:00:00Z')
            rows[row['id']]=copy.deepcopy(row); visible=[row]
        elif request.method=='PATCH':
            for row in visible:
                row.update(json.loads(request.content)); rows[row['id']]=copy.deepcopy(row)
        elif request.method=='DELETE':
            for row in visible:del rows[row['id']]
        if wrong_owner:
            for row in visible:row['user_id']=B if owner==A else A
        return httpx.Response(201 if request.method=='POST' else 200,json=visible)
    async def factory(token,auth_service):return await get_client(token,auth_service=auth_service,transport=httpx.MockTransport(handler))
    client=TestClient(create_app(store=NoStorage(),auth_service=auth,saved_client_factory=factory))
    return client,calls,rows,auth_calls

def headers(user='a'):return {'Authorization':'Bearer user-'+user}

def test_full_crud_version_conflicts_and_owner_isolation(document):
    client,calls,rows,auth_calls=setup()
    response=client.post('/api/saved-itineraries',json=document,headers=headers())
    assert response.status_code==200,response.text
    data=response.json(); assert data['persisted'] is True and data['itinerary']['saved'] is False
    assert 'user_id' not in response.text and 'user-a' not in response.text
    assert client.get('/api/saved-itineraries',headers=headers('b')).json()['items']==[]
    assert client.get('/api/saved-itineraries/'+ID,headers=headers('b')).status_code==404
    assert client.get('/api/saved-itineraries/'+ID,headers=headers()).json()['preferences']==data['preferences']
    listing=client.get('/api/saved-itineraries',headers=headers()).json()
    assert len(listing['items'])==1 and 'itinerary' not in listing['items'][0]
    assert 'preferences' not in calls[-1].url.params['select']
    update={k:v for k,v in document.items() if k!='id'}; update.update(version=1,title='Edited synthetic test')
    assert client.put('/api/saved-itineraries/'+ID,json=update,headers=headers('b')).status_code==409
    response=client.put('/api/saved-itineraries/'+ID,json=update,headers=headers())
    assert response.status_code==200,response.text
    assert response.json()['version']==2 and response.json()['title']==update['title']
    assert client.put('/api/saved-itineraries/'+ID,json=update,headers=headers()).status_code==409
    assert client.request('DELETE','/api/saved-itineraries/'+ID,json={'version':1},headers=headers()).status_code==409
    assert client.request('DELETE','/api/saved-itineraries/'+ID,json={'version':2},headers=headers('b')).status_code==409
    response=client.request('DELETE','/api/saved-itineraries/'+ID,json={'version':2},headers=headers())
    assert response.json()=={'deleted':True,'id':ID,'version':2}
    assert not rows
    assert all(r.headers.get('cache-control')=='no-store' for r in [response])

@pytest.mark.parametrize('token',[None,'bad-token'])
def test_unauthorized_no_database_calls(document,token):
    client,calls,_,_=setup()
    h={} if token is None else {'Authorization':'Bearer '+token}
    for method,path,payload in [('GET','',None),('POST','',document),('PUT','/'+ID,{k:v for k,v in document.items() if k!='id'}|{'version':1}),('DELETE','/'+ID,{'version':1})]:
        r=client.request(method,'/api/saved-itineraries'+path,json=payload,headers=h)
        assert r.status_code==401
        assert 'PRIVATE_AUTH' not in r.text
    assert calls==[]

@pytest.mark.parametrize('change',['owner','extra','mismatch','overlap','infeasible','title','version'])
def test_invalid_payloads_never_reach_database(document,change):
    client,calls,_,_=setup(); d=copy.deepcopy(document)
    if change=='owner':d['user_id']=B
    if change=='extra':d['access_token']='PRIVATE_TOKEN'
    if change=='mismatch':d['itinerary']['destination']='Other'
    if change=='overlap':d['itinerary']['days'][0]['activities'][1]['startTime']='09:00'
    if change=='infeasible':d['itinerary']['status']='infeasible';d['itinerary']['days']=[]
    if change=='title':d['title']=' '
    if change=='version':d['version']=99
    r=client.post('/api/saved-itineraries',json=d,headers=headers())
    assert r.status_code==400 and 'PRIVATE_TOKEN' not in r.text and not calls

@pytest.mark.parametrize('status',[400,401,403,409,429,500,503])
def test_provider_failure_redacted_single_call(document,status):
    client,calls,_,_=setup(failure=status)
    r=client.post('/api/saved-itineraries',json=document,headers=headers())
    assert r.status_code in {403,409,502} and len(calls)==1
    assert 'PRIVATE_DATABASE_DETAIL' not in r.text and 'sb_publishable_test' not in r.text

def test_returned_wrong_owner_rejected(document):
    client,_,_,_=setup(wrong_owner=True)
    assert client.post('/api/saved-itineraries',json=document,headers=headers()).status_code==502

@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE'])
def test_json_boundary_applies_to_writes(method):
    client,_,_,_=setup()
    r=client.request(method,'/api/saved-itineraries/'+ID,content='{}',headers=headers())
    assert r.status_code==415
    r=client.request(method,'/api/saved-itineraries/'+ID,content='x'*131073,headers={**headers(),'Content-Type':'application/json'})
    assert r.status_code==413

def test_admin_client_explicit_and_rejected_by_user_store():
    with pytest.raises(DatabaseError):get_service_client(configuration=lambda:('https://test.supabase.co','sb_secret_test'))
    admin=get_service_client(explicit_admin=True,configuration=lambda:('https://test.supabase.co','sb_secret_test'))
    with pytest.raises(DatabaseError):SavedItineraryStore(admin)
    with pytest.raises(DatabaseError):get_service_client(explicit_admin=True,configuration=lambda:('https://test.supabase.co','sb_publishable_test'))

def test_public_client_rejects_service_key_before_network():
    auth=SupabaseAuthService(configuration=lambda:('https://test.supabase.co','sb_secret_test'))
    with pytest.raises(Exception):asyncio.run(get_client('user-a',auth_service=auth))

def test_schema_setup_gate_no_secret_fallback(monkeypatch):
    client,_,_,_=setup()
    real=TestClient(create_app())
    r=real.get('/api/saved-itineraries',headers=headers())
    assert r.status_code==503
    assert 'key' not in r.text.lower()
