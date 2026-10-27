"""Explicit schema-v2 research queue sharing the section queue's paid-work budget.

No network, credentials, automatic migrations or provider retries. Existing v1
plans remain legacy. Research reservations are never refunded after submission.
"""
import asyncio
from datetime import datetime,timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4,uuid5,NAMESPACE_URL
from .section_preview_store import SectionPreviewMixin
from .adaptive_sqlite import AdaptiveSQLiteGateway, _stamp, _time, _error, _json
from .planning_repository import JobRepositoryError, identity
from .section_repository import _bounded_json, _limit, GLOBAL_STORAGE_BYTES

RESEARCH_ROW_BYTES = 16384
RESEARCH_PACK_BYTES = 65536
RESEARCH_ARGS = {
 'reserve': {'owner','plan','request_id','phase','query'},
 'get': {'owner','research'}, 'latest': {'owner','plan'},
 'claim_next': {'worker'},
 'transition': {'owner','research','lease','expected_version','next_status','response_id','failure_code','sourcepack'},
 'health': set(),
 'request_research': {'owner','section','lease','expected_version','kind'},
 'continue_researched': {'owner','plan'},
}
_RESEARCH_SCHEMA = """CREATE TABLE research_jobs(
 id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,user_id TEXT NOT NULL,request_id TEXT NOT NULL,
 run_index INTEGER NOT NULL CHECK(run_index>=1),phase TEXT NOT NULL CHECK(phase IN ('initial','refresh')),
 data TEXT NOT NULL CHECK(json_valid(data)),UNIQUE(plan_id,request_id),UNIQUE(plan_id,run_index,phase),
 FOREIGN KEY(plan_id,user_id) REFERENCES plans(id,user_id) ON DELETE CASCADE);
CREATE INDEX research_jobs_plan_owner ON research_jobs(plan_id,user_id);
"""


def upgrade_research_schema(path, *, approved=False):
    """Operator-only, atomic v1→v2; reject active work, never initialize a store."""
    if approved is not True: _error('RESEARCH_MIGRATION_NOT_APPROVED',403)
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file(): _error('SECTIONS_STORAGE_UNAVAILABLE',503)
    c=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=5)
    try:
        c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
        version=c.execute('PRAGMA user_version').fetchone()[0]
        if version==2:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='research_jobs' AND type='table'").fetchone(): _error('RESEARCH_SCHEMA_NOT_READY',503)
            c.commit();return
        if version!=1: _error('RESEARCH_SCHEMA_NOT_READY',503)
        for table,statuses in (('plans',('active','paused','completed','cancelled')),('sections',('queued','submitting','running','succeeded','failed','submission_unknown','cancelled'))):
            placeholders=','.join('?' for _ in statuses)
            if c.execute("SELECT COUNT(*) FROM "+table+" WHERE json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ("+placeholders+")",statuses).fetchone()[0]:_error('RESEARCH_SCHEMA_NOT_READY',503)
        if c.execute("SELECT COUNT(*) FROM plans WHERE json_extract(data,'$.status')='active'").fetchone()[0]: _error('PLANNING_IN_PROGRESS',409)
        if c.execute("SELECT COUNT(*) FROM sections WHERE json_extract(data,'$.status') IN ('queued','submitting','running')").fetchone()[0]: _error('PLANNING_IN_PROGRESS',409)
        for statement in _RESEARCH_SCHEMA.split(';'):
            if statement.strip():c.execute(statement)
        c.execute('PRAGMA user_version=2')
        c.execute('UPDATE runtime SET version=2,last_purge=NULL WHERE id=1')
        c.commit()
    except JobRepositoryError:
        c.rollback();raise
    except Exception:
        c.rollback();_error('RESEARCH_MIGRATION_UNCONFIRMED',503)
    finally:c.close()


