"""Bounded historical observations, never fresh evidence or authenticity proof."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
import json
from .adaptive_research import PublicResearchQuery,validate_research_pack
from .planning_repository import JobRepositoryError,identity

KEYS={'receivedAt','expiresAt','text','sources','citations','applicability','evidenceStatus'}


def _invalid():raise JobRepositoryError('ARCHIVE_SOURCES_INVALID',422)


def _receipt(value,now):
    if type(value) is not str or len(value)>40:_invalid()
    receipt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if receipt.tzinfo is None or receipt.utcoffset() is None:_invalid()
    clock=now if now is not None else datetime.now(timezone.utc)
    if not isinstance(clock,datetime) or clock.tzinfo is None or clock.utcoffset() is None or receipt>clock:_invalid()
    return receipt


def validate_archive_sources(notes,*,now=None):
    """Validate historical shape and linkage, without asserting facts or freshness."""
    try:
        if type(notes) is not dict or set(notes)!=KEYS:_invalid()
        if len(json.dumps(notes,ensure_ascii=False,allow_nan=False).encode())>65536:_invalid()
        if notes['applicability']!='unknown' or notes['evidenceStatus']!='historical_unverified':_invalid()
        receipt=_receipt(notes['receivedAt'],now)
        # A non-exported neutral DTO reuses URL/span/source validation. It never
        # represents an actual search and never escapes this validator.
        query=PublicResearchQuery('Historical archive','2000-01-01','2000-01-01')
        pack={'query':asdict(query),'checked_at':notes['receivedAt'],'expires_at':notes['expiresAt'],
            'tool_calls':1,'text':notes['text'],'sources':notes['sources'],'citations':notes['citations'],
            'applicability':'unknown','evidence_status':'model_observations_and_inference_unverified'}
        validate_research_pack(pack,query=query,phase='initial',now=receipt)
        return deepcopy(notes)
    except JobRepositoryError:raise
    except Exception:_invalid()


def project_archive_sources(owner,section,research_row,*,now=None):
    """Require the accepted section's exact owner/plan/job binding; never latest."""
    try:
        owner=identity(owner)
        if type(section) is not dict or section.get('user_id')!=owner or section.get('status')!='succeeded':_invalid()
        plan_id=identity(section['plan_id'])
        linked=section.get('research_source_id')
        if linked is None:return None
        linked=identity(linked)
        if (type(research_row) is not dict or research_row.get('id')!=linked
            or research_row.get('user_id')!=owner or research_row.get('plan_id')!=plan_id
            or research_row.get('status')!='succeeded' or research_row.get('phase') not in {'initial','refresh'}):_invalid()
        pack=research_row['sourcepack'];receipt=_receipt(pack['checked_at'],now)
        pack=validate_research_pack(pack,query=research_row['query'],phase=research_row['phase'],now=receipt)
        notes={'receivedAt':pack['checked_at'],'expiresAt':pack['expires_at'],'text':pack['text'],
            'sources':pack['sources'],'citations':pack['citations'],'applicability':'unknown','evidenceStatus':'historical_unverified'}
        return validate_archive_sources(notes,now=now)
    except JobRepositoryError as error:
        if error.code=='ARCHIVE_SOURCES_INVALID':raise
        _invalid()
    except Exception:_invalid()
