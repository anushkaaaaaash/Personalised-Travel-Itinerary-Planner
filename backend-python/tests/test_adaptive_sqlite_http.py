"""Same accepted durable HTTP contracts against real local SQLite files."""
import asyncio
from app.adaptive_sqlite import AdaptiveSQLiteGateway
from test_adaptive_integration import (test_sql_checkpoint_survives_later_failure_and_explicit_retry as checkpoint_case,
    test_sql_cancellation_wins_late_completed_provider_response as cancellation_case,
    test_actual_sql_constraint_failure_reaches_edit_recommendations_without_retry as advice_case)
import pytest

@pytest.fixture
def database(tmp_path):
    gateway=AdaptiveSQLiteGateway(tmp_path/'planning.sqlite3',enabled=True,initialize=True)
    asyncio.run(gateway.purge_expired())
    yield gateway
    asyncio.run(gateway.close())

def test_accepted_checkpoint_survives_retry(monkeypatch,payload,database):checkpoint_case(monkeypatch,payload,database)
def test_cancel_prevents_late_result(monkeypatch,payload,database):cancellation_case(monkeypatch,payload,database)
def test_actual_sqlite_failure_advice_reaches_frontend(payload,database):advice_case(database,payload)
