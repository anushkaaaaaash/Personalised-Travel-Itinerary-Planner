import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from app.itineraries import validate_itinerary
from app.models import TripPreferences
from app.planning_jobs import PlanningJobEngine, PlanningJobError


def result(p):
    return validate_itinerary(dict(status='infeasible', destination=p.destination,
        currency=p.currency, travelStyle=p.travelStyle, travelPace=p.travelPace,
        explanation='Travel costs cannot be confirmed within this budget.', days=[],
        warnings=['Prices, hours and transport remain unverified.']), p, 'fixture', 'offline')


async def settled(engine, owner, job_id):
    for _ in range(50):
        snapshot = engine.get(owner, job_id)
        if snapshot['status'] not in {'queued', 'running'}:
            return snapshot
        await asyncio.sleep(0.001)
    pytest.fail('Job did not settle')


def test_deduplication_conflict_owner_isolation_and_validated_result(payload):
    async def scenario():
        calls = []
        async def generate(p):
            calls.append(p)
            return result(p)
        engine = PlanningJobEngine(generate)
        request_id = str(uuid4())
        first, duplicate = await asyncio.gather(engine.start('one', request_id, payload), engine.start('one', request_id, payload))
        assert first['id'] == duplicate['id']
        done = await settled(engine, 'one', first['id'])
        assert done['status'] == 'succeeded' and done['result']['saved'] is False
        assert len(calls) == 1
        assert set(done) == {'id', 'requestId', 'status', 'result', 'error', 'createdAt', 'expiresAt'}
        done['result']['warnings'].clear()
        assert engine.get('one', first['id'])['result']['warnings']
        with pytest.raises(PlanningJobError) as error:
            engine.get('two', first['id'])
        assert error.value.status == 404
        with pytest.raises(PlanningJobError):
            await engine.cancel('two', first['id'])
        with pytest.raises(PlanningJobError) as error:
            await engine.start('one', request_id, {**payload, 'budget': 3000})
        assert error.value.status == 409
        other = await engine.start('two', request_id, payload)
        assert other['id'] != first['id']
        await engine.close()
    asyncio.run(scenario())


def test_concurrency_queued_cancellation_and_no_automatic_retry(payload):
    async def scenario():
        release = asyncio.Event()
        calls = []
        async def generate(p):
            calls.append(p)
            await release.wait()
            return result(p)
        engine = PlanningJobEngine(generate, max_concurrency=1)
        one = await engine.start('one', str(uuid4()), payload)
        two = await engine.start('one', str(uuid4()), payload)
        await asyncio.sleep(0.005)
        assert engine.get('one', one['id'])['status'] == 'running'
        assert engine.get('one', two['id'])['status'] == 'queued'
        assert (await engine.cancel('one', two['id']))['status'] == 'cancelled'
        release.set()
        await settled(engine, 'one', one['id'])
        assert len(calls) == 1
        replay = await engine.start('one', two['requestId'], payload)
        assert replay['status'] == 'cancelled'
        await engine.close()
    asyncio.run(scenario())


def test_cancel_race_rejects_provider_that_swallows_cancellation(payload):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def generate(p):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                return result(p)
            return result(p)
        engine = PlanningJobEngine(generate)
        job = await engine.start('one', str(uuid4()), payload)
        await started.wait()
        await engine.cancel('one', job['id'])
        await asyncio.sleep(0.005)
        assert engine.get('one', job['id'])['status'] == 'cancelled'
        assert engine.get('one', job['id'])['result'] is None
        await engine.close()
    asyncio.run(scenario())


def test_expiry_erases_result_retains_dedup_tombstone_and_capacity(payload):
    async def scenario():
        now = [1000.0]
        async def generate(p):
            return result(p)
        engine = PlanningJobEngine(generate, max_jobs=1, ttl_seconds=10, timeout_seconds=5, clock=lambda: now[0])
        job = await engine.start('one', str(uuid4()), payload)
        await settled(engine, 'one', job['id'])
        now[0] += 11
        expired = engine.get('one', job['id'])
        assert expired['status'] == 'expired' and expired['result'] is None
        assert (await engine.start('one', job['requestId'], payload))['status'] == 'expired'
        with pytest.raises(PlanningJobError) as error:
            await engine.start('one', str(uuid4()), payload)
        assert error.value.code == 'JOB_CAPACITY'
        await engine.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('corruption', ['destination', 'vibe', 'provider_error', 'invalid_schema'])
def test_invalid_results_and_exceptions_fail_safely(payload, corruption):
    async def scenario():
        async def generate(p):
            if corruption == 'provider_error':
                raise RuntimeError('private token secret')
            response = result(p).model_dump()
            if corruption == 'destination': response['destination'] = 'Elsewhere'
            if corruption == 'vibe': response['vibe'] = 'luxury'
            if corruption == 'invalid_schema': response['secret'] = 'private token secret'
            return response
        engine = PlanningJobEngine(generate)
        job = await engine.start('one', str(uuid4()), payload)
        done = await settled(engine, 'one', job['id'])
        assert done['status'] == 'failed' and done['result'] is None
        assert 'secret' not in str(done)
        assert (await engine.start('one', job['requestId'], payload))['status'] == 'failed'
        await engine.close()
    asyncio.run(scenario())


def test_timeout_and_input_authorization(payload):
    async def scenario():
        async def generate(p):
            await asyncio.sleep(10)
        engine = PlanningJobEngine(generate, timeout_seconds=0.005)
        with pytest.raises(PlanningJobError) as error:
            await engine.start('', str(uuid4()), payload)
        assert error.value.status == 401
        with pytest.raises(PlanningJobError) as error:
            await engine.start('one', 'not-an-id', payload)
        assert error.value.status == 400
        job = await engine.start('one', str(uuid4()), payload)
        done = await settled(engine, 'one', job['id'])
        assert done['error']['code'] == 'JOB_TIMEOUT'
        await engine.close()
    asyncio.run(scenario())


def test_timeout_does_not_accept_late_result_or_release_busy_capacity(payload):
    async def scenario():
        release = asyncio.Event()
        calls = []
        async def generate(p):
            calls.append(p)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return result(p)
        engine = PlanningJobEngine(generate, max_concurrency=1, timeout_seconds=0.005)
        one = await engine.start('one', str(uuid4()), payload)
        done = await settled(engine, 'one', one['id'])
        assert done['error']['code'] == 'JOB_TIMEOUT'
        two = await engine.start('one', str(uuid4()), payload)
        await asyncio.sleep(0.001)
        assert engine.get('one', two['id'])['status'] == 'queued'
        assert len(calls) == 1
        release.set()
        await settled(engine, 'one', two['id'])
        assert engine.get('one', one['id'])['result'] is None
        await engine.close()
    asyncio.run(scenario())


def test_ttl_cleanup_occurs_without_polling(payload):
    async def scenario():
        async def generate(p): return result(p)
        engine = PlanningJobEngine(generate, ttl_seconds=0.01, timeout_seconds=0.005)
        job = await engine.start('one', str(uuid4()), payload)
        await asyncio.sleep(0.025)
        internal = engine._jobs[job['id']]
        assert internal.status == 'expired' and internal.preferences is None and internal.result is None
        await engine.close()
    asyncio.run(scenario())
