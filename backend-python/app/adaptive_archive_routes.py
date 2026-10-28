"""Account archive endpoints; disabled until the additive schema is approved."""
import os
from uuid import UUID
from fastapi import APIRouter,Request,Query
from pydantic import BaseModel,ConfigDict,Field
from .auth import verified_request_user,bearer,AuthError,auth_error
from .supabase_clients import DatabaseError
from .planning_repository import JobRepositoryError
from .trip_routes import fail
from .adaptive_archive_repository import ArchiveClient,ArchiveRepository
from .adaptive_archive_service import ArchiveService


def archive_enabled():
    return all(os.getenv(k)=='true' for k in ('ADAPTIVE_SAVED_TRIPS_ENABLED','ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED'))


class Save(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    requestId:UUID
    title:str=Field(min_length=1,max_length=120,strict=True)
    expectedVersion:int=Field(ge=1,le=2147483647,strict=True)

class Delete(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    version:int=Field(ge=1,le=2147483647,strict=True)


def build_archive_router(auth_service,engine=None,repository_factory=None,enabled=archive_enabled):
    router=APIRouter(tags=['Saved adaptive trips'])
    async def execute(request,operation):
        if not enabled():return fail(404,'SAVED_ADAPTIVE_NOT_CONFIGURED','Account saving is not available.')
        try:
            user=await verified_request_user(auth_service,request.scope);owner=str(user.id)
            if repository_factory is None:
                url,key=auth_service.settings()
                archive=ArchiveRepository(ArchiveClient(url,key,bearer(request.scope),owner))
            else:archive=repository_factory(owner,bearer(request.scope))
            if archive.owner_id!=owner:raise DatabaseError(403,'SAVED_ADAPTIVE_FORBIDDEN')
            service=ArchiveService(archive,getattr(engine,'repository',None),getattr(engine,'research_repository',None))
            return await operation(service)
        except AuthError as error:return auth_error(error)
        except DatabaseError as error:
            codes={'SAVED_ADAPTIVE_NOT_CONFIGURED','SAVED_ADAPTIVE_NOT_FOUND','SAVED_ADAPTIVE_REQUEST_NOT_FOUND','SAVED_ADAPTIVE_INVALID_REQUEST',
                'SAVED_ADAPTIVE_NOT_COMPLETE','SAVED_ADAPTIVE_VERSION_CONFLICT','SAVED_ADAPTIVE_REQUEST_CONFLICT',
                'SAVED_ADAPTIVE_CONFLICT','SAVED_ADAPTIVE_QUOTA_EXCEEDED','SAVED_ADAPTIVE_SOURCE_EXPIRED',
                'SAVED_ADAPTIVE_TOO_LARGE','SAVED_ADAPTIVE_FORBIDDEN','SAVED_ADAPTIVE_INVALID_SNAPSHOT',
                'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED','SAVED_ADAPTIVE_SOURCE_UNAVAILABLE','SAVED_ADAPTIVE_SOURCES_UNAVAILABLE'}
            code=error.code if error.code in codes else 'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED'
            return fail(error.status if code==error.code else 502,code,'Check this save before starting another. Your working trip is unchanged.')
        except JobRepositoryError as error:
            if error.code=='SECTION_NOT_FOUND_OR_CONFLICT':return fail(410,'SAVED_ADAPTIVE_SOURCE_EXPIRED','The temporary source is no longer available.')
            return fail(503,'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED','Check this save before starting another.')
        except Exception:return fail(503,'SAVED_ADAPTIVE_STORAGE_UNCONFIRMED','Check this save before starting another.')

    @router.post('/api/adaptive-plans/{plan_id}/save')
    async def save(plan_id:UUID,body:Save,request:Request):
        return await execute(request,lambda service:service.save(str(plan_id),str(body.requestId),body.expectedVersion,body.title))
    @router.get('/api/saved-adaptive-trips/requests/{request_id}')
    async def lookup(request_id:UUID,request:Request):return await execute(request,lambda service:service.lookup(str(request_id)))
    @router.get('/api/saved-adaptive-trips')
    async def listing(request:Request,offset:int=Query(0,ge=0,le=10000)):
        return await execute(request,lambda service:service.list(offset))
    @router.get('/api/saved-adaptive-trips/{saved_id}')
    async def get(saved_id:UUID,request:Request,afterSequence:int=Query(0,ge=0,le=1024)):
        return await execute(request,lambda service:service.get(str(saved_id),afterSequence))
    @router.get('/api/saved-adaptive-trips/{saved_id}/export')
    async def export_pdf(saved_id:UUID,request:Request):
        from .itinerary_pdf import archived_pdf_response
        return await execute(request,lambda service:archived_pdf_response(service,str(saved_id)))
    @router.delete('/api/saved-adaptive-trips/{saved_id}')
    async def delete(saved_id:UUID,body:Delete,request:Request):
        return await execute(request,lambda service:service.delete(str(saved_id),body.version))
    return router
