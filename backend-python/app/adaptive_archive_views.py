"""Strict bounded account-archive projections, independent of checkpoint expiry."""
from copy import deepcopy
from datetime import date,datetime
import re
from uuid import UUID,uuid5
from .models import TripPreferences
from .adaptive_planning import cents,validate_strategy
from .adaptive_archive_snapshot import FORMAT,MAX_BYTES,MAX_SECTIONS,digest,integer,invalid
from .adaptive_archive_sources import validate_archive_sources
from .section_repository import validate_checkpoint
from .itineraries import ItineraryPayload,validate_itinerary,adaptive_travel_dates
from .supabase_clients import DatabaseError

MANIFEST_KEYS={'format','sourcePlanId','sourceVersion','sourceExpiresAt','preferences','journeyStrategy',
    'totalDays','sectionCount','sourceCount','spentCents','totalBudgetCents','currency','contentBytes','sectionsDigest','sourceDigest'}
CHUNK_KEYS={'sequence','sourceSequence','startDate','endDate','checkpoint','sourceHashes','sourceAssociation'}
HEX=re.compile(r'^[0-9a-f]{64}$')


def stamp(value):
    if type(value) is not str or len(value)>40:invalid()
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:invalid()
    return value


def title(value):
    if type(value) is not str or not value.strip() or len(value)>120 or any(ord(c)<32 or ord(c)==127 for c in value):invalid('SAVED_ADAPTIVE_INVALID_REQUEST',400)
    return value.strip()


def validate_manifest(value):
    try:
        if type(value) is not dict or set(value)!=MANIFEST_KEYS or value['format']!=FORMAT:invalid()
        UUID(value['sourcePlanId']);integer(value['sourceVersion'],1);stamp(value['sourceExpiresAt'])
        prefs=TripPreferences.model_validate(value['preferences']);validate_strategy(value['journeyStrategy'],prefs)
        days=(date.fromisoformat(prefs.endDate)-date.fromisoformat(prefs.startDate)).days+1
        if integer(value['totalDays'],1)!=days:invalid()
        count=integer(value['sectionCount'],1)
        if not (days+2)//3<=count<=min(days,MAX_SECTIONS):invalid()
        if integer(value['sourceCount'])>count or integer(value['contentBytes'])>MAX_BYTES:invalid()
        if integer(value['totalBudgetCents'])!=cents(prefs.budget) or integer(value['spentCents'])>value['totalBudgetCents'] or value['currency']!=prefs.currency:invalid()
        if any(type(value[k]) is not str or not HEX.fullmatch(value[k]) for k in ('sectionsDigest','sourceDigest')):invalid()
        if digest({k:v for k,v in value.items() if k!='sourceDigest'})!=value['sourceDigest']:invalid()
        return deepcopy(value)
    except DatabaseError:raise
    except Exception:invalid()


def summary(row):
    try:
        if row['status']!='complete':invalid('SAVED_ADAPTIVE_NOT_FOUND',404)
        m=validate_manifest(row['manifest']);prefs=m['preferences']
        return {'id':str(UUID(row['id'])),'requestId':str(UUID(row['requestId'])),'title':title(row['title']),
            'version':integer(row['version'],1),'createdAt':stamp(row['createdAt']),'updatedAt':stamp(row['updatedAt']),
            'format':FORMAT,'persisted':True,'sourcePlanId':m['sourcePlanId'],'sourceVersion':m['sourceVersion'],
            'totalDays':m['totalDays'],'sectionCount':m['sectionCount'],'spentCents':m['spentCents'],
            'totalBudgetCents':m['totalBudgetCents'],'currency':m['currency'],'startDate':prefs['startDate'],
            'endDate':prefs['endDate'],'destination':prefs['destination']}
    except DatabaseError:raise
    except Exception:invalid()


def save_status(row):
    try:
        m=validate_manifest(row['manifest']);status=row['status']
        if status not in {'staging','complete','expired'}:invalid()
        count=integer(row['savedSections'])
        if count>m['sectionCount'] or (status=='complete' and count!=m['sectionCount']):invalid()
        return {'requestId':str(UUID(row['requestId'])),'sourcePlanId':m['sourcePlanId'],
            'sourceVersion':m['sourceVersion'],'title':title(row['title']),'status':status,
            'persisted':status=='complete','savedId':str(UUID(row['id'])) if status=='complete' else None,
            'savedSections':count,'totalSections':m['sectionCount'],
            'stagingExpiresAt':stamp(row['stagingExpiresAt']) if status!='complete' else None,
            'saved':summary(row) if status=='complete' else None}
    except DatabaseError:raise
    except Exception:invalid()


