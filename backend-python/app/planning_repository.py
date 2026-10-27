"""Durable queue adapter: injected server gateway, never reads credentials.

Requires REVIEW_ONLY migration 003 and explicit activation. No automatic retries:
ambiguous inserts are reconciled by owner+request identity, not repeated blindly.
"""
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from .models import TripPreferences


class JobRepositoryError(Exception):
    def __init__(self, code='JOB_STORAGE_UNCONFIRMED', status=503):
        self.code, self.status = code, status
        super().__init__(code)


def identity(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise JobRepositoryError('INVALID_JOB_ID', 400) from None


def canonical_preferences(preferences):
    value = TripPreferences.model_validate(preferences.model_dump() if isinstance(preferences, TripPreferences) else preferences)
    payload = value.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return payload, digest


class DurablePlanningRepository:
    """Gateway implements request(method, resource, params=..., payload=...).

    It MUST use a server-only service context; HTTP routes must authenticate first
    and pass verified owner IDs. SQL grants no client writes. Never expose rows
    directly: preferences, lease tokens and provider IDs are private server data.
    """
    def __init__(self, gateway, *, enabled=False, clock=lambda: datetime.now(timezone.utc)):
        if enabled is not True:
            raise JobRepositoryError('JOB_STORAGE_DISABLED')
        if getattr(gateway, 'elevated', False) is not True:
            raise JobRepositoryError('JOB_WORKER_CONTEXT_REQUIRED', 403)
        self.gateway, self.clock = gateway, clock

    async def _request(self, method, resource='planning_jobs', **kwargs):
        try:
            rows = await self.gateway.request(method, resource, **kwargs)
            if type(rows) is not list or any(type(row) is not dict for row in rows):
                raise ValueError()
            return rows
        except JobRepositoryError:
            raise
        except Exception:
            raise JobRepositoryError() from None

    async def verify_ready(self):
        rows = await self._request('POST','rpc/planning_queue_health',payload={})
        if len(rows)!=1 or rows[0] != {'schema_version':1,'rpc_version':1,'cron_installed':True,'cleanup_fresh':True}:
            raise JobRepositoryError('JOB_SCHEMA_NOT_READY')

    async def find_request(self, owner, request_id):
        owner, request_id = identity(owner), identity(request_id)
        rows = await self._request('GET', params={'user_id': 'eq.'+owner, 'request_id': 'eq.'+request_id, 'limit': '1'})
        if not rows:
            return None
        if len(rows) != 1 or rows[0].get('user_id') != owner or rows[0].get('request_id') != request_id:
            raise JobRepositoryError()
        return rows[0]

    async def enqueue(self, owner, request_id, preferences):
        owner, request_id = identity(owner), identity(request_id)
        payload, digest = canonical_preferences(preferences)
        previous = await self.find_request(owner, request_id)
        if previous:
            if previous.get('input_hash') != digest:
                raise JobRepositoryError('JOB_REQUEST_CONFLICT', 409)
            return previous
        now = self.clock()
        row = {'id': str(uuid4()), 'user_id': owner, 'request_id': request_id,
               'input_hash': digest, 'preferences': payload, 'status': 'queued',
               'created_at': now.isoformat(), 'expires_at': (now+timedelta(hours=24)).isoformat()}
        try:
            rows = await self._request('POST', 'rpc/enqueue_planning_job', payload={'request_row':row})
        except JobRepositoryError as error:
            if error.code == 'JOB_ADMISSION_REJECTED':
                raise
            # Read-only reconciliation covers a race OR a successful insert whose
            # response was lost. Never submit a second insert in this call.
            confirmed = await self.find_request(owner, request_id)
            if confirmed and confirmed.get('input_hash') == digest:
                return confirmed
            if confirmed:
                raise JobRepositoryError('JOB_REQUEST_CONFLICT', 409)
            raise JobRepositoryError('JOB_START_UNCONFIRMED') from None
        if (len(rows) != 1 or any(rows[0].get(key) != row[key]
                for key in ('user_id', 'request_id'))):
            raise JobRepositoryError()
        if rows[0].get('input_hash') != digest:
            raise JobRepositoryError('JOB_REQUEST_CONFLICT', 409)
        return rows[0]

    async def get(self, owner, job_id):
        owner, job_id = identity(owner), identity(job_id)
        rows = await self._request('GET', params={'user_id':'eq.'+owner, 'id':'eq.'+job_id, 'limit':'1'})
        if not rows:
            raise JobRepositoryError('JOB_NOT_FOUND', 404)
        if len(rows) != 1 or rows[0].get('user_id') != owner or rows[0].get('id') != job_id:
            raise JobRepositoryError()
        return rows[0]

    async def claim(self, worker_id):
        # Atomic SKIP LOCKED selection, lease token and admission live in SQL.
        rows = await self._request('POST', 'rpc/claim_planning_job', payload={'worker': identity(worker_id)})
        if len(rows)>1:
            raise JobRepositoryError()
        return rows[0] if rows else None

    async def transition(self, job_id, lease_token, version, status, *, provider_response_id=None, result=None, error_code=None, evidence=None):
        allowed = {'submitting', 'running', 'succeeded', 'failed', 'submission_unknown', 'cancelled', 'expired'}
        if status not in allowed or type(version) is not int or version<1:
            raise JobRepositoryError('INVALID_JOB_TRANSITION', 400)
        rows = await self._request('POST', 'rpc/transition_planning_job', payload={
            'job': identity(job_id), 'lease': identity(lease_token), 'expected_version': version,
            'next_status': status, 'response_id': provider_response_id, 'output': result, 'failure_code': error_code, 'evidence_payload': evidence})
        if not rows:
            raise JobRepositoryError('JOB_LEASE_LOST', 409)
        if len(rows)!=1 or rows[0].get('id')!=identity(job_id) or rows[0].get('status')!=status:
            raise JobRepositoryError()
        return rows[0]

    async def request_cancel(self, owner, job_id):
        rows = await self._request('POST', 'rpc/cancel_planning_job', payload={'owner':identity(owner), 'job':identity(job_id)})
        if not rows:
            raise JobRepositoryError('JOB_NOT_FOUND', 404)
        if len(rows)!=1 or rows[0].get('user_id')!=identity(owner) or rows[0].get('id')!=identity(job_id):
            raise JobRepositoryError()
        return rows[0]


class PlanningGateway:
    """Server-only fixed-resource REST gateway. Explicit secrets, never dotenv.

    Construct only after approved DB rollout. Credentials are not retained in
    repr/logs; no browser import, ambient proxy, redirect, or automatic retry.
    """
    elevated = True
    def __init__(self, url, service_key, *, enabled=False, transport=None):
        import re
        if enabled is not True:
            raise JobRepositoryError('JOB_STORAGE_DISABLED')
        if not isinstance(url, str) or not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', url):
            raise JobRepositoryError('JOB_STORAGE_CONFIGURATION_INVALID')
        if not isinstance(service_key, str) or not service_key.startswith('sb_secret_') or len(service_key)<20:
            raise JobRepositoryError('JOB_WORKER_CONTEXT_REQUIRED', 403)
        self._url, self._key, self._transport = url, service_key, transport

    async def request(self, method, resource, *, params=None, payload=None):
        import httpx
        permitted = {'planning_jobs': {'GET'}, 'rpc/enqueue_planning_job': {'POST'}, 'rpc/planning_queue_health': {'POST'}, 'rpc/claim_planning_job': {'POST'},
                     'rpc/transition_planning_job': {'POST'}, 'rpc/cancel_planning_job': {'POST'}}
        if method not in permitted.get(resource, set()):
            raise JobRepositoryError('INVALID_JOB_OPERATION', 400)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False, transport=self._transport) as client:
                async with client.stream(method, self._url+'/rest/v1/'+resource, params=params, json=payload,
                    headers={'apikey':self._key,'Accept':'application/json','Prefer':'return=representation'}) as response:
                    status=response.status_code
                    body=bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body)>524288:
                            raise JobRepositoryError()
            rows=json.loads(body)
            if status not in {200,201}:
                if (status==400 and resource=='rpc/enqueue_planning_job' and isinstance(rows,dict)
                    and rows.get('code')=='P0001' and rows.get('message')=='Planning admission limit reached'):
                    raise JobRepositoryError('JOB_ADMISSION_REJECTED',429)
                raise JobRepositoryError()
            if type(rows) is not list:
                raise JobRepositoryError()
            return rows
        except JobRepositoryError:
            raise
        except Exception:
            raise JobRepositoryError() from None


