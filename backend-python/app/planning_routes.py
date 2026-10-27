"""Offline job contract. Not a production queue or an implicit provider opt-in."""
import os
import inspect
from uuid import UUID
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from .models import TripPreferences
from .configuration import hosted_environment
from .auth import bearer, AuthError, auth_error
from .trip_routes import fail


class StartPlanningJob(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    requestId: UUID
    preferences: TripPreferences


def preview_enabled():
    return (os.getenv('PLANNING_JOBS_PREVIEW') == 'true'
        and os.getenv('APP_MODE', 'local').lower() == 'local'
        and not hosted_environment())


def build_planning_router(auth_service, engine=None):
    router = APIRouter(prefix='/api/planning-jobs', tags=['Planning jobs preview'])

    async def execute(request, operation):
        # An env flag alone cannot wire a paid generator. Production cannot use
        # this ephemeral prototype even if somebody accidentally sets the flag.
        from .planning_activation import route_enabled
        if not route_enabled(engine):
            return fail(404, 'NOT_FOUND', 'This planning option is not available.')
        try:
            # Never accept a client-supplied owner or local single-user identity.
            user = await auth_service.verify(bearer(request.scope))
            return await operation(str(user.id))
        except AuthError as error:
            return auth_error(error)
        except Exception as error:
            from .planning_jobs import PlanningJobError
            if isinstance(error, PlanningJobError):
                return fail(error.status, error.code, error.public_message)
            return fail(502, 'JOB_UNAVAILABLE', 'Your plan could not be checked. Try checking again shortly.')

    @router.post('')
    async def start(body: StartPlanningJob, request: Request):
        return await execute(request, lambda owner: engine.start(owner, str(body.requestId), body.preferences))

    @router.get('/requests/{request_id}/context')
    async def request_context(request_id: UUID, request: Request):
        async def read(owner):
            value = engine.request_context(owner, str(request_id))
            return await value if inspect.isawaitable(value) else value
        return await execute(request, read)

    @router.get('/{identity}/context')
    async def context(identity: UUID, request: Request):
        async def read(owner):
            value = engine.context(owner, str(identity))
            return await value if inspect.isawaitable(value) else value
        return await execute(request, read)

    @router.get('/requests/{request_id}')
    async def lookup(request_id: UUID, request: Request):
        async def read(owner):
            value = engine.find_request(owner, str(request_id))
            return await value if inspect.isawaitable(value) else value
        return await execute(request, read)

    @router.get('/{identity}')
    async def get(identity: UUID, request: Request):
        async def read(owner):
            value = engine.get(owner, str(identity))
            return await value if inspect.isawaitable(value) else value
        return await execute(request, read)

    @router.post('/{identity}/cancel')
    async def cancel(identity: UUID, request: Request):
        return await execute(request, lambda owner: engine.cancel(owner, str(identity)))

    return router
