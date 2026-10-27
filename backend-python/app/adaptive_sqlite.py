"""Single-machine durable adaptive queue. Explicit local provisioning only.

All RPCs run in one BEGIN IMMEDIATE transaction on a fresh connection. No SQL,
paths, identities or provider errors are logged. No retry after commit ambiguity.
Not a replicated queue: copying/restoring an old database requires operator
quarantine before enabling workers; this module never restores snapshots.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from contextlib import closing
import sqlite3
import time
from uuid import uuid4, UUID

from .planning_repository import JobRepositoryError, identity
from .section_repository import (_bounded_json, _cents, _limit, validate_checkpoint,
    GLOBAL_STORAGE_BYTES, PLAN_STORAGE_BYTES, proposed_constraint_retryable)

_SCHEMA = """
CREATE TABLE plans(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,request_id TEXT NOT NULL,
 data TEXT NOT NULL CHECK(json_valid(data)), UNIQUE(user_id,request_id),UNIQUE(id,user_id));
CREATE TABLE sections(id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,user_id TEXT NOT NULL,
 request_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>0),
 data TEXT NOT NULL CHECK(json_valid(data)),UNIQUE(plan_id,request_id),UNIQUE(plan_id,sequence),
 FOREIGN KEY(plan_id,user_id) REFERENCES plans(id,user_id) ON DELETE CASCADE);
CREATE TABLE controls(plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL,allowance INTEGER NOT NULL CHECK(allowance BETWEEN 1 AND 12),
 PRIMARY KEY(plan_id,request_id));
