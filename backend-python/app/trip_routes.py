"""Private, loopback-only saved-trip routes. No user ownership is implied."""
import json
from datetime import date, datetime
from typing import Literal
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .models import TripPreferences, TripResponse
from .storage import StorageNotConfigured, confirmed_id
from .history import HistoryService
from .diagnostics import safe_reason


def fail(status, code, message, reason=None):
    error = {'code': code, 'message': message}
    if safe_reason(reason):
        error['reason'] = safe_reason(reason)
    return JSONResponse(status_code=status, content={'error': error})

class TripRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: int | str
    destination: str = Field(max_length=200)
    startDate: str
    endDate: str
    budget: float = Field(gt=0, allow_inf_nan=False)
    travelers: int = Field(ge=1, le=20)
    createdAt: str | None
    preferences: TripPreferences | None
    preferencesStatus: Literal['available', 'unavailable']

class TripDetailResponse(BaseModel):
    trip: TripRecord

class TripListResponse(BaseModel):
    trips: list[TripRecord]
    limit: int
    offset: int
    hasMore: bool
    scope: Literal['local-project-saved-trips', 'authenticated-user-saved-trips'] = 'local-project-saved-trips'


def decode_row(row):
    """Never expose arbitrary database fields or guess missing legacy preferences."""
    if not isinstance(row, dict):
        raise ValueError('Invalid stored row')
    identity = confirmed_id(row.get('id'))
    for key in ('start_date', 'end_date'):
        date.fromisoformat(row[key])
    created = row.get('created_at')
    if created is not None:
        datetime.fromisoformat(created.replace('Z', '+00:00'))
    preferences = None
    try:
        raw = row['preferences']
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 16384:
            raise ValueError()
        details = json.loads(raw)
        if not isinstance(details, dict):
            raise ValueError()
        # Top-level columns are authoritative; reject unknown stored keys.
        keys = {'departureCity','currency','interests','dietaryNeeds','travelPace','travelStyle','mobilityConcerns'}
        if set(details) - keys:
            raise ValueError()
        preferences = TripPreferences.model_validate({**details,
            'destination': row['destination'], 'startDate': row['start_date'],
            'endDate': row['end_date'], 'budget': row['budget'], 'travelers': row['travelers']})
    except (ValueError, TypeError, KeyError, UnicodeError):
        pass
    record = TripRecord(id=identity, destination=row['destination'], startDate=row['start_date'],
        endDate=row['end_date'], budget=row['budget'], travelers=row['travelers'], createdAt=created,
        preferences=preferences, preferencesStatus='available' if preferences else 'unavailable')
    record.model_dump_json().encode('utf-8')
    return record

class TripService:
    def __init__(self, storage):
        self.storage = storage

    async def create(self, preferences):
        return {'trip': {'id': confirmed_id(await self.storage.save(preferences))}}

    async def list(self, limit, offset):
        rows = await self.storage.list(limit + 1, offset)
        return TripListResponse(trips=[decode_row(row) for row in rows[:limit]],
            limit=limit, offset=offset, hasMore=len(rows) > limit,
            scope='authenticated-user-saved-trips' if getattr(self.storage, 'owner_id', None) else 'local-project-saved-trips')

    async def get(self, identity):
        row = await self.storage.get(identity)
        return None if row is None else decode_row(row)


def build_trip_router(storage):
    router = APIRouter(prefix='/api', tags=['Trips and saved-trip history'])
    def request_service(request):
        owner = getattr(request.state, 'auth_user_id', None)
        if owner is not None:
            return TripService(storage.for_user(owner, request.state.access_token))
        from .auth import ownership_enabled, production_mode
        if ownership_enabled() or production_mode():
            raise StorageNotConfigured()
        return TripService(storage)

    @router.post('/trips', response_model=TripResponse, status_code=201)
    async def create_trip(preferences: TripPreferences, request: Request):
        try:
            return await request_service(request).create(preferences)
        except StorageNotConfigured:
            return fail(503, 'TRIP_STORAGE_NOT_CONFIGURED', 'Trip saving is not configured yet. Your preferences have not been saved.')
        except Exception:
            return fail(500, 'TRIP_SAVE_FAILED', 'The save could not be confirmed. Check stored trips before retrying.')

    async def listing(request, limit, offset):
        try:
            return await HistoryService(request_service(request)).list_saved_trips(limit, offset)
        except StorageNotConfigured:
            return fail(503, 'TRIP_STORAGE_NOT_CONFIGURED', 'Saved-trip storage is not configured.')
        except Exception:
            return fail(502, 'TRIP_READ_FAILED', 'Saved trips could not be read safely. No data was changed.')

    @router.get('/trips', response_model=TripListResponse)
    async def list_trips(request: Request, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        return await listing(request, limit, offset)

    @router.get('/history', response_model=TripListResponse)
    async def saved_history(request: Request, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        return await listing(request, limit, offset)

    @router.get('/trips/{trip_id}', response_model=TripDetailResponse)
    async def get_trip(trip_id: str, request: Request):
        try:
            identity = confirmed_id(trip_id)
        except Exception:
            return fail(400, 'VALIDATION_ERROR', 'Use a positive saved-trip ID.')
        try:
            trip = await request_service(request).get(identity)
            return {'trip': trip} if trip is not None else fail(404, 'TRIP_NOT_FOUND', 'Saved trip not found.')
        except StorageNotConfigured:
            return fail(503, 'TRIP_STORAGE_NOT_CONFIGURED', 'Saved-trip storage is not configured.')
        except Exception:
            return fail(502, 'TRIP_READ_FAILED', 'Saved trip could not be read safely. No data was changed.')

    return router
