"""Bounded AI deadlines and closed-vocabulary timing diagnostics. No retries."""
import asyncio
import json
import logging
import math
import time

AI_SERVICE_TIMEOUT_SECONDS = 190
AI_READ_TIMEOUT_SECONDS = 180
AI_CONNECT_TIMEOUT_SECONDS = 10
AI_WRITE_TIMEOUT_SECONDS = 45
AI_POOL_TIMEOUT_SECONDS = 45


class ProviderTransportTimeout(TimeoutError):
    """Transport already logged a safe diagnostic; do not relabel as total deadline."""


def timeout_diagnostic(event, subtype, stage, elapsed_seconds):
    """Never serialize exception text, request content, headers, or provider output."""
    if type(event) is not str or event not in {'TRANSPORT_TIMEOUT', 'SERVICE_TIMEOUT'}:
        return
    if type(subtype) is not str or subtype not in {'READ', 'CONNECT', 'WRITE', 'POOL', 'OTHER', 'TOTAL'}:
        return
    if type(stage) is not str or stage not in {'WAIT_RESPONSE', 'READ_RESPONSE_BODY', 'READ_ERROR_BODY', 'PROVIDER_CALL'}:
        return
    if type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds):
        return
    diagnostic = {'event': event, 'timeoutType': subtype, 'stage': stage,
                  'elapsedMs': int(min(3600, max(0, elapsed_seconds)) * 1000)}
    logging.getLogger(__name__).warning('AI provider diagnostic: %s', json.dumps(diagnostic))


async def wait_for_provider(awaitable, timeout_seconds):
    started = time.monotonic()
    deadline = asyncio.timeout(timeout_seconds)
    try:
        async with deadline:
            return await awaitable
    except ProviderTransportTimeout:
        raise
    except TimeoutError:
        if deadline.expired():
            timeout_diagnostic('SERVICE_TIMEOUT', 'TOTAL', 'PROVIDER_CALL', time.monotonic() - started)
        raise
