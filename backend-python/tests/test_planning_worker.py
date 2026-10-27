import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import json
import pytest
from app.planning_worker import PlanningWorker
from app.planning_repository import JobRepositoryError

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


class Repository:
    def __init__(self, payload):
        self.row = dict(id=str(uuid4()), user_id=str(uuid4()), request_id=str(uuid4()),
            preferences=payload, status='queued', version=1, lease_token=None,
            provider_response_id=None, created_at=NOW.isoformat(), expires_at=(NOW+timedelta(hours=24)).isoformat())
        self.transitions = []
        self.lose_on = None
    async def get(self, owner, identity):
        assert owner == self.row['user_id'] and identity == self.row['id']
        return deepcopy(self.row)
    async def claim(self, worker):
        if self.row['status'] not in {'queued', 'running'}: return None
        self.row['lease_token'] = str(uuid4())
        self.row['version'] += 1
        return deepcopy(self.row)
    async def transition(self, job, lease, version, status, **fields):
        if self.lose_on == status or version != self.row['version'] or lease != self.row['lease_token'] or lease is None:
            raise JobRepositoryError('JOB_LEASE_LOST', 409)
        self.transitions.append(status)
        self.row.update(status=status, version=version+1, **fields)
        if status != 'submitting': self.row['lease_token'] = None
        return deepcopy(self.row)


class Client:
    def __init__(self):
        self.creates, self.reads, self.cancels = [], [], []
        self.create_error = self.read_error = None
        self.response = SimpleNamespace(response_id='resp_fixture', status='queued', output_text=None, refused=False)
    async def create(self, system, user, schema):
        self.creates.append((system, user, schema))
        if self.create_error: raise self.create_error
        return deepcopy(self.response)
    async def retrieve(self, identity):
        self.reads.append(identity)
        if self.read_error: raise self.read_error
        return deepcopy(self.response)
    async def cancel(self, identity):
        self.cancels.append(identity)
        return deepcopy(self.response)


def worker(repo, client, **kw):
    return PlanningWorker(repo, client, enabled=True, clock=lambda:NOW, **kw)


def complete(client):
    client.response.status = 'completed'
    client.response.output_text = json.dumps(dict(status='infeasible', days=[], explanation='Budget cannot support verified travel costs.',
        warnings={'verificationWarning':'Prices, hours and transport are unverified.', 'additionalWarnings':[]}))


