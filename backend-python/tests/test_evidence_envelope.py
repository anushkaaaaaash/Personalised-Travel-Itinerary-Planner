from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
import pytest
from app.evidence_envelope import build_evidence_envelope,validate_evidence_envelope,itinerary_digest
from app.travel_evidence import EvidenceScope,TrustedEvidence
from app.travel_feasibility import TravelConstraint,assess_feasibility

def fixture():
    now=datetime.now(timezone.utc)
    plan={'days':[{'date':'2028-01-01','activities':[{'id':'museum','title':'Museum','startTime':'10:00','durationMinutes':60}]}]}
    record=TrustedEvidence(providerId='official',scope=EvidenceScope(destinationId='city-id',localDate=date(2028,1,1),timeZone='UTC',kind='closure',subjectId='museum'),
        sourceURL='https://official.example/notices',checkedAt=now-timedelta(minutes=1),expiresAt=now+timedelta(hours=1),
        validFrom=date(2028,1,1),validUntil=date(2028,1,1),outcome='clear',summary='Official venue notice checked.',fallback='Check again before leaving.')
    report=assess_feasibility(plan,destination_id='city-id',time_zone='UTC',constraints=(TravelConstraint(evidence=record,rule='closure'),),accepted_providers=frozenset({'official'}),now=now)
    return now,plan,build_evidence_envelope(plan,report)

def test_envelope_binds_exact_itinerary_and_scope():
    now,plan,envelope=fixture()
    assert validate_evidence_envelope(envelope,plan,now=now)['assessments'][0]['status']=='verified'
    for change in [lambda p:p['days'][0].update(date='2028-01-02'),lambda p:p['days'][0]['activities'][0].update(title='Different venue'),lambda p:p['days'][0]['activities'][0].update(startTime='12:00')]:
        edited=deepcopy(plan);change(edited)
        with pytest.raises(ValueError):validate_evidence_envelope(envelope,edited)
    altered=deepcopy(envelope);altered['assessments'][0]['scope']['subjectId']='another'
    with pytest.raises(ValueError):validate_evidence_envelope(altered,plan)

def test_expiry_downgrades_and_numeric_digest_matches_javascript():
    now,plan,envelope=fixture()
    assert validate_evidence_envelope(envelope,plan,now=now+timedelta(hours=2))['assessments'][0]['status']=='stale'
    assert itinerary_digest({'x':1.0,'é':'✓'})==itinerary_digest({'é':'✓','x':1})

def test_saved_schema_does_not_accept_verified_claims(payload):
    from app.saved_itineraries import Document
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Document.model_validate({'title':'Trip','preferences':payload,'itinerary':{},'evidence':{'status':'verified'}})

def test_digest_matches_browser_for_float_edge_cases():
    import json, subprocess
    from pathlib import Path
    value={'small':1e-7,'large':1e20,'negativeZero':-0.0,'decimal':0.1,'unicode':'京都 ✓','nested':[1,True,None]}
    module=(Path(__file__).resolve().parents[2]/'frontend/src/services/planningJobs.js').as_uri()
    script=f"import {{itineraryEvidenceDigest}} from {json.dumps(module)}; console.log(await itineraryEvidenceDigest({json.dumps(value,ensure_ascii=False)}));"
    # Repo root is two levels above backend-python/tests.
    module=(Path(__file__).resolve().parents[2]/'frontend/src/services/planningJobs.js').as_uri()
    result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,check=True)
    assert result.stdout.strip()==itinerary_digest(value)