class ResearchSQLiteGateway(SectionPreviewMixin, AdaptiveSQLiteGateway):
    schema_version=2
    supports_research=True

    def __init__(self,*args,research_enabled=False,**kwargs):
        if kwargs.get('initialize'): _error('RESEARCH_EXPLICIT_MIGRATION_REQUIRED',503)
        self.research_enabled=research_enabled is True
        super().__init__(*args,**kwargs)

    async def research_request(self,operation,payload):
        if operation not in RESEARCH_ARGS or type(payload) is not dict or set(payload)!=RESEARCH_ARGS[operation]: _error('RESEARCH_OPERATION_INVALID',400)
        _bounded_json(payload,131072)
        for key in {'owner','plan','research','section','request_id','worker','lease'} & payload.keys():identity(payload[key])
        return await asyncio.to_thread(self._execute,'research_'+operation,payload)

    def _allocated(self,c):
        return super()._allocated(c)+c.execute("SELECT COALESCE(SUM(json_extract(data,'$.reserved_sourcepack_bytes')),0) FROM research_jobs").fetchone()[0]

    def _paid_work_count(self,c,now):
        completed_triggers=c.execute("SELECT COUNT(*) FROM sections WHERE json_extract(data,'$.status')='failed' AND json_extract(data,'$.error_code')='SECTION_RESEARCH_REQUESTED' AND json_extract(data,'$.provider_response_id') IS NOT NULL AND json_extract(data,'$.submitted_at')>?",(_stamp(now-600),)).fetchone()[0]
        return super()._paid_work_count(c,now)-completed_triggers+c.execute("SELECT COUNT(*) FROM research_jobs WHERE json_extract(data,'$.status') IN ('submitting','running') OR (json_extract(data,'$.status')='queued' AND json_extract(data,'$.lease_until')>?) OR (json_extract(data,'$.status') IN ('submission_unknown','cancelled','failed') AND json_extract(data,'$.submitted_at')>?)",(_stamp(now),_stamp(now-600))).fetchone()[0]

    def _create(self,c,a,now):
        prior=c.execute('SELECT 1 FROM plans WHERE user_id=? AND request_id=?',(a['owner'],a['request_id'])).fetchone()
        rows=super()._create(c,a,now)
        if rows and not prior and self.research_enabled:
            p=rows[0];p.update(research_on_demand=True,research_latest=None,active_research=None,research_trigger=None,run_index=1,tool_calls_reserved=0)
            self._save(c,'plans',p)
        return rows

    def _next(self,c,a,now):
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        if p and (p.get('active_research') or p.get('research_trigger')):return []
        if p and p.get('research_required') and not p.get('research_latest'):return []
        rows=super()._next(c,a,now)
        if rows and p and p.get('research_latest'):
            s=rows[0]
            # A section permanently records the exact sourcepack used; later
            # refreshes cannot rewrite an accepted section's evidence context.
            if 'research_source_id' not in s:
                s['research_source_id']=p['research_latest'];self._save(c,'sections',s)
        return rows

    def _continue(self,c,p,a,now):
        before=p['remaining_creates'];index=p.get('run_index',1)
        if (p.get('research_required') or p.get('research_on_demand')) and p['status']=='paused' and p.get('pause_reason')=='RESEARCH_ALLOWANCE_REACHED':
            allowance=_limit(a['run_allowance'],12)
            prior=c.execute('SELECT allowance FROM controls WHERE plan_id=? AND request_id=?',(p['id'],a['request_id'])).fetchone()
            if prior:
                if prior[0]!=allowance:_error()
                return [p]
            if p['storage_used_bytes']+512>p['storage_limit_bytes'] or self._allocated(c)+512>GLOBAL_STORAGE_BYTES:return [p]
            c.execute('INSERT INTO controls VALUES(?,?,?)',(p['id'],a['request_id'],allowance))
            p.update(remaining_creates=allowance,run_index=index+1,tool_calls_reserved=0,storage_used_bytes=p['storage_used_bytes']+512,status='active',pause_reason=None)
            self._save(c,'plans',p);return [p]
        existed=c.execute('SELECT 1 FROM controls WHERE plan_id=? AND request_id=?',(p['id'],a['request_id'])).fetchone()
        rows=super()._continue(c,p,a,now)
        if rows and not existed and before==0 and rows[0]['remaining_creates']>0 and (p.get('research_required') or p.get('research_on_demand')):
            p=rows[0];p.update(run_index=index+1,tool_calls_reserved=0);self._save(c,'plans',p)
        return rows

    def _dispatch(self,c,op,a,now):
        if op.startswith('research_'):return self._research_dispatch(c,op[9:],a,now)
        if op=='retry_section':
            section=self._one(c,'sections',a['section'],a['owner'],now)
            if section and section.get('error_code')=='SECTION_RESEARCH_REQUESTED':return []
        if op=='cancel_plan':
            p=self._one(c,'plans',a['plan'],a['owner'],now)
            if p and p['status']!='completed':
                for j in self._rows(c,'research_jobs',"WHERE plan_id=? AND user_id=? AND json_extract(data,'$.status')!='succeeded'",(p['id'],p['user_id'])):
                    j.update(status='cancelled',lease_token=None,lease_until=None,reserved_sourcepack_bytes=0);self._save(c,'research_jobs',j)
        prior_plan=None
        if self.research_enabled and op in ('retry_section','continue_run'):
            plan_id=a.get('plan')
            if op=='retry_section':
                old_section=self._one(c,'sections',a['section'],a['owner'],now)
                plan_id=old_section['plan_id'] if old_section else None
            prior_plan=self._one(c,'plans',plan_id,a['owner'],now) if plan_id else None
        rows=super()._dispatch(c,op,a,now)
        if rows and prior_plan and not prior_plan.get('research_on_demand') and not prior_plan.get('research_required'):
            p=self._one(c,'plans',prior_plan['id'],a['owner'],now)
            confirmed=(op=='retry_section' and rows[0].get('status')=='queued' and p.get('active_section')==rows[0]['id']) or (op=='continue_run' and prior_plan['status']=='paused' and p['status']=='active')
            if confirmed:
                p.update(research_on_demand=True,research_latest=None,active_research=None,research_trigger=None,run_index=1,tool_calls_reserved=0)
                self._save(c,'plans',p)
                if op=='continue_run':rows=[p]
        return rows

    def _research_dispatch(self,c,op,a,now):
        if op=='health':
            r=c.execute('SELECT version,last_purge FROM runtime WHERE id=1').fetchone()
            return [{'schema_version':r['version'],'research_version':1,'cleanup_fresh':bool(r['last_purge'] is not None and 0<=now-r['last_purge']<180)}]
        if op=='reserve':return self._reserve(c,a,now)
        if op=='request_research':return self._request_research(c,a,now)
        if op=='continue_researched':return self._continue_researched(c,a,now)
        if op=='get':
            j=self._one(c,'research_jobs',a['research'],a['owner'],now);return [j] if j else []
        if op=='latest':
            p=self._one(c,'plans',a['plan'],a['owner'],now)
            j=self._one(c,'research_jobs',p['research_latest'],a['owner'],now) if p and p.get('research_latest') else None
            return [j] if j and j['status']=='succeeded' else []
        if op=='claim_next':
            # Only a persisted, validated model trigger permits research work.
            ready=self._rows(c,'plans',"WHERE json_extract(data,'$.status')='active' AND json_extract(data,'$.research_on_demand')=1 AND json_extract(data,'$.research_trigger') IS NOT NULL AND json_extract(data,'$.expires_at')>? ORDER BY json_extract(data,'$.created_at') LIMIT 3",(_stamp(now),))
            for plan in ready:
                self._ensure_triggered(c,plan,now)
            rows=self._rows(c,'research_jobs',"WHERE json_extract(data,'$.status') IN ('queued','submitting','running') AND COALESCE(json_extract(data,'$.lease_until'),'')<=? AND plan_id IN (SELECT id FROM plans WHERE json_extract(data,'$.status')='active' AND json_extract(data,'$.expires_at')>?) ORDER BY (json_extract(data,'$.status')='running') DESC,json_extract(data,'$.created_at') LIMIT 3",(_stamp(now),_stamp(now)))
            for j in rows:
                p=self._one(c,'plans',j['plan_id'],j['user_id'],now)
                if p.get('active_research')!=j['id']:continue
                if j['status']=='submitting':
                    j.update(status='submission_unknown',error_code='RESEARCH_SUBMISSION_UNCONFIRMED',lease_token=None,lease_until=None,reserved_sourcepack_bytes=0);self._save(c,'research_jobs',j)
                    p.update(status='paused',pause_reason='RESEARCH_SUBMISSION_UNKNOWN');self._save(c,'plans',p);continue
                if j['status']=='queued' and self._paid_work_count(c,now)>=2:continue
                j.update(lease_token=str(uuid4()),lease_until=_stamp(now+60),worker_id=a['worker']);self._save(c,'research_jobs',j);return [j]
            return []
        if op=='transition':return self._research_transition(c,a,now)
        _error('RESEARCH_OPERATION_INVALID',400)

    def _request_research(self,c,a,now):
        if a['kind'] not in ('places','hours','transport','bookings','closures'):_error('RESEARCH_TOPIC_INVALID',400)
        s=self._one(c,'sections',a['section'],a['owner'],now)
        if not s:return []
        p=self._one(c,'plans',s['plan_id'],a['owner'],now)
        if not p or not p.get('research_on_demand') or p['status']!='active' or p['active_section']!=s['id'] or s['status']!='running' or not s.get('provider_response_id') or type(a['expected_version']) is not int or s['version']!=a['expected_version'] or s['lease_token']!=a['lease'] or _time(s['lease_until'])<=now:return []
        s.update(status='failed',error_code='SECTION_RESEARCH_REQUESTED',failure_details=None,lease_token=None,lease_until=None,reserved_checkpoint_bytes=0)
        self._save(c,'sections',s)
        p.update(research_trigger={'section':s['id'],'kind':a['kind']})
        self._save(c,'plans',p)
        self._ensure_triggered(c,p,now)
        return [s]

    def _ensure_triggered(self,c,p,now):
        trigger=p.get('research_trigger')
        if not trigger or p['status']!='active':return
        latest=self._one(c,'research_jobs',p['research_latest'],p['user_id'],now) if p.get('research_latest') else None
        if latest and latest.get('trigger_section')==trigger['section']:
            self._continue_researched(c,{'owner':p['user_id'],'plan':p['id']},now);return
        active=self._one(c,'research_jobs',p['active_research'],p['user_id'],now) if p.get('active_research') else None
        if active and (active['status']!='failed' or active['run_index']==p.get('run_index',1)):return
        jobs=c.execute('SELECT COUNT(*) FROM research_jobs WHERE plan_id=? AND run_index=?',(p['id'],p.get('run_index',1))).fetchone()[0]
        phase='initial' if jobs==0 else 'refresh'
        cap=4 if phase=='initial' else 2
        if jobs>=2 or p['remaining_creates']<1 or p.get('tool_calls_reserved',0)+cap>6:
            p.update(status='paused',pause_reason='RESEARCH_ALLOWANCE_REACHED');self._save(c,'plans',p);return
        from .adaptive_research import build_trigger_query
        from dataclasses import asdict
        request=str(uuid5(NAMESPACE_URL,'adaptive-research-trigger:'+trigger['section']+':'+trigger['kind']+':'+str(p.get('run_index',1))+':'+phase))
        try:query=asdict(build_trigger_query(p['preferences'],trigger['kind']))
        except Exception:
            p.update(status='paused',pause_reason='RESEARCH_FAILED',research_error='RESEARCH_QUERY_INVALID');self._save(c,'plans',p);return
        try:self._reserve(c,{'owner':p['user_id'],'plan':p['id'],'request_id':request,'phase':phase,'query':query},now)
        except JobRepositoryError as error:
            if error.code!='RESEARCH_STORAGE_LIMIT':raise
            scope='plan' if p['storage_used_bytes']+RESEARCH_ROW_BYTES+RESEARCH_PACK_BYTES>p['storage_limit_bytes'] else 'global'
            p.update(status='paused',pause_reason='STORAGE_LIMIT',storage_pause_scope=scope);self._save(c,'plans',p)

    def _continue_researched(self,c,a,now):
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        if not p or not p.get('research_on_demand') or not p.get('research_trigger'):return []
        trigger=p['research_trigger'];s=self._one(c,'sections',trigger['section'],a['owner'],now)
        request=str(uuid5(NAMESPACE_URL,'adaptive-researched-section:'+trigger['section']))
        prior=self._rows(c,'sections','WHERE plan_id=? AND request_id=?',(p['id'],request))
        if prior:return prior
        j=self._one(c,'research_jobs',p['research_latest'],a['owner'],now) if p.get('research_latest') else None
        if p['status']!='active' or not p['remaining_creates'] or p.get('active_research') or not s or not j or j['status']!='succeeded' or j.get('trigger_section')!=s['id'] or s['status']!='failed' or s.get('error_code')!='SECTION_RESEARCH_REQUESTED' or p['active_section']!=s['id']:return []
        p.update(active_section=None,research_trigger=None);self._save(c,'plans',p)
        rows=self._next(c,{'owner':a['owner'],'plan':p['id'],'request_id':request,'section_days':s['requested_days']},now)
        if rows:
            rows[0]['retry_of']=s['id'];self._save(c,'sections',rows[0])
        else:
            # Capacity pauses retain the exact trigger so explicit recovery can
            # retry allocation, never repeat research/provider submission.
            p=self._one(c,'plans',p['id'],a['owner'],now);p.update(active_section=s['id'],research_trigger=trigger);self._save(c,'plans',p)
        return rows

    def _reserve(self,c,a,now):
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        if not p:return []
        phase=a['phase']
        if phase not in ('initial','refresh'): _error('RESEARCH_PHASE_INVALID',400)
        query=a['query']
        # The parser module supplies a strict public-only DTO; never persist
        # the full preferences or personal notes as search input.
        from .adaptive_research import public_query_from_dict
        from dataclasses import asdict
        try: query=json.loads(json.dumps(asdict(public_query_from_dict(query))))
        except Exception:_error('RESEARCH_QUERY_INVALID',400)
        if query['destination']!=p['preferences']['destination'].strip() or query['startDate']!=p['start_date'] or query['endDate']!=p['end_date']:_error('RESEARCH_QUERY_SCOPE_INVALID',400)
        from .adaptive_research import build_trigger_query
        if p.get('research_trigger') and query!=json.loads(json.dumps(asdict(build_trigger_query(p['preferences'],p['research_trigger']['kind'])))):_error('RESEARCH_QUERY_SCOPE_INVALID',400)
        encoded=_bounded_json(query,8192);digest=hashlib.sha256(encoded).hexdigest()
        prior=self._rows(c,'research_jobs','WHERE plan_id=? AND request_id=?',(p['id'],a['request_id']))
        if prior:
            if prior[0]['query_hash']!=digest or prior[0]['phase']!=phase:_error('RESEARCH_REQUEST_CONFLICT',409)
            return prior
        trigger=p.get('research_trigger')
        if not p.get('research_on_demand') or not trigger or p['status'] not in ('active','paused'):return []
        section=self._one(c,'sections',trigger['section'],p['user_id'],now)
        if not section or section['status']!='failed' or section.get('error_code')!='SECTION_RESEARCH_REQUESTED' or p.get('active_section')!=section['id']:return []
        active=self._one(c,'research_jobs',p['active_research'],p['user_id'],now) if p.get('active_research') else None
        if active and active['status']!='failed':return []
        if p['status']=='paused' and p.get('pause_reason')!='RESEARCH_FAILED':return []
        cap=4 if phase=='initial' else 2
        if phase=='initial' and c.execute('SELECT 1 FROM research_jobs WHERE plan_id=? AND run_index=?',(p['id'],p.get('run_index',1))).fetchone():return []
        if p['remaining_creates']<1 or p.get('tool_calls_reserved',0)+cap>6:return []
        if c.execute('SELECT 1 FROM research_jobs WHERE plan_id=? AND run_index=? AND phase=?',(p['id'],p.get('run_index',1),phase)).fetchone():_error('RESEARCH_PHASE_ALREADY_RESERVED',409)
        need=RESEARCH_ROW_BYTES+RESEARCH_PACK_BYTES
        if p['storage_used_bytes']+need>p['storage_limit_bytes'] or self._allocated(c)+need>GLOBAL_STORAGE_BYTES:_error('RESEARCH_STORAGE_LIMIT',413)
        j=dict(id=str(uuid4()),plan_id=p['id'],user_id=p['user_id'],request_id=a['request_id'],run_index=p.get('run_index',1),phase=phase,
            trigger_section=trigger['section'],trigger_kind=trigger['kind'],query=query,query_hash=digest,max_tool_calls=cap,status='queued',version=1,lease_token=None,lease_until=None,worker_id=None,
            provider_response_id=None,submitted_at=None,sourcepack=None,error_code=None,reserved_sourcepack_bytes=RESEARCH_PACK_BYTES,created_at=_stamp(now))
        c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?)',(j['id'],p['id'],p['user_id'],a['request_id'],j['run_index'],phase,_json(j)))
        p.update(active_research=j['id'],status='active',pause_reason=None,storage_used_bytes=p['storage_used_bytes']+RESEARCH_ROW_BYTES);self._save(c,'plans',p)
        return [j]

    def _research_transition(self,c,a,now):
        j=self._one(c,'research_jobs',a['research'],a['owner'],now)
        if not j:return []
        p=self._one(c,'plans',j['plan_id'],j['user_id'],now)
        if p['status']!='active' or p.get('active_research')!=j['id'] or j['version']!=a['expected_version'] or type(a['expected_version']) is not int or j['lease_token']!=a['lease'] or _time(j['lease_until'])<=now:return []
        status=a['next_status'];allowed={'queued':{'submitting','failed'},'submitting':{'running','failed','submission_unknown'},'running':{'running','succeeded','failed'}}
        if status not in allowed.get(j['status'],set()):return []
        response=a['response_id'] if a['response_id'] is not None else j['provider_response_id']
        if response is not None and (type(response) is not str or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}',response)):_error('RESEARCH_TRANSITION_INVALID',400)
        if status=='running' and not response:_error('RESEARCH_TRANSITION_INVALID',400)
        if j['provider_response_id'] and response!=j['provider_response_id']:_error('RESEARCH_REQUEST_CONFLICT',409)
        code=a['failure_code']
        if code is not None and (type(code) is not str or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code)):_error('RESEARCH_TRANSITION_INVALID',400)
        pack=a['sourcepack']
        if (status=='succeeded')!=(pack is not None):_error('RESEARCH_RESULT_INVALID',400)
        if status=='submitting':
            if p['remaining_creates']<1 or p.get('tool_calls_reserved',0)+j['max_tool_calls']>6:return []
            p.update(remaining_creates=p['remaining_creates']-1,tool_calls_reserved=p.get('tool_calls_reserved',0)+j['max_tool_calls'])
        elif status=='succeeded':
            # Strict semantic/provenance validator is injected through the
            # shared result model; arbitrary 'verified' metadata cannot enter.
            from .adaptive_research import validate_research_pack
            try: pack=validate_research_pack(pack,query=j['query'],phase=j['phase'],now=datetime.fromtimestamp(now,timezone.utc))
            except Exception:_error('RESEARCH_RESULT_INVALID',400)
            size=len(_bounded_json(pack,RESEARCH_PACK_BYTES))
            if p['storage_used_bytes']+size>p['storage_limit_bytes']:_error('RESEARCH_STORAGE_LIMIT',413)
            p.update(research_latest=j['id'],active_research=None,storage_used_bytes=p['storage_used_bytes']+size,
                status='active' if p['remaining_creates'] else 'paused',pause_reason=None if p['remaining_creates'] else 'RESOURCE_ALLOWANCE_REACHED')
        elif status in ('failed','submission_unknown'):
            p.update(status='paused',pause_reason=('RESEARCH_ALLOWANCE_REACHED' if p['remaining_creates']==0 or p.get('tool_calls_reserved',0)>=6 else 'RESEARCH_FAILED') if status=='failed' else 'RESEARCH_SUBMISSION_UNKNOWN')
        self._save(c,'plans',p)
        j.update(status=status,provider_response_id=response,error_code=code,sourcepack=pack,
            reserved_sourcepack_bytes=0 if status in ('succeeded','failed','submission_unknown') else j['reserved_sourcepack_bytes'],
            submitted_at=_stamp(now) if status=='submitting' else j['submitted_at'],
            lease_token=j['lease_token'] if status=='submitting' else None,lease_until=_stamp(now+60) if status=='submitting' else None)
        self._save(c,'research_jobs',j);return [j]
