"""Authenticated-route facade for durable jobs. Explicit injection only."""
import asyncio
import logging
import time
from .planning_repository import public_job_snapshot, JobRepositoryError
from .planning_jobs import PlanningJobError
from .models import TripPreferences
from .prompts import build_itinerary_prompt


class DurablePlanningCoordinator:
    def __init__(self, repository, worker, *, enabled=False, require_health=False):
        if enabled is not True:
            raise ValueError('Durable planning activation is required.')
        self.repository, self.worker = repository, worker
        self.require_health = require_health
        self._ready, self._ready_checked = False, 0.0

    async def verify_ready(self):
        if self.require_health:
            try:
                await self.repository.verify_ready()
            except Exception:
                self._ready, self._ready_checked = False, time.monotonic()
                raise
            self._ready, self._ready_checked = True, time.monotonic()

    def capability_ready(self):
        # Public capability discovery never opens a database connection. The
        # authenticated start path and app-owned worker refresh this health.
        return self.require_health and self._ready and 0 <= time.monotonic()-self._ready_checked <= 15

    async def _execute(self, owner, operation):
        try:
            return public_job_snapshot(await operation(), owner)
        except JobRepositoryError as error:
            messages = {429:'Please wait before starting another plan.',404:'This planning session is no longer available.',
                        409:'These trip details changed. Start a new planning session.',
                        400:'Check your trip details.'}
            raise PlanningJobError(error.status,error.code,messages.get(error.status,
                'Your plan could not be checked. Check this session before starting another plan.')) from None

    async def start(self, owner, request_id, preferences):
        if self.require_health:
            await self.verify_ready()
        preferences=TripPreferences.model_validate(preferences.model_dump() if isinstance(preferences,TripPreferences) else preferences)
        if not 1<=build_itinerary_prompt(preferences).tripDays<=14:
            raise PlanningJobError(400,'VALIDATION_ERROR','Choose a trip of 1–14 days.')
        return await self._execute(owner,lambda:self.repository.enqueue(owner,request_id,preferences))

    async def context(self, owner, job_id):
        try:
            row = await self.repository.get(owner, job_id)
            snapshot = public_job_snapshot(row, owner)
            preferences = None if snapshot['status']=='expired' else TripPreferences.model_validate(row['preferences']).model_dump(mode='json')
            return {'preferences': preferences, 'job': snapshot}
        except JobRepositoryError as error:
            raise PlanningJobError(error.status,error.code,'This planning session could not be checked.') from None

    async def request_context(self, owner, request_id):
        job = await self.find_request(owner, request_id)
        return await self.context(owner, job['id'])

    async def find_request(self, owner, request_id):
        async def lookup():
            row = await self.repository.find_request(owner, request_id)
            if row is None:
                raise JobRepositoryError('JOB_NOT_FOUND', 404)
            return row
        return await self._execute(owner, lookup)

    async def get(self, owner, job_id):
        return await self._execute(owner,lambda:self.repository.get(owner,job_id))

    async def cancel(self, owner, job_id):
        async def stop():
            row=await self.repository.request_cancel(owner,job_id)
            if row['status']=='cancelled':
                await self.worker.cancel(row)
            return row
        return await self._execute(owner,stop)

    async def run(self, stop, *, interval_seconds=5):
        """App-owned bounded polling loop. Not a scheduler or always-on promise."""
        if not 1 <= interval_seconds <= 60:
            raise ValueError('Polling interval must be 1–60 seconds.')
        while not stop.is_set():
            try:
                await self.verify_ready()
                await self.worker.tick()
            except Exception:
                # Persisted state and lease define recovery; never retry a create
                # here, print secrets, or invent a successful result.
                logging.getLogger(__name__).warning('Planning worker tick unconfirmed: JOB_WORKER_UNAVAILABLE')
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