CREATE TABLE runtime(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,last_purge REAL);
INSERT INTO runtime VALUES(1,1,NULL);
PRAGMA user_version=1;
"""
_ARGS = {
 'create_plan': {'owner','request_id','preferences','input_hash','budget_cents','run_allowance'},
 'find_current': {'owner'}, 'find_request': {'owner','request_id'}, 'get_plan': {'owner','plan'},
 'get_section': {'owner','section'}, 'list_sections': {'owner','plan','after_sequence','page_size'},
 'recent_checkpoints': {'owner','plan'}, 'next_section': {'owner','plan','request_id','section_days'},
 'claim_section': {'owner','section','worker'}, 'claim_next': {'worker'},
 'transition_section': {'owner','section','lease','expected_version','next_status','response_id','failure_code','checkpoint','failure_details'},
 'retry_section': {'owner','section','request_id','section_days'},
 'continue_run': {'owner','plan','request_id','run_allowance'}, 'cancel_plan': {'owner','plan'},
 'purge_expired': set(), 'checkpoint_health': set(),
}

def _stamp(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat()

def _time(value):
    return datetime.fromisoformat(value).timestamp() if value else 0

def _json(value):
    return _bounded_json(value,524288).decode()

def _error(code='SECTION_REQUEST_CONFLICT', status=409):
    raise JobRepositoryError(code,status) from None

def _rollback(conn):
    if conn:
        try: conn.rollback()
        except sqlite3.Error: pass


class AdaptiveSQLiteGateway:
    schema_version = 1
    elevated = True
    supports_proposed_constraint_retry = True
    supports_owner_recovery = True

    def __init__(self, path, *, enabled=False, initialize=False, clock=None):
        if enabled is not True: _error('SECTIONS_DISABLED',503)
        self.path = Path(path)
        if not self.path.is_absolute() or str(path)==':memory:' or self.path.is_symlink():
            _error('SECTIONS_STORAGE_PATH_INVALID',503)
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self.closed = False
        # Caller authorizes first provisioning. Missing stores never auto-recreate.
        if initialize:
            try:
                fd = self.path.open('xb'); fd.close()
                self.path.chmod(0o600)
                with closing(self._connect()) as conn:
                    conn.executescript(_SCHEMA)
            except Exception:
                _error('SECTIONS_STORAGE_PROVISION_FAILED',503)
        try:
            self._identity = self.path.stat().st_dev, self.path.stat().st_ino
            with closing(self._connect()) as conn:
                if conn.execute('PRAGMA user_version').fetchone()[0]!=self.schema_version:
                    _error('SECTIONS_SCHEMA_NOT_READY',503)
                if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    _error('SECTIONS_SCHEMA_NOT_READY',503)
        except JobRepositoryError: raise
        except Exception: _error('SECTIONS_STORAGE_UNAVAILABLE',503)

    def _connect(self):
        # mode=rw is critical: a missing volume/store must not become an empty queue.
        conn = sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':
            conn.close(); _error('SECTIONS_SCHEMA_NOT_READY',503)
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA secure_delete=ON')
        deadline=time.monotonic()+5
        conn.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
        return conn

    async def close(self):
        self.closed=True

    async def purge_expired(self):
        return await self.request('POST','rpc/adaptive_purge_expired',payload={})

    async def request(self,method,resource,params=None,payload=None):
        op=resource.removeprefix('rpc/adaptive_') if isinstance(resource,str) else ''
        if method!='POST' or resource!='rpc/adaptive_'+op or op not in _ARGS or params or type(payload) is not dict or set(payload)!=_ARGS[op]:
            _error('SECTION_OPERATION_INVALID',400)
        _bounded_json(payload,262144)
        for key in {'owner','plan','section','request_id','worker','lease'} & payload.keys():
            identity(payload[key])
        return await asyncio.to_thread(self._execute,op,payload)

    def _execute(self,op,a):
        conn=None
        try:
            if self.closed or self.path.is_symlink() or (self.path.stat().st_dev,self.path.stat().st_ino)!=self._identity:
                _error('SECTIONS_STORAGE_UNAVAILABLE',503)
            conn=self._connect();conn.execute('BEGIN IMMEDIATE')
            result=self._dispatch(conn,op,a,self.clock())
            _bounded_json(result,524288)
            conn.commit()
            if op=='purge_expired':
                # Erase deleted payload pages from WAL before marking cleanup fresh.
                if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:
                    _error('SECTIONS_CLEANUP_UNCONFIRMED',503)
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('UPDATE runtime SET last_purge=? WHERE id=1',(self.clock(),))
                conn.commit()
            return result
        except JobRepositoryError:
            _rollback(conn)
            raise
        except Exception:
            _rollback(conn)
            _error('SECTION_STORAGE_UNCONFIRMED',503)
        finally:
            if conn: conn.close()

    @staticmethod
    def _rows(c,table,where='',args=()):
        # table and SQL clauses are exclusively compile-time strings below.
        return [json.loads(r[0]) for r in c.execute('SELECT data FROM '+table+' '+where,args)]

    def _one(self,c,table,id,owner,now):
        rows=self._rows(c,table,'WHERE id=? AND user_id=?',(id,owner))
        if not rows: return None
        row=rows[0]
        p=row if table=='plans' else self._one(c,'plans',row['plan_id'],owner,now)
        return row if p and _time(p['expires_at'])>now else None

    @staticmethod
    def _save(c,table,row):
        row['version']+=1
        c.execute('UPDATE '+table+' SET data=? WHERE id=? AND user_id=?',(_json(row),row['id'],row['user_id']))

    def _allocated(self,c):
        return c.execute("SELECT (SELECT COALESCE(SUM(json_extract(data,'$.storage_used_bytes')),0) FROM plans)+(SELECT COALESCE(SUM(json_extract(data,'$.reserved_checkpoint_bytes')),0) FROM sections)").fetchone()[0]

    def _paid_work_count(self,c,now):
        return c.execute("SELECT COUNT(*) FROM sections WHERE json_extract(data,'$.status') IN ('submitting','running') OR (json_extract(data,'$.status')='queued' AND json_extract(data,'$.lease_until')>?) OR (json_extract(data,'$.status') IN ('submission_unknown','cancelled','failed') AND json_extract(data,'$.submitted_at')>?)",(_stamp(now),_stamp(now-600))).fetchone()[0]

    def _dispatch(self,c,op,a,now):
        if op=='checkpoint_health':
            r=c.execute('SELECT version,last_purge FROM runtime WHERE id=1').fetchone()
            return [{'schema_version':r['version'],'rpc_version':1,'cleanup_fresh':bool(r['last_purge'] is not None and 0<=now-r['last_purge']<180)}]
        if op=='purge_expired':
            ids=[r[0] for r in c.execute("SELECT id FROM plans WHERE json_extract(data,'$.expires_at')<=?",(_stamp(now),))]
            c.executemany('DELETE FROM plans WHERE id=?',[(i,) for i in ids])
            c.execute('UPDATE runtime SET last_purge=NULL WHERE id=1')
            return len(ids)
        if op=='create_plan': return self._create(c,a,now)
        if op=='claim_next':
            ready=self._rows(c,'plans',"WHERE json_extract(data,'$.status')='active' AND json_extract(data,'$.expires_at')>? AND json_extract(data,'$.active_section') IS NULL AND json_extract(data,'$.next_date') IS NOT NULL AND json_extract(data,'$.remaining_creates')>0 ORDER BY json_extract(data,'$.created_at') LIMIT 3",(_stamp(now),))
            for p in ready:
                self._next(c,dict(owner=p['user_id'],plan=p['id'],request_id=str(UUID(hashlib.md5((p['id']+':'+p['next_date']).encode()).hexdigest())),section_days=3),now)
            rows=self._rows(c,'sections',"WHERE json_extract(data,'$.status') IN ('queued','running','submitting') AND COALESCE(json_extract(data,'$.lease_until'),'')<=? AND plan_id IN (SELECT id FROM plans WHERE json_extract(data,'$.status')='active' AND json_extract(data,'$.expires_at')>?) ORDER BY (json_extract(data,'$.status')='running') DESC,json_extract(data,'$.created_at') LIMIT 3",(_stamp(now),_stamp(now)))
            for s in rows:
                claimed=self._claim(c,dict(owner=s['user_id'],section=s['id'],worker=a['worker']),now)
                if claimed:return claimed
            return []
        owner=a['owner']
        if op=='find_current':
            rows=self._rows(c,'plans',"WHERE user_id=? AND json_extract(data,'$.status') IN ('active','paused') AND json_extract(data,'$.expires_at')>? LIMIT 2",(owner,_stamp(now)))
            if len(rows)>1:_error('SECTION_OWNER_RECOVERY_CONFLICT',503)
            return rows
        if op=='find_request':
            return [p for p in self._rows(c,'plans','WHERE user_id=? AND request_id=?',(owner,a['request_id'])) if _time(p['expires_at'])>now]
        if op in ('get_plan','get_section'):
            r=self._one(c,'plans' if op=='get_plan' else 'sections',a['plan'] if op=='get_plan' else a['section'],owner,now)
            return [r] if r else []
        if op in ('list_sections','recent_checkpoints'):
            if not self._one(c,'plans',a['plan'],owner,now):return []
            if op=='recent_checkpoints': return self._rows(c,'sections',"WHERE plan_id=? AND user_id=? AND json_extract(data,'$.status')='succeeded' ORDER BY sequence DESC LIMIT 3",(a['plan'],owner))
            _limit(a['page_size'],3)
            if type(a['after_sequence']) is not int or a['after_sequence']<0:_error('SECTION_CURSOR_INVALID',400)
            return self._rows(c,'sections','WHERE plan_id=? AND user_id=? AND sequence>? ORDER BY sequence LIMIT ?',(a['plan'],owner,a['after_sequence'],a['page_size']))
        if op=='next_section':return self._next(c,a,now)
        if op=='claim_section':return self._claim(c,a,now)
        if op=='transition_section':return self._transition(c,a,now)
        if op=='retry_section':
            s=self._one(c,'sections',a['section'],owner,now)
            if not s:return []
            p=self._one(c,'plans',s['plan_id'],owner,now)
            prior=self._rows(c,'sections','WHERE plan_id=? AND request_id=?',(p['id'],a['request_id']))
            if prior:
                if prior[0]['retry_of']!=s['id'] or prior[0]['requested_days']!=a['section_days']:_error()
                return prior
            if s['status']!='failed' or p['active_section']!=s['id'] or p['status'] not in ('active','paused') or not p['remaining_creates']:return []
            if s['error_code']=='SECTION_BUDGET_EXHAUSTED':return []
            if s['error_code']=='SECTION_CONSTRAINT_CONFLICT' and not proposed_constraint_retryable(s):return []
            p.update(status='active',pause_reason=None,active_section=None);self._save(c,'plans',p)
            rows=self._next(c,dict(owner=owner,plan=p['id'],request_id=a['request_id'],section_days=a['section_days']),now)
            if rows: rows[0]['retry_of']=s['id'];self._save(c,'sections',rows[0])
            return rows
        p=self._one(c,'plans',a['plan'],owner,now)
        if not p:return []
        if op=='continue_run': return self._continue(c,p,a,now)
        if op=='cancel_plan':
            for s in self._rows(c,'sections',"WHERE plan_id=? AND user_id=? AND json_extract(data,'$.status')!='succeeded'",(p['id'],owner)):
                if s['status']!='succeeded':
                    s.update(status='cancelled',reserved_checkpoint_bytes=0,lease_token=None,lease_until=None);self._save(c,'sections',s)
            if p['status']=='completed':return []
            p.update(status='cancelled',pause_reason=None);self._save(c,'plans',p);return [p]
        _error('SECTION_OPERATION_INVALID',400)

    def _create(self,c,a,now):
        from .models import TripPreferences
        prefs=TripPreferences.model_validate(a['preferences']).model_dump(mode='json')
        encoded=_bounded_json(prefs,16384)
        allowance=_limit(a['run_allowance'],12)
        budget=_cents(prefs['budget'])
        if budget<=0 or type(a['budget_cents']) is not int or a['budget_cents']!=budget or a['input_hash']!=hashlib.sha256(encoded).hexdigest():_error('SECTION_PREFERENCES_INVALID',400)
        prior=self._rows(c,'plans','WHERE user_id=? AND request_id=?',(a['owner'],a['request_id']))
        if prior:
            if prior[0]['input_hash']!=a['input_hash'] or prior[0]['initial_run_allowance']!=allowance:_error()
            if _time(prior[0]['expires_at'])<=now:return []
            return prior
        active=c.execute("SELECT COUNT(*),COALESCE(SUM(user_id=?),0) FROM plans WHERE json_extract(data,'$.status') IN ('active','paused') AND json_extract(data,'$.expires_at')>?",(a['owner'],_stamp(now))).fetchone()
        if active[1]:_error('SECTION_OWNER_PLAN_EXISTS',429)
        if active[0]>=50 or self._allocated(c)+49152>GLOBAL_STORAGE_BYTES:_error('SECTION_CAPACITY_LIMIT',429)
        p=dict(id=str(uuid4()),user_id=a['owner'],request_id=a['request_id'],input_hash=a['input_hash'],preferences=prefs,
          start_date=prefs['startDate'],end_date=prefs['endDate'],next_date=prefs['startDate'],total_budget_cents=budget,spent_cents=0,completed_days=0,
          storage_limit_bytes=PLAN_STORAGE_BYTES,storage_used_bytes=49152,global_storage_limit_bytes=GLOBAL_STORAGE_BYTES,
          previous_boundary=dict(location=prefs['departureCity'],lastActivityEnd=None),journey_strategy=None,status='active',pause_reason=None,storage_pause_scope=None,
          active_section=None,remaining_creates=allowance,initial_run_allowance=allowance,version=1,created_at=_stamp(now),expires_at=_stamp(now+86400))
        c.execute('INSERT INTO plans VALUES(?,?,?,?)',(p['id'],p['user_id'],p['request_id'],_json(p)));return [p]

    def _next(self,c,a,now):
        days=_limit(a['section_days'],3)
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        if not p:return []
        prior=self._rows(c,'sections','WHERE plan_id=? AND request_id=?',(p['id'],a['request_id']))
        if prior:
            if prior[0]['requested_days']!=days:_error()
            return prior
        if p['status']!='active' or p['active_section'] or not p['remaining_creates'] or not p['next_date']:return []
        scope='plan' if p['storage_used_bytes']+147456>p['storage_limit_bytes'] else 'global' if self._allocated(c)+147456>GLOBAL_STORAGE_BYTES else None
        if scope:
            p.update(status='paused',pause_reason='STORAGE_LIMIT',storage_pause_scope=scope);self._save(c,'plans',p);return []
        start=date.fromisoformat(p['next_date']);end=start+timedelta(days=min(days-1,(date.fromisoformat(p['end_date'])-start).days))
        sequence=c.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM sections WHERE plan_id=?',(p['id'],)).fetchone()[0]
        s=dict(id=str(uuid4()),plan_id=p['id'],user_id=p['user_id'],request_id=a['request_id'],sequence=sequence,requested_days=days,retry_of=None,
          start_date=start.isoformat(),end_date=end.isoformat(),budget_limit_cents=p['total_budget_cents']-p['spent_cents'],input_boundary=p['previous_boundary'],
          final_section=end.isoformat()==p['end_date'],departure_city=p['preferences']['departureCity'],status='queued',version=1,lease_token=None,lease_until=None,worker_id=None,
          submitted_at=None,provider_response_id=None,reserved_checkpoint_bytes=131072,error_code=None,failure_details=None,checkpoint=None,created_at=_stamp(now))
        c.execute('INSERT INTO sections VALUES(?,?,?,?,?,?)',(s['id'],p['id'],p['user_id'],a['request_id'],sequence,_json(s)))
        p.update(active_section=s['id'],storage_used_bytes=p['storage_used_bytes']+16384);self._save(c,'plans',p);return [s]

    def _claim(self,c,a,now):
        s=self._one(c,'sections',a['section'],a['owner'],now)
        if not s:return []
        p=self._one(c,'plans',s['plan_id'],a['owner'],now)
        if p['status']!='active':return []
        if s['status']=='submitting' and _time(s['lease_until'])<=now:
            s.update(status='submission_unknown',reserved_checkpoint_bytes=0,error_code='SUBMISSION_UNKNOWN',lease_token=None,lease_until=None);self._save(c,'sections',s)
            p.update(status='paused',pause_reason='SUBMISSION_UNKNOWN');self._save(c,'plans',p);return []
        if s['status'] not in ('queued','running') or _time(s['lease_until'])>now:return []
        active=self._paid_work_count(c,now)
        if s['status']=='queued' and active>=2:return []
        s.update(lease_token=str(uuid4()),lease_until=_stamp(now+60),worker_id=a['worker']);self._save(c,'sections',s);return [s]

    def _transition(self,c,a,now):
        s=self._one(c,'sections',a['section'],a['owner'],now)
        if not s:return []
        p=self._one(c,'plans',s['plan_id'],a['owner'],now);status=a['next_status'];cp=a['checkpoint']
        if p['status']!='active' or p['active_section']!=s['id'] or type(a['expected_version']) is not int or s['version']!=a['expected_version'] or s['lease_token']!=a['lease'] or _time(s['lease_until'])<=now:return []
        allowed={'queued':{'submitting','failed'},'submitting':{'running','failed','submission_unknown'},'running':{'running','succeeded','failed'}}
        if status not in allowed.get(s['status'],set()):return []
        response=a['response_id'] if a['response_id'] is not None else s['provider_response_id']
        if response is not None and (not isinstance(response,str) or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}',response)):_error('SECTION_TRANSITION_INVALID',400)
        if status=='running' and not response:_error('SECTION_TRANSITION_INVALID',400)
        if s['provider_response_id'] and response!=s['provider_response_id']:_error()
        if (status=='succeeded')!=(cp is not None):_error('SECTION_CHECKPOINT_INVALID',400)
        code=a['failure_code']
        if code is not None and (not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code)):_error('SECTION_TRANSITION_INVALID',400)
        details=a['failure_details']
        if details is not None:
            if status!='failed' or code!='SECTION_CONSTRAINT_CONFLICT' or type(details) is not dict or set(details)!={'applicability','explanation','recommendations'} or details['applicability']!='proposed' or not isinstance(details['explanation'],str) or not 1<=len(details['explanation'])<=500 or type(details['recommendations']) is not list or not 1<=len(details['recommendations'])<=3:_error('SECTION_FAILURE_DETAILS_INVALID',400)
            for r in details['recommendations']:
                if type(r) is not dict or set(r)!={'field','reason','suggestion'} or any(type(v) is not str or not 1<=len(v)<=500 for v in r.values()):_error('SECTION_FAILURE_DETAILS_INVALID',400)
            _bounded_json(details,8192)
        if status=='succeeded':self._accept(c,p,s,cp)
        elif status=='submitting':
            if not p['remaining_creates']:return []
            p['remaining_creates']-=1
        elif status in ('failed','submission_unknown'):
            p.update(status='paused',pause_reason='SECTION_FAILED' if status=='failed' else 'SUBMISSION_UNKNOWN')
        self._save(c,'plans',p)
        s.update(status=status,provider_response_id=response,error_code=code,failure_details=details,checkpoint=cp,
          reserved_checkpoint_bytes=0 if status in ('succeeded','failed','submission_unknown') else s['reserved_checkpoint_bytes'],
          submitted_at=_stamp(now) if status=='submitting' else s['submitted_at'],lease_token=s['lease_token'] if status=='submitting' else None,lease_until=_stamp(now+60) if status=='submitting' else None)
        self._save(c,'sections',s);return [s]

    def _accept(self,c,p,s,cp):
        validate_checkpoint(cp,s)
        # Pydantic coercion must not admit wire strings/bools as money.
        categories={'accommodation','meals','localTransport','activities','departureTravel'}
        for day in cp['itinerary']['days']:
            costs=day['costs']
            if set(costs)!=categories or any(type(v) not in (int,float) for v in costs.values()):
                _error('SECTION_CHECKPOINT_INVALID',400)
        strategy=cp['journeyStrategy'];stays=strategy['stays']
        if stays[0]['startDate']!=p['start_date'] or stays[-1]['endDate']!=p['end_date'] or (p['journey_strategy'] is not None and p['journey_strategy']!=strategy):_error('SECTION_CHECKPOINT_INVALID',400)
        location=next((r['location'] for r in stays if r['startDate']<=s['end_date']<=r['endDate']),None)
        if not s['final_section'] and location!=cp['endLocation']:_error('SECTION_CHECKPOINT_INVALID',400)
        titles={a['title'].strip().lower() for d in cp['itinerary']['days'] for a in d['activities'] if a['kind']=='main'}
        # Stream only normalized principal titles, never prior checkpoint blobs.
        for row in c.execute("SELECT json_extract(activity.value,'$.title') FROM sections s,json_each(s.data,'$.checkpoint.itinerary.days') day,json_each(day.value,'$.activities') activity WHERE s.plan_id=? AND json_extract(s.data,'$.status')='succeeded' AND json_extract(activity.value,'$.kind')='main'",(p['id'],)):
            if row[0].strip().lower() in titles:_error('SECTION_CHECKPOINT_INVALID',400)
        last=cp['itinerary']['days'][-1]['activities'][-1];h,m=map(int,last['startTime'].split(':'));end=h*60+m+last['durationMinutes']
        if not 0<=end<=1440:_error('SECTION_CHECKPOINT_INVALID',400)
        size=len(_bounded_json(cp))
        if p['storage_used_bytes']+size>p['storage_limit_bytes']:_error('SECTION_RESOURCE_LIMIT',413)
        p.update(spent_cents=p['spent_cents']+cp['spentCents'],completed_days=p['completed_days']+len(cp['itinerary']['days']),
          storage_used_bytes=p['storage_used_bytes']+size,journey_strategy=strategy,next_date=None if s['final_section'] else (date.fromisoformat(s['end_date'])+timedelta(days=1)).isoformat(),
          previous_boundary={'location':cp['endLocation'],'lastActivityEnd':f'{end//60:02}:{end%60:02}'},active_section=None,
          status='completed' if s['final_section'] else 'paused' if not p['remaining_creates'] else 'active',
          pause_reason='RESOURCE_ALLOWANCE_REACHED' if not s['final_section'] and not p['remaining_creates'] else None)

    def _continue(self,c,p,a,now):
        allowance=_limit(a['run_allowance'],12)
        prior=c.execute('SELECT allowance FROM controls WHERE plan_id=? AND request_id=?',(p['id'],a['request_id'])).fetchone()
        if prior:
            if prior[0]!=allowance:_error()
            return [p]
        if p['status']!='paused':return []
        failed=self._one(c,'sections',p['active_section'],p['user_id'],now) if p['active_section'] else None
        if failed and failed['error_code'] in ('SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED'):return []
        storage=p['pause_reason']=='STORAGE_LIMIT' and p['storage_pause_scope']=='global'
        if not storage and not (p['pause_reason'] in ('RESOURCE_ALLOWANCE_REACHED','SECTION_FAILED') and not p['remaining_creates']):return []
        needed=512+(147456 if storage else 0)
        if p['storage_used_bytes']+needed>p['storage_limit_bytes']:
            p.update(pause_reason='STORAGE_LIMIT',storage_pause_scope='plan');self._save(c,'plans',p);return [p]
        if self._allocated(c)+needed>GLOBAL_STORAGE_BYTES:return [p]
        c.execute('INSERT INTO controls VALUES(?,?,?)',(p['id'],a['request_id'],allowance))
        p.update(remaining_creates=p['remaining_creates'] if storage and p['remaining_creates']>0 else allowance,
          storage_used_bytes=p['storage_used_bytes']+512,status='active',pause_reason=None,storage_pause_scope=None)
        self._save(c,'plans',p);return [p]
