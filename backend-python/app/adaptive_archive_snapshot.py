"""Bounded owner-scoped complete snapshot preparation, without provider calls."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
from .models import TripPreferences
from .adaptive_planning import cents, validate_strategy
from .planning_repository import identity, JobRepositoryError
from .section_repository import validate_checkpoint, _bounded_json, PLAN_STORAGE_BYTES, SECTION_ROW_RESERVATION_BYTES
from .supabase_clients import DatabaseError

FORMAT='adaptive-sections-v1'
MAX_SECTIONS=1024
MAX_PAGES=32768
MAX_BYTES=16*1024*1024


def canonical(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def invalid(code='SAVED_ADAPTIVE_INVALID_SNAPSHOT',status=409):raise DatabaseError(status,code)


def integer(value,minimum=0):
    if type(value) is not int or not minimum<=value<=2**53-1:invalid()
    return value


@dataclass(frozen=True)
class ArchiveSnapshot:
    owner: str=field(repr=False)
    plan_id: str=field(repr=False)
    version: int
    manifest: dict=field(repr=False)


def _plan(plan,owner,plan_id,expected_version,now):
    if type(plan) is not dict or plan.get('id')!=plan_id or plan.get('user_id')!=owner:invalid('SAVED_ADAPTIVE_NOT_FOUND',404)
    if plan.get('status')!='completed':invalid('SAVED_ADAPTIVE_NOT_COMPLETE')
    if integer(plan.get('version'),1)!=expected_version:invalid('SAVED_ADAPTIVE_VERSION_CONFLICT')
    expiry=datetime.fromisoformat(plan['expires_at'].replace('Z','+00:00'))
    if expiry.tzinfo is None or expiry<=now:invalid('SAVED_ADAPTIVE_SOURCE_EXPIRED',410)
    prefs=TripPreferences.model_validate(plan['preferences'])
    days=(date.fromisoformat(prefs.endDate)-date.fromisoformat(prefs.startDate)).days+1
    if integer(plan['completed_days'],1)!=days or integer(plan['total_budget_cents'])!=cents(prefs.budget):invalid()
    if integer(plan['spent_cents'])>plan['total_budget_cents']:invalid()
    route=validate_strategy(plan['journey_strategy'],prefs)
    return prefs,route,days


async def archive_chunks(repository,research_repository,owner,plan,*,now=None,
        after_sequence=0,section_offset=0,covered_days=0,spent_cents=0,last_location=None):
    """Yield complete accepted sections, retaining one three-row page.

    A partial iteration is not a successful save; finalization must verify the
    prepared manifest's complete totals and ordered hash over every chunk.
    """
    now=now or datetime.now(timezone.utc)
    owner=identity(owner);plan_id=identity(plan['id'])
    prefs,route,total_days=_plan(plan,owner,plan_id,plan['version'],now)
    cursor=integer(after_sequence);covered=integer(covered_days);spent=integer(spent_cents);sections=integer(section_offset)
    pages=read_bytes=0
    if covered>total_days or spent>plan['spent_cents'] or sections>MAX_SECTIONS:invalid()
    if bool(cursor)!=bool(sections) or bool(covered)!=bool(sections):invalid()
    last_location=prefs.departureCity if not sections else last_location
    if type(last_location) is not str or not last_location:invalid()
    while covered<total_days:
        pages+=1
        if pages>MAX_PAGES:invalid('SAVED_ADAPTIVE_TOO_LARGE',413)
        rows=await repository.list_sections(owner,plan_id,after_sequence=cursor,limit=3)
        if type(rows) is not list or not 1<=len(rows)<=3:invalid()
        for row in rows:
            if covered==total_days:invalid()
            if type(row) is not dict or row.get('user_id')!=owner or row.get('plan_id')!=plan_id:invalid()
            identity(row['id']);sequence=integer(row['sequence'],1)
            if sequence<=cursor:invalid()
            cursor=sequence
            read_bytes+=SECTION_ROW_RESERVATION_BYTES+len(_bounded_json(row,524288))
            if read_bytes>PLAN_STORAGE_BYTES:invalid('SAVED_ADAPTIVE_TOO_LARGE',413)
            if row.get('status') not in {'succeeded','failed','cancelled'}:invalid()
            if row['status']!='succeeded':continue
            cp=deepcopy(validate_checkpoint(row['checkpoint'],row))
            if cp['journeyStrategy']!=route or cp['itinerary']['currency']!=prefs.currency:invalid()
            if cp['startLocation']!=last_location:invalid()
            days=cp['itinerary']['days']
            if not 1<=len(days)<=3 or len(days)>total_days-covered:invalid()
            for day in days:
                if day['date']!=date.fromordinal(date.fromisoformat(prefs.startDate).toordinal()+covered).isoformat():invalid()
                covered+=1
            last_location=cp['endLocation'];spent+=cp['spentCents'];sections+=1
            if sections>MAX_SECTIONS or spent>plan['spent_cents']:invalid('SAVED_ADAPTIVE_TOO_LARGE',413)
            sources=[];association='none_recorded'
            if row.get('research_source_id'):
                if research_repository is None:invalid('SAVED_ADAPTIVE_SOURCES_UNAVAILABLE',503)
                job=await research_repository.get(owner,identity(row['research_source_id']))
                from .adaptive_archive_sources import project_archive_sources
                notes=project_archive_sources(owner,row,job,now=now)
                if notes is None:invalid()
                sources=[{'hash':digest(notes),'data':notes}];association='linked_historical'
            chunk={'sequence':sections,'sourceSequence':sequence,'startDate':row['start_date'],'endDate':row['end_date'],
                'checkpoint':cp,'sourceHashes':[s['hash'] for s in sources],'sourceAssociation':association}
            yield chunk,sources
    if covered!=total_days or spent!=plan['spent_cents'] or last_location!=prefs.departureCity:invalid()


async def prepare_archive(repository,research_repository,owner,plan_id,expected_version,*,now=None):
    owner,plan_id=identity(owner),identity(plan_id);integer(expected_version,1)
    now=now or datetime.now(timezone.utc)
    try:
        plan=await repository.get_plan(owner,plan_id)
        prefs,route,total_days=_plan(plan,owner,plan_id,expected_version,now)
        rolling=hashlib.sha256();sections=total_bytes=0;source_keys=set()
        async for chunk,sources in archive_chunks(repository,research_repository,owner,plan,now=now):
            encoded=canonical(chunk);rolling.update(hashlib.sha256(encoded).digest());sections+=1;total_bytes+=len(encoded)
            for source in sources:
                if source['hash'] not in source_keys:
                    source_keys.add(source['hash']);total_bytes+=len(canonical(source['data']))
            if total_bytes>MAX_BYTES:invalid('SAVED_ADAPTIVE_TOO_LARGE',413)
        manifest={'format':FORMAT,'sourcePlanId':plan_id,'sourceVersion':expected_version,
            'sourceExpiresAt':plan['expires_at'],
            'preferences':prefs.model_dump(mode='json'),'journeyStrategy':route,'totalDays':total_days,
            'sectionCount':sections,'sourceCount':len(source_keys),'spentCents':plan['spent_cents'],
            'totalBudgetCents':plan['total_budget_cents'],'currency':prefs.currency,
            'contentBytes':total_bytes,'sectionsDigest':rolling.hexdigest()}
        manifest['sourceDigest']=digest(manifest)
        if total_bytes+len(canonical(manifest))>MAX_BYTES:invalid('SAVED_ADAPTIVE_TOO_LARGE',413)
        current=await repository.get_plan(owner,plan_id)
        _plan(current,owner,plan_id,expected_version,now)
        if any(current.get(k)!=plan.get(k) for k in ('preferences','journey_strategy','spent_cents','total_budget_cents','completed_days','expires_at')):invalid('SAVED_ADAPTIVE_VERSION_CONFLICT')
        return ArchiveSnapshot(owner,plan_id,expected_version,manifest)
    except DatabaseError:raise
    except JobRepositoryError as error:
        if error.code=='SECTION_NOT_FOUND_OR_CONFLICT':invalid('SAVED_ADAPTIVE_SOURCE_EXPIRED',410)
        invalid('SAVED_ADAPTIVE_SOURCE_UNAVAILABLE',503)
    except Exception:invalid()
