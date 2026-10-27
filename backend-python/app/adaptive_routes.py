"""Authenticated adaptive routes; injection plus server readiness only."""
from uuid import UUID
import logging
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, ConfigDict
from .models import TripPreferences
from .auth import bearer, AuthError, auth_error
from .trip_routes import fail
from .planning_repository import JobRepositoryError

class Start(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    requestId: UUID
    preferences: TripPreferences
class RequestIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    requestId: UUID
class Retry(RequestIdentity):
    sectionId: UUID


def build_adaptive_router(auth_service, engine=None):
    router = APIRouter(prefix='/api/adaptive-plans',tags=['Adaptive planning'])
    async def execute(request, operation):
        from .adaptive_activation import route_enabled
        if not route_enabled(engine): return fail(404,'NOT_FOUND','This planning option is not available.')
        try:
            user = await auth_service.verify(bearer(request.scope))
            return await operation(str(user.id))
        except AuthError as error: return auth_error(error)
        except JobRepositoryError as error:
            code = error.code if error.code in {'SECTION_NOT_FOUND','SECTION_NOT_FOUND_OR_CONFLICT','SECTION_RETRY_NOT_ALLOWED',
                'SECTION_MONEY_INVALID','SECTION_RESOURCE_LIMIT','SECTION_STORAGE_UNCONFIRMED','SECTIONS_SCHEMA_NOT_READY',
                'SECTION_ADMISSION_REJECTED','SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT','SECTION_CURRENT_NOT_FOUND','SECTION_OWNER_RECOVERY_CONFLICT','SECTION_OWNER_RECOVERY_UNAVAILABLE','SECTION_REQUEST_CONFLICT'} else 'SECTION_UNAVAILABLE'
            if code in {'SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT','SECTION_ADMISSION_REJECTED'}:
                try: logging.getLogger('uvicorn.error').info('Adaptive admission rejected: %s',code)
                except Exception: pass  # Diagnostics never change the API outcome.
            return fail(error.status,code,'Your planning session could not be checked. Check this session before starting another.')
        except Exception:
            return fail(503,'SECTION_UNAVAILABLE','Your planning session could not be checked. Check this session before starting another.')
    @router.post('')
    async def start(body:Start,request:Request): return await execute(request,lambda owner:engine.start(owner,str(body.requestId),body.preferences))
    @router.get('/current')
    async def current(request:Request): return await execute(request,lambda owner:engine.current_context(owner))
    @router.get('/requests/{request_id}')
    async def lookup(request_id:UUID,request:Request): return await execute(request,lambda owner:engine.request_context(owner,str(request_id)))
    @router.get('/{plan_id}')
    async def get(plan_id:UUID,request:Request,afterSequence:int=Query(0,ge=0,le=2147483647)):
        return await execute(request,lambda owner:engine.context(owner,str(plan_id),afterSequence))
    @router.get('/{plan_id}/export')
    async def export(plan_id:UUID,request:Request):
        from .adaptive_export import export_response
        return await execute(request,lambda owner:export_response(engine,owner,str(plan_id)))
    @router.post('/{plan_id}/continue')
    async def continue_run(plan_id:UUID,body:RequestIdentity,request:Request):
        return await execute(request,lambda owner:engine.continue_run(owner,str(plan_id),str(body.requestId)))
    @router.post('/{plan_id}/retry')
    async def retry(plan_id:UUID,body:Retry,request:Request):
        return await execute(request,lambda owner:engine.retry(owner,str(plan_id),str(body.sectionId),str(body.requestId)))
    @router.post('/{plan_id}/cancel')
    async def cancel(plan_id:UUID,request:Request): return await execute(request,lambda owner:engine.cancel(owner,str(plan_id)))
    return router
