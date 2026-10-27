"""Explicitly injected durable background worker; importing starts no work.

Production activation, migration and temporary provider retention need separate
approval. One tick claims one record. Never repeat a create after an ambiguous
submission; polling/restart recovery uses the stored provider response identity.
"""
from datetime import datetime, timezone
import json
import logging
from uuid import uuid4
from .generation_contract import GenerationContract
from .itineraries import MAX_DAYS, validate_itinerary
from .models import TripPreferences
from .planning_repository import JobRepositoryError
from .prompts import build_itinerary_prompt


_logger = logging.getLogger(__name__)


def _provider_diagnostic(phase, *, error=None, status=None, refused=False):
    from .openai_background import background_error_metadata, STATUSES, DIAGNOSTIC_PHASES
    if error is not None:
        metadata = background_error_metadata(error, phase)
    else:
        metadata = {'phase': phase if phase in DIAGNOSTIC_PHASES else 'unknown',
            'code': 'BACKGROUND_TERMINAL',
            'status': status if type(status) is str and status in STATUSES else 'unknown',
            'refused': refused is True}
    _logger.warning('Planning provider diagnostic: %s', json.dumps(metadata, sort_keys=True))


class PlanningWorker:
    def __init__(self, repository, client, *, enabled=False, worker_id=None,
                 clock=lambda: datetime.now(timezone.utc), deadline_seconds=480, feasibility_gate=None):
        if enabled is not True:
            raise ValueError('Background worker activation is required.')
        if not 0 < deadline_seconds <= 480:
            raise ValueError('Background deadline cannot exceed eight minutes.')
        self.repository, self.client = repository, client
        self.worker_id, self.clock = worker_id or str(uuid4()), clock
        self.deadline_seconds = deadline_seconds
        if feasibility_gate is not None and not callable(feasibility_gate):
            raise ValueError('Feasibility gate must be explicitly injected.')
        self.feasibility_gate = feasibility_gate

    async def _transition(self, row, status, **kwargs):
        return await self.repository.transition(row['id'], row['lease_token'], row['version'], status, **kwargs)

    async def cancel(self, row):
        """Best effort only, after DB cancellation wins; never expose output."""
        response_id = row.get('provider_response_id')
        if response_id:
            try:
                await self.client.cancel(response_id)
            except Exception as error:
                _provider_diagnostic('cancel', error=error)
                return False
        return True

    def _expired(self, row):
        created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
        expires = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        now = self.clock()
        return now >= expires or (now - created).total_seconds() >= self.deadline_seconds

    async def tick(self):
        row = await self.repository.claim(self.worker_id)
        if row is None:
            return None
        if row['status'] not in {'queued', 'running'}:
            # The repository must quarantine expired submitting leases itself.
            raise JobRepositoryError('INVALID_JOB_CLAIM')
        response_id = row.get('provider_response_id')
        created_this_tick = False
        try:
            if row.get('cancel_requested'):
                await self.cancel(row)
                return {'id': row['id'], 'status': 'cancelled'}
            if self._expired(row):
                expired = await self._transition(row, 'expired' if row['status'] == 'running' else 'failed', error_code='JOB_EXPIRED')
                await self.cancel(expired)
                return expired
            try:
                preferences = TripPreferences.model_validate(row['preferences'])
                prompt = build_itinerary_prompt(preferences)
                if not 1 <= prompt.tripDays <= MAX_DAYS:
                    raise ValueError()
                contract = GenerationContract(preferences)
            except Exception:
                return await self._transition(row, 'failed', error_code='JOB_INVALID_PREFERENCES')
            if row['status'] == 'queued':
                # This write precedes the only non-idempotent provider operation.
                # A process crash after it is quarantined, never auto-retried.
                row = await self._transition(row, 'submitting')
                try:
                    response = await self.client.create(prompt.messages[0].content + contract.instructions,
                        prompt.messages[1].content, contract.schema)
                except Exception as error:
                    _provider_diagnostic('create', error=error)
                    ambiguous = getattr(error, 'ambiguous_create', True)
                    return await self._transition(row, 'submission_unknown' if ambiguous else 'failed',
                        error_code='JOB_SUBMISSION_UNCONFIRMED' if ambiguous else 'JOB_PROVIDER_REJECTED')
                response_id = response.response_id
                created_this_tick = True
                # Persisting running releases this lease. Even an immediate
                # completion is retrieved under a fresh claim before publishing.
                return await self._transition(row, 'running', provider_response_id=response_id)
            else:
                if not response_id:
                    return await self._transition(row, 'failed', error_code='JOB_RESPONSE_ID_MISSING')
                try:
                    response = await self.client.retrieve(response_id)
                except Exception as error:
                    _provider_diagnostic('retrieve', error=error)
                    # Keep the original identity for another bounded poll; never
                    # convert a read error into a second create operation.
                    return await self._transition(row, 'running', error_code='JOB_POLL_UNCONFIRMED')
            if response.response_id != response_id:
                return await self._transition(row, 'failed', error_code='JOB_RESPONSE_ID_MISMATCH')
            if self._expired(row):
                expired = await self._transition(row, 'expired', error_code='JOB_EXPIRED')
                await self.cancel(expired)
                return expired
            if response.status in {'queued', 'in_progress'}:
                return await self._transition(row, 'running')
            if response.status not in {'queued', 'in_progress'}:
                _provider_diagnostic('retrieve', status=response.status, refused=response.refused)
            if response.status == 'cancelled':
                return await self._transition(row, 'cancelled', error_code='JOB_PROVIDER_CANCELLED')
            if response.status != 'completed' or response.refused:
                return await self._transition(row, 'failed', error_code='JOB_PROVIDER_FAILED')
            try:
                public_payload = contract.decode(response.output_text)
                validated = validate_itinerary(public_payload, preferences, 'openai', 'gpt-6-luna')
                if validated.vibe is not None:
                    raise ValueError()
            except Exception:
                return await self._transition(row, 'failed', error_code='JOB_INVALID_RESULT')
            evidence = None
            if self.feasibility_gate is not None and validated.status == 'planned':
                try:
                    report = self.feasibility_gate(validated.model_dump(mode='json'), preferences.model_dump(mode='json'))
                    if getattr(report, 'feasible', None) is not True:
                        return await self._transition(row, 'failed', error_code='JOB_TRAVEL_CONFLICT')
                    from .evidence_envelope import build_evidence_envelope
                    evidence = build_evidence_envelope(validated.model_dump(mode='json'), report)
                except Exception as error:
                    from .travel_feasibility import FeasibilityConflict
                    code = 'JOB_TRAVEL_CONFLICT' if isinstance(error, FeasibilityConflict) else 'JOB_TRAVEL_CHECK_UNCONFIRMED'
                    return await self._transition(row, 'failed', error_code=code)
            # CAS prevents a late provider success from reviving a cancelled job.
            return await self._transition(row, 'succeeded', result=validated.model_dump(mode='json'), evidence=evidence)
        except JobRepositoryError:
            # A lost lease is not cancellation authority: another worker may
            # now own the same provider response, or the write may have succeeded.
            # Reconcile read-only and cancel only a confirmed durable cancellation.
            if response_id:
                try:
                    current = await self.repository.get(row['user_id'], row['id'])
                except Exception:
                    current = None
                if current and current.get('status') == 'cancelled' and (
                        current.get('provider_response_id') == response_id
                        or (created_this_tick and current.get('provider_response_id') is None)):
                    await self.cancel({'provider_response_id': response_id})
            raise