def public_job_snapshot(row, owner, *, now=None):
    """Revalidate persisted output; never pass storage/provider details to UI."""
    from .itineraries import ItineraryResponse, ItineraryPayload, validate_itinerary
    now = now or datetime.now(timezone.utc)
    try:
        if row['user_id']!=identity(owner):
            raise ValueError()
        created=datetime.fromisoformat(row['created_at'].replace('Z','+00:00'))
        expires=datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))
        if created.tzinfo is None or expires.tzinfo is None or expires<=created:
            raise ValueError()
        status = 'expired' if now>=expires else row['status']
        if status not in {'queued','submitting','running','succeeded','failed','submission_unknown','cancelled','expired'}:
            raise ValueError()
        result=None
        if status=='succeeded':
            candidate=ItineraryResponse.model_validate(row['result'])
            if candidate.vibe is not None or candidate.refinementSummary is not None:
                raise ValueError()
            for day in candidate.days:
                if (day.mainActivityCount != sum(activity.kind=='main' for activity in day.activities)
                    or any(activity.kind=='unknown' or activity.fixedTime for activity in day.activities)):
                    raise ValueError()
            payload={k:v for k,v in candidate.model_dump().items() if k in ItineraryPayload.model_fields}
            result=validate_itinerary(payload,TripPreferences.model_validate(row['preferences']),candidate.provider,candidate.model).model_dump(mode='json')
        from .evidence_envelope import validate_evidence_envelope
        evidence=validate_evidence_envelope(row.get('evidence'),result,now=now) if status=='succeeded' else None
        error_code={'failed':('JOB_TRAVEL_CONFLICT' if row.get('error_code')=='JOB_TRAVEL_CONFLICT' else 'JOB_FAILED'),'submission_unknown':'JOB_SUBMISSION_UNCONFIRMED','expired':'JOB_EXPIRED'}.get(status)
        return {'id':identity(row['id']),'requestId':identity(row['request_id']),'status':status,
                'result':result,'evidence':evidence,'error':{'code':error_code} if error_code else None,
                'createdAt':created.isoformat(),'expiresAt':expires.isoformat()}
    except Exception:
        raise JobRepositoryError('JOB_RESULT_UNCONFIRMED') from None
