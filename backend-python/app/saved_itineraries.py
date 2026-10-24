"""Activity 5.1: authenticated full-snapshot CRUD, distinct from legacy preferences."""
import os
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from .auth import bearer, AuthError, auth_error
from .models import TripPreferences
from .itineraries import ItineraryPayload, validate_itinerary
from .supabase_clients import get_client, DatabaseError
from .trip_routes import fail


class Document(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    title: str=Field(min_length=1,max_length=120,strict=True)
    preferences: TripPreferences
    itinerary: ItineraryPayload

    @field_validator('title')
    @classmethod
    def title_text(cls,value):
        if not value.strip() or any(ord(c)<32 or ord(c)==127 for c in value): raise ValueError('Invalid title')
        return value.strip()

    @model_validator(mode='after')
    def consistent(self):
        try:
            if self.itinerary.status!='planned': raise ValueError()
            validate_itinerary(self.itinerary.model_dump(),self.preferences,'Saved snapshot','stored')
        except Exception: raise ValueError('Invalid complete itinerary snapshot') from None
        return self


class CreateDocument(Document):
    id: UUID  # Client operation identity lets ambiguous saves be checked without blind retries.


class UpdateDocument(Document):
    version: int=Field(ge=1,lt=2147483647,strict=True)


class DeleteDocument(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    version: int=Field(ge=1,le=2147483647,strict=True)


SUMMARY='id,user_id,title,version,created_at,updated_at'
FULL=SUMMARY+',preferences,itinerary'


def metadata(row,owner):
    try:
        if type(row) is not dict or row.get('user_id')!=owner: raise ValueError()
        identity=str(UUID(row['id']))
        if type(row['version']) is not int or row['version']<1: raise ValueError()
        title=Document.title_text(row['title'])
        if len(title)>120: raise ValueError()
        for k in ('created_at','updated_at'):
            if not isinstance(row[k],str) or datetime.fromisoformat(row[k].replace('Z','+00:00')).tzinfo is None: raise ValueError()
        return {'id':identity,'title':title,'version':row['version'],'createdAt':row['created_at'],'updatedAt':row['updated_at']}
    except Exception: raise DatabaseError() from None


def full_document(row,owner):
    meta=metadata(row,owner)
    try:
        doc=Document.model_validate({k:row[k] for k in ('title','preferences','itinerary')})
        # Preserve the generation contract saved:false; persistence lives in this envelope.
        plan=validate_itinerary(doc.itinerary.model_dump(),doc.preferences,'Saved snapshot','stored')
        return {**meta,'preferences':doc.preferences.model_dump(),'itinerary':plan.model_dump(mode='json'),'persisted':True}
    except Exception: raise DatabaseError() from None


class SavedItineraryStore:
    def __init__(self,client):
        if client.elevated or not client.owner_id: raise DatabaseError(403,'PERSISTENCE_FORBIDDEN')
        self.client=client

    def query(self,identity=None,version=None,full=True):
        q={'select':FULL if full else SUMMARY,'user_id':'eq.'+self.client.owner_id}
        if identity is not None:q['id']='eq.'+str(identity)
        if version is not None:q['version']='eq.'+str(version)
        return q

    async def list(self,offset):
        rows=await self.client.request('GET','saved_itineraries',params={**self.query(full=False),'order':'updated_at.desc,id.desc','limit':'21','offset':str(offset)})
        if len(rows)>21:raise DatabaseError()
        items=[metadata(row,self.client.owner_id) for row in rows]
        return {'items':items[:20],'hasMore':len(items)>20,'offset':offset}

    async def get(self,identity):
        rows=await self.client.request('GET','saved_itineraries',params={**self.query(identity),'limit':'1'})
        if not rows:raise DatabaseError(404,'SAVED_TRIP_NOT_FOUND')
        if len(rows)!=1 or rows[0].get('id')!=str(identity):raise DatabaseError()
        return full_document(rows[0],self.client.owner_id)

    async def write(self,doc,identity,version=None):
        body={k:getattr(doc,k) for k in ('title',)}
        body.update(preferences=doc.preferences.model_dump(),itinerary=doc.itinerary.model_dump(),version=1 if version is None else version+1)
        if version is None:body.update(id=str(identity),user_id=self.client.owner_id)
        rows=await self.client.request('POST' if version is None else 'PATCH','saved_itineraries',params=self.query(identity if version else None,version),payload=body)
        if not rows and version is not None:raise DatabaseError(409,'VERSION_CONFLICT')
        if len(rows)!=1 or rows[0].get('id')!=str(identity) or rows[0].get('version')!=body['version']:raise DatabaseError()
        result=full_document(rows[0],self.client.owner_id)
        if any(rows[0].get(k)!=body[k] for k in ('title','preferences','itinerary')):raise DatabaseError()
        return result

    async def delete(self,identity,version):
        rows=await self.client.request('DELETE','saved_itineraries',params=self.query(identity,version,full=False))
        if not rows:raise DatabaseError(409,'VERSION_CONFLICT')
        if len(rows)!=1:raise DatabaseError()
        meta=metadata(rows[0],self.client.owner_id)
        if meta['id']!=str(identity) or meta['version']!=version:raise DatabaseError()
        return {'deleted':True,'id':str(identity),'version':version}


def build_saved_itinerary_router(auth_service,client_factory=None):
    router=APIRouter(prefix='/api/saved-itineraries',tags=['Authenticated saved full itineraries'])
    async def store(request):
        token=bearer(request.scope)
        # No service-role fallback, including in trusted-operator local mode.
        if client_factory is not None:client=await client_factory(token,auth_service=auth_service)
        else:
            client=await get_client(token,auth_service=auth_service)
            if os.getenv('SAVED_ITINERARIES_SCHEMA_VERIFIED','').lower()!='true':raise DatabaseError(503,'PERSISTENCE_NOT_CONFIGURED')
        return SavedItineraryStore(client)
    async def execute(request,operation):
        try:return await operation(await store(request))
        except AuthError as error:return auth_error(error)
        except DatabaseError as error:
            messages={409:'This record changed or is no longer available. Reload it before updating or deleting.',404:'Saved itinerary not found.',403:'Saved itinerary access denied.',503:'Authenticated itinerary storage requires approved setup.'}
            return fail(error.status,error.code,messages.get(error.status,'The storage outcome could not be confirmed. Check saved history before retrying; your local plan is retained.'))
        except Exception:return fail(502,'PERSISTENCE_UNCONFIRMED','The storage outcome could not be confirmed. Check saved history before retrying.')
    @router.get('')
    async def listing(request:Request,offset:int=Query(default=0,ge=0,le=10000)):
        return await execute(request,lambda s:s.list(offset))
    @router.get('/{identity}')
    async def detail(identity:UUID,request:Request):return await execute(request,lambda s:s.get(identity))
    @router.post('')
    async def create(doc:CreateDocument,request:Request):return await execute(request,lambda s:s.write(doc,doc.id))
    @router.put('/{identity}')
    async def update(identity:UUID,doc:UpdateDocument,request:Request):return await execute(request,lambda s:s.write(doc,identity,doc.version))
    @router.delete('/{identity}')
    async def delete(identity:UUID,doc:DeleteDocument,request:Request):return await execute(request,lambda s:s.delete(identity,doc.version))
    return router
