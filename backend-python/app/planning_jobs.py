"""Bounded, ephemeral job prototype. Never configure this as a production queue.

No provider, database, credentials or disk access. A caller must inject generation.
Expired tombstones remain until process exit: the same request cannot silently
start paid work again. Capacity includes tombstones and fails closed when full.
A restart loses all jobs; durable storage/leases require separately approved work.
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import time
from uuid import UUID, uuid4

from .itineraries import MAX_DAYS, ItineraryPayload, ItineraryResponse, validate_itinerary
from .models import TripPreferences


class PlanningJobError(Exception):
    def __init__(self, status, code, public_message):
        super().__init__(code)
        self.status, self.code, self.public_message = status, code, public_message


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


@dataclass
class _Job:
    id: str
    owner: str
    request_id: str
    fingerprint: str
    preferences: TripPreferences | None
    created_at: float
    expires_at: float
    status: str = 'queued'
    result: dict | None = None
    error: dict | None = None
    task: asyncio.Task | None = None
    expiry_task: asyncio.Task | None = None


class PlanningJobEngine:
    def __init__(self, generator, *, max_jobs=100, max_concurrency=2,
                 ttl_seconds=900, timeout_seconds=210, clock=time.time):
        if not callable(generator):
            raise ValueError('An explicit generator is required.')
        if any(type(v) is not int or v < 1 for v in (max_jobs, max_concurrency)):
            raise ValueError('Capacity must be a positive integer.')
        if not all(math.isfinite(v) for v in (timeout_seconds, ttl_seconds)) or not 0 < timeout_seconds <= ttl_seconds:
            raise ValueError('Timeout must fit within the job lifetime.')
        self._generator, self._clock = generator, clock
        self._max_jobs, self._ttl, self._timeout = max_jobs, ttl_seconds, timeout_seconds
        self._slots = asyncio.Semaphore(max_concurrency)
        self._jobs, self._requests = {}, {}
        self._closed = False
        self._producers = set()

    def _expire(self):
        for job in self._jobs.values():
            if job.status != 'expired' and self._clock() >= job.expires_at:
                job.status, job.result, job.preferences = 'expired', None, None
                job.error = {'code': 'JOB_EXPIRED', 'message': 'This temporary job has expired. No automatic retry was made.'}
                if job.task and not job.task.done():
                    job.task.cancel()

    def _snapshot(self, job):
        return deepcopy({'id': job.id, 'requestId': job.request_id,
            'status': job.status, 'result': job.result, 'error': job.error,
            'createdAt': _iso(job.created_at), 'expiresAt': _iso(job.expires_at)})

    def _find(self, owner, job_id):
        self._expire()
        job = self._jobs.get(job_id)
        if not owner or job is None or job.owner != owner:
            raise PlanningJobError(404, 'JOB_NOT_FOUND', 'This job is unavailable or no longer exists.')
        return job

    async def start(self, owner, request_id, preferences):
        if not isinstance(owner, str) or not owner.strip():
            raise PlanningJobError(401, 'AUTH_REQUIRED', 'Sign in to create a planning job.')
        try:
            request_id = str(UUID(str(request_id)))
        except (ValueError, TypeError, AttributeError):
            raise PlanningJobError(400, 'INVALID_REQUEST_ID', 'Use a unique request identifier.') from None
        preferences = TripPreferences.model_validate(preferences.model_dump() if isinstance(preferences, TripPreferences) else preferences)
        if (date.fromisoformat(preferences.endDate) - date.fromisoformat(preferences.startDate)).days + 1 > MAX_DAYS:
            raise PlanningJobError(400, 'ITINERARY_DURATION_UNSUPPORTED', 'AI itineraries support trips of 1–14 days.')
        fingerprint = hashlib.sha256(json.dumps(preferences.model_dump(mode='json'), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self._expire()
        existing = self._requests.get((owner, request_id))
        if existing:
            job = self._jobs[existing]
            if job.fingerprint != fingerprint:
                raise PlanningJobError(409, 'REQUEST_CONFLICT', 'This request identifier belongs to different trip preferences.')
            return self._snapshot(job)
        if self._closed or len(self._jobs) >= self._max_jobs:
            raise PlanningJobError(503, 'JOB_CAPACITY', 'Temporary planning capacity is unavailable. No generation was started.')
        now = self._clock()
        job = _Job(str(uuid4()), owner, request_id, fingerprint, preferences, now, now + self._ttl)
        self._jobs[job.id] = job
        self._requests[(owner, request_id)] = job.id
        job.task = asyncio.create_task(self._run(job))
        job.expiry_task = asyncio.create_task(self._expire_later(job))
        return self._snapshot(job)

    def context(self, owner, job_id):
        snapshot = self.get(owner, job_id)
        job = self._jobs[job_id]
        preferences = job.preferences.model_dump(mode='json') if job.preferences is not None else None
        return {'preferences': preferences, 'job': snapshot}

    def request_context(self, owner, request_id):
        return self.context(owner, self.find_request(owner, request_id)['id'])

    def find_request(self, owner, request_id):
        job_id = self._requests.get((owner, str(UUID(request_id))))
        if job_id is None:
            raise PlanningJobError(404, 'JOB_NOT_FOUND', 'This planning session is no longer available.')
        return self.get(owner, job_id)

    def get(self, owner, job_id):
        return self._snapshot(self._find(owner, job_id))

    async def cancel(self, owner, job_id):
        job = self._find(owner, job_id)
        if job.status in {'queued', 'running'}:
            job.status = 'cancelled'
            job.error = {'code': 'JOB_CANCELLED', 'message': 'Planning was cancelled. Upstream processing or charges may still occur; no result will be accepted.'}
            job.task.cancel()
        return self._snapshot(job)

    def _validated(self, response, preferences):
        # The injected service handles the private GenerationContract. The queue
        # accepts only its public envelope and rechecks all request constraints.
        response = ItineraryResponse.model_validate(response.model_dump() if isinstance(response, ItineraryResponse) else response)
        payload = {name: getattr(response, name) for name in ItineraryPayload.model_fields}
        payload = ItineraryPayload(**payload).model_dump(mode='json')
        result = validate_itinerary(payload, preferences, response.provider, response.model)
        if result.vibe is not None or response.refinementSummary is not None:
            raise ValueError('Generation cannot contain refinement metadata.')
        for day in result.days:
            if sum(a.kind == 'main' for a in day.activities) != day.mainActivityCount:
                raise ValueError('Main count mismatch.')
            if any(a.kind == 'unknown' or a.fixedTime for a in day.activities):
                raise ValueError('Generation cannot invent commitments.')
        return result.model_dump(mode='json')

    async def _expire_later(self, job):
        await asyncio.sleep(max(0, job.expires_at - self._clock()))
        self._expire()

    async def _produce(self, job, preferences):
        # The slot belongs to actual work, not the polling wrapper. If an
        # injected provider suppresses cancellation it cannot free capacity and
        # allow unbounded replacement requests while it is still processing.
        async with self._slots:
            self._expire()
            if job.status != 'queued':
                return None
            job.status = 'running'
            return await self._generator(preferences)

    @staticmethod
    def _consume_exception(task):
        if not task.cancelled():
            task.exception()

    async def _run(self, job):
        producer = None
        try:
            preferences = job.preferences.model_copy(deep=True)
            producer = asyncio.create_task(self._produce(job, preferences))
            self._producers.add(producer)
            producer.add_done_callback(self._producers.discard)
            producer.add_done_callback(self._consume_exception)
            # Unlike wait_for, wait does not wait indefinitely for a provider
            # that suppresses cancellation. Late results are never accepted.
            completed, _ = await asyncio.wait({producer}, timeout=min(self._timeout, max(0, job.expires_at - self._clock())))
            if not completed:
                producer.cancel()
                raise TimeoutError()
            response = producer.result()
            self._expire()
            if job.status != 'running':
                return
            result = self._validated(response, preferences)
            self._expire()
            if job.status == 'running':
                job.status, job.result = 'succeeded', result
        except asyncio.CancelledError:
            if producer:
                producer.cancel()
            if job.status in {'queued', 'running'}:
                job.status = 'cancelled'
            raise
        except Exception as exc:
            self._expire()
            if job.status in {'queued', 'running'}:
                timeout = isinstance(exc, TimeoutError)
                job.status = 'failed'
                job.error = {'code': 'JOB_TIMEOUT' if timeout else 'JOB_GENERATION_FAILED',
                    'message': 'Planning timed out. No automatic retry was made.' if timeout else 'A valid itinerary could not be confirmed. No automatic retry was made.'}

    async def close(self):
        self._closed = True
        tasks = []
        for job in self._jobs.values():
            if job.expiry_task:
                job.expiry_task.cancel()
                tasks.append(job.expiry_task)
            if job.task and not job.task.done():
                await self.cancel(job.owner, job.id)
                tasks.append(job.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Do not let a cancellation-resistant injected provider block shutdown.
        # This prototype cannot promise upstream cancellation or charge reversal.
        for producer in self._producers.copy():
            producer.cancel()