def test_submission_then_restart_resumes_same_id_and_validates(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        complete(client)  # even immediate completion must persist ID first
        first = await worker(repo, client).tick()
        assert first['status'] == 'running'
        assert repo.transitions == ['submitting', 'running']
        assert len(client.creates) == 1 and not client.reads
        result = await worker(repo, client).tick()
        assert result['status'] == 'succeeded'
        assert result['result']['saved'] is False
        assert result['result']['model'] == 'gpt-6-luna'
        assert client.reads == ['resp_fixture']
        assert await worker(repo, client).tick() is None
    asyncio.run(scenario())


@pytest.mark.parametrize('ambiguous', [True, False])
def test_create_failure_never_retries(payload, ambiguous):
    async def scenario():
        repo, client = Repository(payload), Client()
        error = RuntimeError('private credential should never escape')
        error.ambiguous_create = ambiguous
        client.create_error = error
        row = await worker(repo, client).tick()
        assert row['status'] == ('submission_unknown' if ambiguous else 'failed')
        assert await worker(repo, client).tick() is None
        assert len(client.creates) == 1
        assert 'private' not in str(row)
    asyncio.run(scenario())


def test_poll_error_and_in_progress_release_lease_without_recreate(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        await worker(repo, client).tick()
        client.read_error = RuntimeError('offline')
        row = await worker(repo, client).tick()
        assert row['status'] == 'running' and row['lease_token'] is None
        client.read_error = None
        client.response.status = 'in_progress'
        row = await worker(repo, client).tick()
        assert row['status'] == 'running' and row['lease_token'] is None
        assert len(client.creates) == 1 and client.reads == ['resp_fixture', 'resp_fixture']
    asyncio.run(scenario())


@pytest.mark.parametrize('lost_status', ['running', 'succeeded'])
def test_cas_loss_does_not_cancel_new_owner_work_or_publish(payload, lost_status):
    async def scenario():
        repo, client = Repository(payload), Client()
        if lost_status == 'succeeded':
            await worker(repo, client).tick()
            complete(client)
        repo.lose_on = lost_status
        with pytest.raises(JobRepositoryError):
            await worker(repo, client).tick()
        assert client.cancels == []
        assert repo.row['status'] != 'succeeded'
        assert len(client.creates) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('status', ['failed', 'incomplete', 'cancelled', 'invalid_result', 'refused'])
def test_provider_terminal_failures_and_invalid_results(payload, status):
    async def scenario():
        repo, client = Repository(payload), Client()
        await worker(repo, client).tick()
        complete(client)
        if status == 'invalid_result': client.response.output_text = '{}'
        elif status == 'refused': client.response.refused = True
        else: client.response.status = status
        row = await worker(repo, client).tick()
        assert row['status'] == ('cancelled' if status == 'cancelled' else 'failed')
        assert not row.get('result')
    asyncio.run(scenario())


def test_processing_expiry_cancels_and_never_recreates(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        await worker(repo, client).tick()
        later = PlanningWorker(repo, client, enabled=True, clock=lambda:NOW+timedelta(minutes=8))
        row = await later.tick()
        assert row['status'] == 'expired' and client.cancels == ['resp_fixture']
        assert len(client.creates) == 1 and not client.reads
    asyncio.run(scenario())


def test_expired_queued_and_invalid_preferences_never_submit(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        repo.row['created_at'] = (NOW-timedelta(minutes=9)).isoformat()
        assert (await worker(repo, client).tick())['status'] == 'failed'
        assert not client.creates
        repo = Repository({**payload, 'endDate':'2027-01-01'})
        assert (await worker(repo, client).tick())['error_code'] == 'JOB_INVALID_PREFERENCES'
        assert not client.creates
    asyncio.run(scenario())


def test_activation_off_by_default(payload):
    with pytest.raises(ValueError):
        PlanningWorker(Repository(payload), Client())


def test_complete_planned_contract_becomes_validated_public_itinerary(payload):
    async def scenario():
        from app.generation_contract import GenerationContract
        from app.models import TripPreferences
        repo, client = Repository(payload), Client()
        await worker(repo, client).tick()
        contract = GenerationContract(TripPreferences.model_validate(payload))
        days = []
        for day in contract.dates:
            entries = {f'main_{i+1}':dict(id=f'activity-{i}', title='Museum' if i == 0 else 'Cultural walk',
                durationMinutes=60, notes='Check opening and access before visiting.', latitude=None, longitude=None,
                kind='main', gapBeforeMinutes=0 if i == 0 else 60, sequence=i+1) for i in range(2)}
            days.append(dict(date=day, morning='Museum visit.', afternoon='Cultural walk.', evening='Rest.',
                dining='Confirm meal suitability directly.', dietaryNotes='No dietary needs supplied.',
                mobilityNotes='No mobility needs supplied.', transitAndRest='Allow travel and rest between activities.',
                interestTags=['culture'], costs=dict(accommodation=100, meals=20, localTransport=10, activities=10, departureTravel=20),
                dayStart='09:00', requiredMainActivities=entries, activities=[]))
        client.response.status = 'completed'
        client.response.output_text = json.dumps(dict(days=days, status='planned', explanation='Cautious estimated plan.',
            warnings=dict(verificationWarning='Prices, hours, locations and access are unverified.', additionalWarnings=[])))
        done = await worker(repo, client).tick()
        assert done['status'] == 'succeeded'
        assert len(done['result']['days']) == 6
        assert done['result']['estimatedTotalGroupCost'] == 960
        assert done['result']['days'][0]['activities'][1]['startTime'] == '11:00'
    asyncio.run(scenario())


def test_cancelled_create_leaves_submitting_for_repository_quarantine(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        client.create_error = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await worker(repo, client).tick()
        assert repo.row['status'] == 'submitting'
        assert repo.transitions == ['submitting'] and len(client.creates) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('durable_status', ['running', 'succeeded', 'cancelled', 'unavailable'])
def test_ambiguous_write_reconciliation_cancels_only_confirmed_cancellation(payload, durable_status):
    async def scenario():
        class RaceRepository(Repository):
            async def transition(self, job, lease, version, status, **fields):
                if status == 'running':
                    # The request may have committed while another worker or
                    # cancellation changes the row before this worker reconciles.
                    self.row.update(status=durable_status, provider_response_id=fields['provider_response_id'])
                    raise JobRepositoryError('JOB_STORAGE_UNCONFIRMED')
                return await super().transition(job, lease, version, status, **fields)
            async def get(self, owner, identity):
                if durable_status == 'unavailable': raise JobRepositoryError()
                return await super().get(owner, identity)
        repo, client = RaceRepository(payload), Client()
        with pytest.raises(JobRepositoryError): await worker(repo, client).tick()
        assert client.cancels == (['resp_fixture'] if durable_status == 'cancelled' else [])
        assert len(client.creates) == 1
    asyncio.run(scenario())


def test_stale_worker_cannot_cancel_after_expiry_cas_lost(payload):
    async def scenario():
        repo, client = Repository(payload), Client()
        await worker(repo, client).tick()
        repo.lose_on = 'expired'
        stale = PlanningWorker(repo, client, enabled=True, clock=lambda: NOW+timedelta(minutes=8))
        with pytest.raises(JobRepositoryError): await stale.tick()
        assert repo.row['status'] == 'running' and not client.cancels
    asyncio.run(scenario())