def page(row,expected_id,after_sequence=0,*,now=None):
    try:
        meta=summary(row);m=validate_manifest(row['manifest']);prefs=TripPreferences.model_validate(m['preferences'])
        if meta['id']!=str(UUID(expected_id)) or integer(after_sequence)>m['sectionCount']:invalid()
        rows=row['sections'];source_rows=row['sources']
        if type(rows) is not list or len(rows)>3 or type(source_rows) is not list or len(source_rows)>3:invalid()
        sources={}
        for source in source_rows:
            if type(source) is not dict or set(source)!={'hash','data'} or not HEX.fullmatch(source['hash']):invalid()
            value=validate_archive_sources(source['data'],now=now)
            if digest(value)!=source['hash'] or source['hash'] in sources:invalid()
            sources[source['hash']]=value
        result=[];used=set();sequence=after_sequence;last_date=None;last_location=None
        for item in rows:
            if type(item) is not dict or set(item)!=CHUNK_KEYS|{'hash'}:invalid()
            chunk={k:v for k,v in item.items() if k!='hash'}
            if type(chunk) is not dict or set(chunk)!=CHUNK_KEYS or digest(chunk)!=item['hash']:invalid()
            if integer(chunk['sequence'],1)!=sequence+1 or integer(chunk['sourceSequence'],1)<chunk['sequence']:invalid()
            sequence+=1
            start,end=date.fromisoformat(chunk['startDate']),date.fromisoformat(chunk['endDate'])
            if not 0<=(end-start).days<3 or start<date.fromisoformat(prefs.startDate) or end>date.fromisoformat(prefs.endDate):invalid()
            if last_date is not None and start.toordinal()!=last_date.toordinal()+1:invalid()
            cp=chunk['checkpoint'];budget=cents(cp['itinerary']['estimatedTotalGroupCost'])+cents(cp['itinerary']['remainingBudget'])
            if not 0<budget<=m['totalBudgetCents']:invalid()
            section={'start_date':chunk['startDate'],'end_date':chunk['endDate'],'input_boundary':{'location':cp['startLocation']},
                'final_section':chunk['endDate']==prefs.endDate,'departure_city':prefs.departureCity,'budget_limit_cents':budget}
            validate_checkpoint(cp,section)
            if cp['journeyStrategy']!=m['journeyStrategy'] or (last_location is not None and cp['startLocation']!=last_location):invalid()
            sp=TripPreferences.model_validate({**prefs.model_dump(),'startDate':chunk['startDate'],'endDate':chunk['endDate'],'budget':budget/100})
            raw={k:v for k,v in cp['itinerary'].items() if k in ItineraryPayload.model_fields}
            validate_itinerary(raw,sp,'openai','gpt-6-luna',travel_day_dates=adaptive_travel_dates(prefs.startDate,prefs.endDate,m['journeyStrategy']))
            if sequence==1 and (chunk['startDate']!=prefs.startDate or cp['startLocation']!=prefs.departureCity):invalid()
            if sequence==m['sectionCount'] and (chunk['endDate']!=prefs.endDate or cp['endLocation']!=prefs.departureCity):invalid()
            hashes=chunk['sourceHashes'];association=chunk['sourceAssociation']
            if type(hashes) is not list or len(hashes)>1 or association not in {'none_recorded','linked_historical'}:invalid()
            if bool(hashes)!=(association=='linked_historical') or any(h not in sources for h in hashes):invalid()
            used.update(hashes)
            result.append({'id':str(uuid5(UUID(meta['id']),str(sequence))),'sequence':sequence,
                'startDate':chunk['startDate'],'endDate':chunk['endDate'],'checkpoint':deepcopy(cp),
                'sourceAssociation':association,'historicalSources':[deepcopy(sources[h]) for h in hashes]})
            last_date=end;last_location=cp['endLocation']
        expected=min(3,m['sectionCount']-after_sequence)
        if len(result)!=expected or used!=set(sources):invalid()
        cursor=sequence if sequence<m['sectionCount'] else None
        if row['nextCursor']!=cursor:invalid()
        return {'saved':meta,'preferences':prefs.model_dump(mode='json'),'journeyStrategy':deepcopy(m['journeyStrategy']),
            'sections':result,'nextCursor':cursor}
    except DatabaseError:raise
    except Exception:invalid()
