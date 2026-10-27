import json
import logging
from app.adaptive_worker import _timing


def test_timing_has_closed_fields_and_bounds(caplog):
    with caplog.at_level(logging.INFO, logger='uvicorn.error'):
        _timing('create_ack', 1.25, status='queued')
        _timing('provider_wait', 999999, status='PRIVATE output')
        _timing('validation', -1)
        _timing('PRIVATE prompt', 10)
        _timing('validation', float('nan'))
        _timing('validation', 'SECRET')
        _timing([], 1)
    values = [json.loads(r.message.split(': ', 1)[1]) for r in caplog.records]
    assert values == [
        {'phase':'create_ack','elapsed_ms':1250,'status':'queued'},
        {'phase':'provider_wait','elapsed_ms':86400000},
        {'phase':'validation','elapsed_ms':0}]
    assert 'PRIVATE' not in caplog.text and 'SECRET' not in caplog.text


def test_timing_never_interrupts_paid_result_persistence(monkeypatch):
    import app.adaptive_worker as worker
    def broken(*args, **kwargs): raise RuntimeError('PRIVATE logging failure')
    monkeypatch.setattr(worker._logger, 'info', broken)
    worker._timing('create_ack', 1.0, status='queued')
    worker._timing('provider_wait', 1e308, status='completed')
    worker._timing('provider_wait', 10 ** 1000, status='completed')
