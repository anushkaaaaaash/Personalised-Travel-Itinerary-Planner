"""Local FastAPI replacement; leave the Express server stopped while using port 5000."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .models import TripPreferences, PromptResponse
from .prompts import build_itinerary_prompt
from .storage import SupabaseTripStore

from .recommendations import RecommendationService, RecommendationResponse, RecommendationError
from .ai_services import ConfiguredRecommendationService
from .trip_routes import build_trip_router
from .itineraries import build_itinerary_router
from .optimizer import build_optimizer_router
from .auth import SupabaseAuthService, build_auth_router, AccessBoundary
from .cors import configured_frontend_origins
from .privacy import NoStoreBoundary
from fastapi.middleware.cors import CORSMiddleware

LIMIT = 16 * 1024

def error_response(status, code, message, fields=None, reason=None):
    from .diagnostics import safe_reason
    error = {'code': code, 'message': message}
    if safe_reason(reason):
        error['reason'] = safe_reason(reason)
    if fields:
        error['fields'] = fields
    return JSONResponse(status_code=status, content={'error': error})

class JsonBoundary:
    """Bound streamed bodies too, before FastAPI parses JSON. No body logging."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST','PUT','PATCH','DELETE'}:
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        media = headers.get(b'content-type', b'').split(b';')[0].strip().lower()
        if media != b'application/json':
            return await error_response(415, 'UNSUPPORTED_MEDIA_TYPE', 'Send preferences as JSON.')(scope, receive, send)
        body_limit = 128 * 1024 if (scope.get('path') in {'/api/itineraries/refine','/api/itineraries/optimize'} or scope.get('path','').startswith('/api/saved-itineraries')) else LIMIT
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > body_limit:
                return await error_response(413, 'REQUEST_TOO_LARGE', 'Trip preferences are too large.')(scope, receive, send)
            if not message.get('more_body', False):
                break
        async def replay():
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
        await self.app(scope, replay, send)

def create_app(store=None, recommendation_service=None, itinerary_service=None, auth_service=None, saved_client_factory=None, planning_engine=None, adaptive_engine=None, archive_repository_factory=None):
    @asynccontextmanager
    async def lifespan(_app):
        from .planning_activation import route_enabled
        _app.state.planning_lifespan_active = True
        stop = asyncio.Event()
        runners = []
        if route_enabled(planning_engine) and callable(getattr(planning_engine, 'run', None)):
            if callable(getattr(planning_engine, 'verify_ready', None)):
                await planning_engine.verify_ready()
            runners.append(asyncio.create_task(planning_engine.run(stop)))
        from .adaptive_activation import route_enabled as adaptive_route_enabled
        if adaptive_route_enabled(adaptive_engine):
            await adaptive_engine.verify_ready()
            runners.append(asyncio.create_task(adaptive_engine.run(stop)))
        try:
            yield
        finally:
            _app.state.planning_lifespan_active = False
            stop.set()
            for runner in runners: runner.cancel()
            if runners: await asyncio.gather(*runners, return_exceptions=True)
            if planning_engine is not None and callable(getattr(planning_engine, 'close', None)):
                await planning_engine.close()
            if adaptive_engine is not None:
                await adaptive_engine.close()
    app = FastAPI(title='Travel planner API', version='0.4.0', lifespan=lifespan)
    app.state.planning_lifespan_active = False
    storage = store if store is not None else SupabaseTripStore()
    app.add_middleware(JsonBoundary)
    authentication = auth_service if auth_service is not None else SupabaseAuthService()
    app.add_middleware(AccessBoundary, auth_service=authentication, ownership_supported=callable(getattr(storage, 'for_user', None)))
    app.add_middleware(CORSMiddleware, allow_origins=configured_frontend_origins(),
        allow_credentials=False, allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],
        allow_headers=['Authorization','Content-Type'])
    app.add_middleware(NoStoreBoundary)
    def planning_capability():
        from .planning_activation import route_enabled
        from .planning_coordinator import DurablePlanningCoordinator
        return (app.state.planning_lifespan_active and isinstance(planning_engine, DurablePlanningCoordinator)
            and route_enabled(planning_engine) and planning_engine.capability_ready())
    def adaptive_capability():
        from .adaptive_activation import route_enabled
        return bool(app.state.planning_lifespan_active and route_enabled(adaptive_engine) and adaptive_engine.capability_ready())
    app.include_router(build_auth_router(authentication, planning_capability, adaptive_capability,
        lambda: adaptive_engine.public_policy() if hasattr(adaptive_engine,'public_policy') else {'sectionDays':3,'maxSubmissionsPerRun':adaptive_engine.run_allowance}))
    from .adaptive_archive_routes import build_archive_router
    app.include_router(build_archive_router(authentication, adaptive_engine, archive_repository_factory))
    from .adaptive_routes import build_adaptive_router
    app.include_router(build_adaptive_router(authentication, adaptive_engine))
    from .planning_routes import build_planning_router
    app.include_router(build_planning_router(authentication, planning_engine))
    from .saved_itineraries import build_saved_itinerary_router
    app.include_router(build_saved_itinerary_router(authentication,saved_client_factory))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        # Pydantic's default details include raw submitted values: never echo those.
        fields = {}
        auth_request = request.url.path.startswith('/api/auth/')
        for item in exc.errors():
            location = item.get('loc', ())
            field = str(location[1]) if len(location) > 1 and location[1] in (set(TripPreferences.model_fields) | ({'email','password'} if auth_request else set())) else 'form'
            fields[field] = 'Check this preference.'
        return error_response(400, 'VALIDATION_ERROR', ('Check the email and password fields.' if auth_request else 'Check the trip preferences and try again.'), fields)

    recommendations = recommendation_service if recommendation_service is not None else ConfiguredRecommendationService()
    router = APIRouter(prefix='/api', tags=['Recommendations'])

    @router.post('/recommendations', response_model=RecommendationResponse)
    async def recommend(preferences: TripPreferences):
        # No save or trip listing here. Provider access must be configured explicitly.
        try:
            return await recommendations.recommend(preferences)
        except RecommendationError as exc:
            return error_response(exc.status, exc.code, exc.public_message, reason=exc.reason)
        except Exception:
            return error_response(502, 'AI_PROVIDER_FAILED', 'Recommendations could not be confirmed.')

    app.include_router(router)

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'backend': 'fastapi'}

    app.include_router(build_trip_router(storage))
    app.include_router(build_itinerary_router(itinerary_service))
    app.include_router(build_optimizer_router())

    @app.post('/api/prompts/itinerary', response_model=PromptResponse)
    async def preview_prompt(preferences: TripPreferences):
        # Activity 3.2 only: no save, no AI call, no credentials or cost.
        return build_itinerary_prompt(preferences)

    from .frontend_static import attach_frontend
    attach_frontend(app)
    return app

app = create_app()
