"""Pure optional feasibility gate over server-trusted source constraints.

No replacement activity, booking, route, or opening window is invented here.
Only fresh, exact-scope observations can reject a plan. Unknown coverage is
returned for display and must not be marketed as a verified itinerary.
"""
from datetime import date, datetime
import re
from typing import Literal
from pydantic import field_validator, model_validator
from .travel_evidence import StrictRecord, TrustedEvidence, EvidenceScope, EvidenceAssessment, evaluate_evidence


def minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use local HH:MM time.')
    h, m = map(int, value.split(':'))
    return h * 60 + m


class TravelConstraint(StrictRecord):
    evidence: TrustedEvidence
    rule: Literal['closure', 'visit_window', 'minimum_gap', 'fixed_booking', 'booking_required']
    opensAt: str | None = None
    closesAt: str | None = None
    lastEntry: str | None = None
    minimumGapMinutes: int | None = None
    fixedStart: str | None = None

    @field_validator('opensAt', 'closesAt', 'lastEntry', 'fixedStart')
    @classmethod
    def clock(cls, value):
        if value is not None: minutes(value)
        return value

    @model_validator(mode='after')
    def fields(self):
        expected = {'closure':'closure', 'visit_window':'opening_hours', 'minimum_gap':'route',
                    'fixed_booking':'booking', 'booking_required':'booking'}
        if self.evidence.scope.kind != expected[self.rule]: raise ValueError('Constraint kind mismatch.')
        if self.rule == 'visit_window':
            if self.opensAt is None or self.closesAt is None or minutes(self.opensAt) >= minutes(self.closesAt):
                raise ValueError('A same-local-day opening window is required.')
            if self.lastEntry is not None and not minutes(self.opensAt) <= minutes(self.lastEntry) <= minutes(self.closesAt):
                raise ValueError('Last entry must be inside opening window.')
        if self.rule == 'minimum_gap' and (self.minimumGapMinutes is None or self.minimumGapMinutes < 0):
            raise ValueError('Nonnegative travel/rest gap required.')
        if self.rule == 'fixed_booking' and self.fixedStart is None: raise ValueError('Confirmed booking time required.')
        return self


class FeasibilityIssue(StrictRecord):
    activityId: str
    date: str
    code: str
    message: str
    fallback: str
    sourceURL: str


class FeasibilityReport(StrictRecord):
    feasible: bool
    blockers: tuple[FeasibilityIssue, ...]
    checks: tuple[EvidenceAssessment, ...]


class FeasibilityConflict(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('The proposed schedule conflicts with checked travel constraints.')


def raise_on_blockers(report):
    if not report.feasible: raise FeasibilityConflict(report)
    return report


def assess_feasibility(plan: dict, *, destination_id: str, time_zone: str,
                       constraints: tuple[TravelConstraint, ...] = (),
                       accepted_providers: frozenset[str] = frozenset(),
                       now: datetime) -> FeasibilityReport:
    blockers, checks = [], []
    for day in plan.get('days', []):
        local_date = date.fromisoformat(day['date'])
        activities = sorted(day.get('activities', []), key=lambda a: minutes(a['startTime']))
        previous_end = None
        for activity in activities:
            start = minutes(activity['startTime'])
            end = start + activity['durationMinutes']
            matching = [c for c in constraints if c.evidence.scope.destinationId == destination_id
                and c.evidence.scope.timeZone == time_zone and c.evidence.scope.localDate == local_date
                and c.evidence.scope.subjectId == activity['id']]
            for kind in ('closure', 'opening_hours', 'route', 'booking'):
                scope = EvidenceScope(destinationId=destination_id, localDate=local_date,
                    timeZone=time_zone, kind=kind, subjectId=activity['id'])
                records = tuple(c.evidence for c in matching if c.evidence.scope.kind == kind)
                checks.extend(evaluate_evidence((scope,), trusted_records=records,
                    accepted_providers=accepted_providers, now=now))
            for constraint in matching:
                evidence = constraint.evidence
                assessment = evaluate_evidence((evidence.scope,), trusted_records=(evidence,),
                    accepted_providers=accepted_providers, now=now)[0]
                if assessment.status != 'verified': continue
                code = None
                if constraint.rule == 'closure' and evidence.outcome == 'blocked': code = 'VENUE_CLOSED'
                elif constraint.rule == 'visit_window':
                    if start < minutes(constraint.opensAt) or end > minutes(constraint.closesAt): code = 'VISIT_OUTSIDE_HOURS'
                    elif constraint.lastEntry and start > minutes(constraint.lastEntry): code = 'LAST_ENTRY_MISSED'
                elif constraint.rule == 'minimum_gap' and previous_end is not None:
                    if start - previous_end < constraint.minimumGapMinutes: code = 'TRANSFER_BUFFER_TOO_SHORT'
                elif constraint.rule == 'fixed_booking' and start != minutes(constraint.fixedStart): code = 'FIXED_BOOKING_CONFLICT'
                # A reservation requirement alone never establishes ticket inventory or a booking.
                if code:
                    blockers.append(FeasibilityIssue(activityId=activity['id'], date=day['date'], code=code,
                        message=evidence.summary, fallback=evidence.fallback, sourceURL=evidence.sourceURL))
            previous_end = end
    return FeasibilityReport(feasible=not blockers, blockers=tuple(blockers), checks=tuple(checks))


def build_feasibility_gate(*, constraints=(), accepted_providers=frozenset(), now,
                           destination_id: str, time_zone: str):
    """Adapter for worker callable(plan, preferences); IDs/timezone are server-owned.

    now may be an aware datetime or an injected clock callable. In production use
    a clock callable so cached gates cannot freeze evidence freshness.
    """
    def gate(plan, preferences):
        return raise_on_blockers(assess_feasibility(plan, destination_id=destination_id,
            time_zone=time_zone, constraints=constraints, accepted_providers=accepted_providers,
            now=now() if callable(now) else now))
    return gate
