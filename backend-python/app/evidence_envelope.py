"""Server-owned evidence bound to one exact itinerary, never imported/saved claims."""
import hashlib
import json
import struct
from datetime import datetime, timezone
from .travel_evidence import EvidenceAssessment, TrustedEvidence


def itinerary_digest(value):
    def normalize(item):
        if item is None:return ['null']
        if isinstance(item,bool):return ['bool',item]
        if isinstance(item,(int,float)):return ['number',struct.pack('>d',float(item)).hex()]
        if isinstance(item,str):return ['string',item]
        if isinstance(item,dict):return ['object',[[key,normalize(item[key])] for key in sorted(item)]]
        if isinstance(item,list):return ['array',[normalize(v) for v in item]]
        raise ValueError('Unsupported itinerary value.')
    encoded=json.dumps(normalize(value),separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_evidence_envelope(itinerary, report):
    checks=[item.model_dump(mode='json') for item in report.checks if item.status!='unverified']
    if not checks:return None
    scopes={(item['scope']['destinationId'],item['scope']['timeZone']) for item in checks}
    if len(scopes)!=1:raise ValueError('Evidence destination scope is inconsistent.')
    destination,time_zone=next(iter(scopes))
    value={'version':1,'destinationId':destination,'timeZone':time_zone,
           'itineraryDigest':itinerary_digest(itinerary),'assessments':checks}
    return validate_evidence_envelope(value,itinerary)


def validate_evidence_envelope(value,itinerary,*,now=None):
    if value is None:return None
    now=now or datetime.now(timezone.utc)
    if (type(value) is not dict or set(value)!={'version','destinationId','timeZone','itineraryDigest','assessments'}
        or value['version']!=1 or value['itineraryDigest']!=itinerary_digest(itinerary)
        or not isinstance(value['assessments'],list) or len(value['assessments'])>448):
        raise ValueError('Evidence binding is invalid.')
    scopes={(day['date'],activity['id']) for day in itinerary['days'] for activity in day['activities']}
    checks=[]
    for raw in value['assessments']:
        item=EvidenceAssessment.model_validate_json(json.dumps(raw,allow_nan=False))
        if (item.scope.destinationId!=value['destinationId'] or item.scope.timeZone!=value['timeZone']
            or (item.scope.localDate.isoformat(),item.scope.subjectId) not in scopes):
            raise ValueError('Evidence does not apply to this itinerary.')
        if item.sourceURL is not None:
            TrustedEvidence.source(item.sourceURL)
        if item.status=='verified':
            if (item.checkedAt is None or item.expiresAt is None or item.sourceURL is None
                or item.checkedAt>now or item.validFrom is None or item.validUntil is None
                or not item.validFrom<=item.scope.localDate<=item.validUntil):
                raise ValueError('Evidence provenance is incomplete.')
            if item.expiresAt<=now:
                item=item.model_copy(update={'status':'stale','severity':'unknown','summary':'This information needs a fresh check.'})
        checks.append(item.model_dump(mode='json'))
    return {**value,'assessments':checks}
