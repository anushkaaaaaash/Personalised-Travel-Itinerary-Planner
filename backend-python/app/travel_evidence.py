"""Offline evidence evaluator. Not wired into production; no network/model calls.

Only server-owned adapters may supply trusted_records and accepted_providers.
Never deserialize model output or user input into these trusted arguments.
Verified means fresh source observation, not guaranteed future conditions.
"""
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

class StrictRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)

class EvidenceScope(StrictRecord):
    destinationId: str
    localDate: date
    timeZone: str
    kind: Literal['opening_hours', 'closure', 'route', 'weather', 'transit', 'booking']
    subjectId: str

    @field_validator('destinationId', 'subjectId')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Exact destination and subject are required.')
        return value

    @field_validator('timeZone')
    @classmethod
    def timezone(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('Use an IANA time zone.') from None
        return value

class TrustedEvidence(StrictRecord):
    providerId: str
    scope: EvidenceScope
    sourceURL: str
    checkedAt: datetime
    expiresAt: datetime
    validFrom: date
    validUntil: date
    outcome: Literal['clear', 'blocked', 'caution', 'unavailable']
    summary: str
    fallback: str

    @field_validator('sourceURL')
    @classmethod
    def source(cls, value):
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('HTTPS source URL without credentials required.')
        return value

    @field_validator('providerId', 'summary', 'fallback')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Nonblank evidence text required.')
        return value

    @model_validator(mode='after')
    def bounds(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.checkedAt, self.expiresAt)):
            raise ValueError('Timestamps must include UTC offset.')
        if self.expiresAt <= self.checkedAt or self.validUntil < self.validFrom:
            raise ValueError('Invalid validity bounds.')
        return self

class EvidenceAssessment(StrictRecord):
    scope: EvidenceScope
    status: Literal['verified', 'unverified', 'stale', 'unavailable']
    severity: Literal['unknown', 'none', 'caution', 'blocker']
    summary: str
    fallback: str
    sourceURL: str | None = None
    checkedAt: datetime | None = None
    expiresAt: datetime | None = None
    validFrom: date | None = None
    validUntil: date | None = None

FALLBACKS = {
    'opening_hours': 'Check official opening hours before setting a visit time.',
    'closure': 'Check official venue notices and keep a nearby alternative.',
    'route': 'Check this journey and leave extra transfer time.',
    'weather': 'Keep an indoor alternative and check the forecast closer to departure.',
    'transit': 'Check the transport operator’s service updates before departure.',
    'booking': 'Check availability directly before committing to this time.',
}

def evaluate_evidence(scopes: tuple[EvidenceScope, ...], *,
                      trusted_records: tuple[TrustedEvidence, ...] = (),
                      accepted_providers: frozenset[str] = frozenset(),
                      now: datetime) -> tuple[EvidenceAssessment, ...]:
    """Match exact scopes. Missing coverage never means clear. No generated status
    input is accepted. Fresh contradictory observations favor the stricter one.
    """
    if now.tzinfo is None or now.utcoffset() is None: raise ValueError('now must be timezone-aware')
    results = []
    priority = {'blocked': 3, 'caution': 2, 'clear': 1, 'unavailable': 0}
    for scope in scopes:
        candidates = [r for r in trusted_records if r.providerId in accepted_providers
            and r.scope == scope and r.checkedAt <= now and r.validFrom <= scope.localDate <= r.validUntil]
        fresh = [r for r in candidates if now < r.expiresAt]
        if not candidates:
            results.append(EvidenceAssessment(scope=scope, status='unverified', severity='unknown',
                summary='Current information has not been checked for this part of the trip.', fallback=FALLBACKS[scope.kind]))
            continue
        record = max(fresh, key=lambda r: (priority[r.outcome], r.checkedAt)) if fresh else max(candidates, key=lambda r: r.checkedAt)
        metadata = {k: getattr(record, k) for k in ('sourceURL', 'checkedAt', 'expiresAt', 'validFrom', 'validUntil')}
        if not fresh:
            status, severity, summary = 'stale', 'unknown', 'This information needs a fresh check.'
        elif record.outcome == 'unavailable':
            status, severity, summary = 'unavailable', 'unknown', 'Current information is unavailable.'
        else:
            status, severity, summary = 'verified', {'blocked':'blocker', 'caution':'caution', 'clear':'none'}[record.outcome], record.summary
        results.append(EvidenceAssessment(scope=scope, status=status, severity=severity, summary=summary,
            fallback=record.fallback if status == 'verified' else FALLBACKS[scope.kind], **metadata))
    return tuple(results)
