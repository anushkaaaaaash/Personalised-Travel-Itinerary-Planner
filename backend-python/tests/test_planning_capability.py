import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.planning_coordinator import DurablePlanningCoordinator
from app.planning_repository import JobRepositoryError

class Auth:
    def configured(self):return True
class Repository:
    healthy=True
    async def verify_ready(self):
        if not self.healthy:raise JobRepositoryError('JOB_SCHEMA_NOT_READY')
class Worker:
    async def tick(self):return None

def test_default_disabled_and_no_lifespan_is_not_ready():
    assert TestClient(create_app(auth_service=Auth())).get('/api/auth/config').json()['planning_jobs_enabled'] is False

def test_capability_is_cached_durable_health_and_failure_is_closed(monkeypatch):
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true');monkeypatch.setenv('APP_MODE','local')
    repo=Repository();coordinator=DurablePlanningCoordinator(repo,Worker(),enabled=True,require_health=True)
    with TestClient(create_app(auth_service=Auth(),planning_engine=coordinator)) as browser:
        assert browser.get('/api/auth/config').json()['planning_jobs_enabled'] is True
        coordinator._ready_checked-=16
        assert browser.get('/api/auth/config').json()['planning_jobs_enabled'] is False
        browser.portal.call(coordinator.verify_ready)
        assert browser.get('/api/auth/config').json()['planning_jobs_enabled'] is True
        repo.healthy=False
        with pytest.raises(JobRepositoryError):browser.portal.call(coordinator.verify_ready)
        assert browser.get('/api/auth/config').json()['planning_jobs_enabled'] is False

def test_failed_cleanup_stops_startup_not_only_ui(monkeypatch):
    monkeypatch.setenv('PLANNING_JOBS_PREVIEW','true');monkeypatch.setenv('APP_MODE','local')
    repo=Repository();repo.healthy=False
    coordinator=DurablePlanningCoordinator(repo,Worker(),enabled=True,require_health=True)
    with pytest.raises(JobRepositoryError):
        with TestClient(create_app(auth_service=Auth(),planning_engine=coordinator)):pass
