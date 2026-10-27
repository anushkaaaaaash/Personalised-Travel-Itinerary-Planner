from datetime import date, datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from app.travel_evidence import EvidenceScope, TrustedEvidence, evaluate_evidence
NOW = datetime(2026,10,27,5,tzinfo=timezone.utc)
SCOPE = EvidenceScope(destinationId='paris-fr', localDate=date(2026,10,27), timeZone='Europe/Paris', kind='closure', subjectId='louvre')
def record(**changes):
    return TrustedEvidence(**dict(dict(providerId='official', scope=SCOPE, sourceURL='https://www.louvre.fr/en/visit/hours-admission',
        checkedAt=NOW-timedelta(hours=1), expiresAt=NOW+timedelta(hours=1), validFrom=SCOPE.localDate, validUntil=SCOPE.localDate,
        outcome='blocked', summary='Closed on Tuesday.', fallback='Choose another day.'), **changes))
def evaluate(records=(), scope=SCOPE):
    return evaluate_evidence((scope,), trusted_records=records, accepted_providers=frozenset({'official'}), now=NOW)[0]
def test_missing_coverage_unknown():
    r=evaluate(); assert r.status=='unverified' and r.severity=='unknown' and r.sourceURL is None
def test_fresh_blocker():
    r=evaluate((record(),)); assert r.status=='verified' and r.severity=='blocker' and r.fallback=='Choose another day.'
@pytest.mark.parametrize('change',[dict(providerId='model'),dict(checkedAt=NOW+timedelta(minutes=1)),dict(validFrom=date(2026,10,25),validUntil=date(2026,10,26))])
def test_bad_provenance_or_window(change):
    assert evaluate((record(**change),)).status=='unverified'
@pytest.mark.parametrize('change',[dict(destinationId='paris-us'),dict(localDate=date(2026,10,28)),dict(timeZone='UTC'),dict(subjectId='other'),dict(kind='booking')])
def test_exact_scope(change):
    assert evaluate((record(),),EvidenceScope(**dict(SCOPE.model_dump(),**change))).status=='unverified'
def test_stale_not_blocker():
    r=evaluate((record(expiresAt=NOW),)); assert r.status=='stale' and r.severity=='unknown' and r.summary!='Closed on Tuesday.'
def test_unavailable_not_clear():
    r=evaluate((record(outcome='unavailable'),)); assert r.status=='unavailable' and r.severity=='unknown'
def test_conflicting_blocker_wins():
    assert evaluate((record(),record(outcome='clear',checkedAt=NOW))).severity=='blocker'
def test_default_trust_empty():
    assert evaluate_evidence((SCOPE,),trusted_records=(record(),),now=NOW)[0].status=='unverified'
@pytest.mark.parametrize('change',[dict(sourceURL='http://example.com'),dict(sourceURL='https://user:pass@example.com'),dict(checkedAt=NOW.replace(tzinfo=None)),dict(expiresAt=NOW-timedelta(hours=2)),dict(status='verified')])
def test_invalid_record(change):
    with pytest.raises(ValidationError): record(**change)
def test_invalid_timezone():
    with pytest.raises(ValidationError): EvidenceScope(**dict(SCOPE.model_dump(),timeZone='bad/zone'))
