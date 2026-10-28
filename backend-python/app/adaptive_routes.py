"""Authenticated adaptive routes; injection plus server readiness only."""
from uuid import UUID
import logging
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from .models import TripPreferences
from .auth import bearer, AuthError, auth_error, verified_request_user
from .trip_routes import fail
from .planning_repository import JobRepositoryError

class Start(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    requestId: UUID
    preferences: TripPreferences
class RequestIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    requestId: UUID
class RevisionStart(RequestIdentity):
    targetDate: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    instruction: str = Field(min_length=1,max_length=2000)
class Retry(RequestIdentity):
    sectionId: UUID


def build_adaptive_router(auth_service, engine=None):
    router = APIRouter(prefix='/api/adaptive-plans',tags=['Adaptive planning'])
    async def execute(request, operation):
        from .adaptive_activation import route_enabled
        if not route_enabled(engine): return fail(404,'NOT_FOUND','This planning option is not available.')
        try:
            user = await verified_request_user(auth_service, request.scope)
            return await operation(str(user.id))
        except AuthError as error: return auth_error(error)
        except JobRepositoryError as error:
            code = error.code if error.code in {'SECTION_NOT_FOUND','SECTION_NOT_FOUND_OR_CONFLICT','SECTION_RETRY_NOT_ALLOWED',
                'SECTION_MONEY_INVALID','SECTION_RESOURCE_LIMIT','SECTION_STORAGE_UNCONFIRMED','SECTIONS_SCHEMA_NOT_READY',
                'SECTION_ADMISSION_REJECTED','SECTION_OWNER_PLAN_EXISTS','SECTION_CAPACITY_LIMIT','SECTION_CURRENT_NOT_FOUND','SECTION_OWNER_RECOVERY_CONFLICT','SECTION_OWNER_RECOVERY_UNAVAILABLE','SECTION_REQUEST_CONFLICT','RESEARCH_RETRY_NOT_ALLOWED','RESEARCH_ALLOWANCE_REACHED','RESEARCH_PHASE_ALREADY_RESERVED','REVISION_DISABLED','REVISION_NOT_FOUND','REVISION_NOT_FOUND_OR_CONFLICT','REVISION_ALLOWANCE_REACHED','REVISION_INSUFFICIENT_RETENTION','REVISION_ADMISSION_REJECTED','REVISION_RESOURCE_LIMIT','REVISION_RETRY_NOT_ALLOWED','REVISION_ACCEPT_CONFLICT','REVISION_INVALID_REQUEST','REVISION_CONTINUE_CONFLICT','REVISION_BASE_EXPIRED','REVISION_BASE_CHANGED','REVISION_OWNER_BUSY','REVISION_REQUEST_CONFLICT','REVISION_STORAGE_LIMIT','REVISION_TARGET_INVALID','REVISION_INVALID_BASE','SECTION_EXPENSES_INVALID'} else 'SECTION_UNAVAILABLE'
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
        if 'application/pdf' in request.headers.get('accept',''):
            from .itinerary_pdf import pdf_response
            return await execute(request,lambda owner:pdf_response(engine,owner,str(plan_id)))
        return await execute(request,lambda owner:export_response(engine,owner,str(plan_id)))
    @router.post('/{plan_id}/continue')
    async def continue_run(plan_id:UUID,body:RequestIdentity,request:Request):
        return await execute(request,lambda owner:engine.continue_run(owner,str(plan_id),str(body.requestId)))
    @router.post('/{plan_id}/retry')
    async def retry(plan_id:UUID,body:Retry,request:Request):
        return await execute(request,lambda owner:engine.retry(owner,str(plan_id),str(body.sectionId),str(body.requestId)))
    @router.post('/{plan_id}/research/retry')
    async def retry_research(plan_id:UUID,body:RequestIdentity,request:Request):
        if not hasattr(engine,'retry_research'): return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.retry_research(owner,str(plan_id),str(body.requestId)))
    @router.get('/{plan_id}/expenses')
    async def expenses(plan_id:UUID,request:Request):
        from .adaptive_expenses import accepted_expenses
        return await execute(request,lambda owner:accepted_expenses(engine.repository,owner,str(plan_id)))
    @router.post('/{plan_id}/revisions')
    async def revision_start(plan_id:UUID,body:RevisionStart,request:Request):
        if not hasattr(engine,'start_revision'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.start_revision(owner,str(plan_id),body.model_dump(mode='json')))
    @router.get('/{plan_id}/revision-requests/{request_id}')
    async def revision_lookup(plan_id:UUID,request_id:UUID,request:Request):
        if not hasattr(engine,'revision_request_context'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.revision_request_context(owner,str(plan_id),str(request_id)))
    @router.post('/{plan_id}/revisions/continue')
    async def revision_continue(plan_id:UUID,body:RequestIdentity,request:Request):
        if not hasattr(engine,'continue_revisions'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.continue_revisions(owner,str(plan_id),str(body.requestId)))
    @router.get('/{plan_id}/revisions/current')
    async def revision_current(plan_id:UUID,request:Request):
        if not hasattr(engine,'current_revision_context'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.current_revision_context(owner,str(plan_id)))
    @router.get('/{plan_id}/revisions/{revision_id}')
    async def revision_get(plan_id:UUID,revision_id:UUID,request:Request):
        if not hasattr(engine,'revision_context'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.revision_context(owner,str(plan_id),str(revision_id)))
    @router.post('/{plan_id}/revisions/{revision_id}/accept')
    async def revision_accept(plan_id:UUID,revision_id:UUID,request:Request):
        if not hasattr(engine,'revision_action'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.revision_action(owner,str(plan_id),str(revision_id),'accept'))
    @router.post('/{plan_id}/revisions/{revision_id}/reject')
    async def revision_reject(plan_id:UUID,revision_id:UUID,request:Request):
        if not hasattr(engine,'revision_action'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.revision_action(owner,str(plan_id),str(revision_id),'reject'))
    @router.post('/{plan_id}/revisions/{revision_id}/retry')
    async def revision_retry(plan_id:UUID,revision_id:UUID,body:RequestIdentity,request:Request):
        if not hasattr(engine,'revision_action'):return fail(404,'NOT_FOUND','This planning option is not available.')
        return await execute(request,lambda owner:engine.revision_action(owner,str(plan_id),str(revision_id),'retry',str(body.requestId)))
    @router.post('/{plan_id}/cancel')
    async def cancel(plan_id:UUID,request:Request): return await execute(request,lambda owner:engine.cancel(owner,str(plan_id)))
    return router
