"""Explicitly provisioned revision jobs sharing durable admission and quotas."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
import re
from uuid import uuid4,uuid5,NAMESPACE_URL
from .research_sqlite import ResearchSQLiteGateway
from .adaptive_sqlite import _stamp,_time,_error,_json
from .adaptive_revision import RevisionRequest,RevisionContract,RevisionCandidate,prepare_revision,canonical_hash
from .adaptive_planning import AdaptiveError
from .planning_repository import JobRepositoryError,identity
from .revision_repository import revision_tables_ready
from .section_repository import _bounded_json,GLOBAL_STORAGE_BYTES,PLAN_ROW_RESERVATION_BYTES,SECTION_ROW_RESERVATION_BYTES,validate_checkpoint

ROW_BYTES=16384
CANDIDATE_BYTES=131072
_ARGS={'health':set(),'lookup':{'owner','request_id'},'current':{'owner','plan'},'reserve':{'owner','plan','request','retry_of'},'get':{'owner','revision'},'retry':{'owner','revision','request_id'},
 'reject':{'owner','revision'},'accept':{'owner','revision'},'continue':{'owner','plan','request_id'},'claim_next':{'worker'},
 'transition':{'owner','revision','lease','expected_version','next_status','response_id','error_code','output_text'}}

class RevisionSQLiteGateway(ResearchSQLiteGateway):
    supports_revisions=True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        with self._connect() as c:
            if not revision_tables_ready(c):_error('REVISION_SCHEMA_NOT_READY',503)

    async def revision_request(self,op,payload):
        if op not in _ARGS or type(payload) is not dict or set(payload)!=_ARGS[op]:_error('REVISION_REQUEST_INVALID',400)
        for key in {'owner','plan','revision','worker','lease','request_id'}&payload.keys():identity(payload[key])
        _bounded_json(payload,262144)
        return await asyncio.to_thread(self._execute,'revision_'+op,payload)

    async def revision_context(self,owner,revision):
        def read():
            with self._connect() as c:
                c.execute('BEGIN')
                j=self._one(c,'revision_jobs',revision,owner,self.clock())
                if not j:_error('REVISION_NOT_FOUND_OR_CONFLICT',409)
                return self._context(c,j,self.clock())
        try:return await asyncio.to_thread(read)
        except (JobRepositoryError,AdaptiveError):raise
        except Exception:_error('REVISION_STORAGE_UNCONFIRMED',503)

    def _accepted(self,c,plan,owner):
        cursor=c.execute("SELECT data FROM sections WHERE plan_id=? AND user_id=? AND json_extract(data,'$.status')='succeeded' ORDER BY sequence",(plan,owner))
        for row in cursor:yield json.loads(row[0])

    def _context(self,c,j,now):
        p=self._one(c,'plans',j['plan_id'],j['user_id'],now)
        if not p:_error('REVISION_BASE_EXPIRED',410)
        try:
            context=prepare_revision(j['user_id'],p,self._accepted(c,p['id'],p['user_id']),
                {'requestId':j['request_id'],'targetDate':j['target_date'],'instruction':j['instruction']},now=datetime.fromtimestamp(now,timezone.utc))
        except AdaptiveError as e:_error(e.code,409)
        if j.get('source_digest') and (context.source_digest!=j['source_digest'] or context.base_version!=j['base_version']):_error('REVISION_BASE_CHANGED',409)
        return context

    def _allocated(self,c):
        return super()._allocated(c)+c.execute("SELECT COALESCE(SUM(json_extract(data,'$.storage_bytes')),0) FROM revision_jobs").fetchone()[0]+512*c.execute('SELECT COUNT(*) FROM revision_controls').fetchone()[0]

    def _paid_work_count(self,c,now):
        return super()._paid_work_count(c,now)+c.execute("SELECT COUNT(*) FROM revision_jobs WHERE json_extract(data,'$.status') IN ('submitting','running') OR (json_extract(data,'$.status')='queued' AND json_extract(data,'$.lease_until')>?) OR (json_extract(data,'$.status') IN ('submission_unknown','rejected','failed') AND json_extract(data,'$.submitted_at')>?)",(_stamp(now),_stamp(now-600))).fetchone()[0]

    def _owner_revision(self,c,owner,now):
        return c.execute("SELECT 1 FROM revision_jobs WHERE user_id=? AND (json_extract(data,'$.status') IN ('queued','submitting','running','candidate','submission_unknown') OR (json_extract(data,'$.status')='rejected' AND json_extract(data,'$.submitted_at')>?)) AND json_extract(data,'$.expires_at')>? LIMIT 1",(owner,_stamp(now-600),_stamp(now))).fetchone() is not None

    def _create(self,c,a,now):
        prior=c.execute('SELECT 1 FROM plans WHERE user_id=? AND request_id=?',(a['owner'],a['request_id'])).fetchone()
        if not prior and self._owner_revision(c,a['owner'],now):
            active=c.execute("SELECT 1 FROM revision_jobs WHERE user_id=? AND json_extract(data,'$.status') IN ('queued','submitting','running','candidate','submission_unknown') AND json_extract(data,'$.expires_at')>? LIMIT 1",(a['owner'],_stamp(now))).fetchone()
            _error('SECTION_OWNER_PLAN_EXISTS' if active else 'SECTION_CAPACITY_LIMIT',429)
        return super()._create(c,a,now)

    def _remaining(self,c,root,owner,now):
        p=self._one(c,'plans',root,owner,now)
        if not p:_error('REVISION_BASE_EXPIRED',410)
        used=c.execute("SELECT COUNT(*) FROM revision_jobs WHERE root_id=? AND json_extract(data,'$.submitted_at') IS NOT NULL",(root,)).fetchone()[0]
        runs=c.execute('SELECT COUNT(*) FROM revision_controls WHERE root_id=?',(root,)).fetchone()[0]
        return max(0,p['remaining_creates']+12*runs-used)

    def _quota(self,c,p,need):
        own=c.execute("SELECT COALESCE(SUM(json_extract(data,'$.storage_bytes')),0) FROM revision_jobs WHERE plan_id=?",(p['id'],)).fetchone()[0]
        controls=512*c.execute('SELECT COUNT(*) FROM revision_controls WHERE root_id=?',(p.get('revision_budget_root',p['id']),)).fetchone()[0]
        if p['storage_used_bytes']+own+controls+need>p['storage_limit_bytes'] or self._allocated(c)+need>GLOBAL_STORAGE_BYTES:_error('REVISION_STORAGE_LIMIT',413)

    def _revision_reserve(self,c,a,now):
        try:req=RevisionRequest.parse(a['request'])
        except AdaptiveError as e:_error(e.code,400)
        prior=self._rows(c,'revision_jobs','WHERE user_id=? AND request_id=?',(a['owner'],req.request_id))
        if prior:
            j=prior[0]
            if j['plan_id']!=a['plan'] or j['target_date']!=req.target_date or j['instruction']!=req.instruction or j.get('retry_of')!=a['retry_of']:_error('REVISION_REQUEST_CONFLICT',409)
            if _time(j['expires_at'])<=now:_error('REVISION_BASE_EXPIRED',410)
            j['remaining_creates']=self._remaining(c,j['root_id'],j['user_id'],now);return [j]
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        if not p:_error('REVISION_BASE_EXPIRED',410)
        if _time(p['expires_at'])-now<480:_error('REVISION_INSUFFICIENT_RETENTION',409)
        if self._owner_revision(c,a['owner'],now) or c.execute("SELECT 1 FROM plans WHERE user_id=? AND json_extract(data,'$.status') IN ('active','paused') AND json_extract(data,'$.expires_at')>?",(a['owner'],_stamp(now))).fetchone():_error('REVISION_OWNER_BUSY',409)
        root=p.get('revision_budget_root',p['id']);remaining=self._remaining(c,root,a['owner'],now)
        if remaining<1:_error('REVISION_ALLOWANCE_REACHED',409)
        self._quota(c,p,ROW_BYTES+CANDIDATE_BYTES)
        j=dict(id=str(uuid4()),plan_id=p['id'],root_id=root,user_id=a['owner'],request_id=req.request_id,target_date=req.target_date,instruction=req.instruction,
            retry_of=a['retry_of'],status='queued',version=1,lease_token=None,lease_until=None,worker_id=None,provider_response_id=None,submitted_at=None,
            candidate=None,candidate_hash=None,error_code=None,accepted_plan_id=None,created_at=_stamp(now),expires_at=p['expires_at'],
            storage_bytes=ROW_BYTES+CANDIDATE_BYTES,remaining_creates=remaining)
        ctx=self._context(c,j,now);j.update(source_digest=ctx.source_digest,base_version=ctx.base_version)
        c.execute('INSERT INTO revision_jobs VALUES(?,?,?,?,?,?)',(j['id'],j['plan_id'],j['user_id'],j['request_id'],root,_json(j)))
        return [j]

    def _dispatch(self,c,op,a,now):
        if op=='find_current':
            plans=super()._dispatch(c,op,a,now)
            if plans:return plans
            jobs=self._rows(c,'revision_jobs',"WHERE user_id=? AND json_extract(data,'$.status') IN ('queued','submitting','running','candidate','submission_unknown') AND json_extract(data,'$.expires_at')>? LIMIT 2",(a['owner'],_stamp(now)))
            if len(jobs)>1:_error('SECTION_OWNER_RECOVERY_CONFLICT',503)
            if not jobs:return []
            plan=self._one(c,'plans',jobs[0]['plan_id'],a['owner'],now)
            if not plan or plan['status']!='completed':_error('SECTION_OWNER_RECOVERY_CONFLICT',503)
            return [plan]
        if not op.startswith('revision_'):return super()._dispatch(c,op,a,now)
        op=op[9:]
        if op=='health':
            if not revision_tables_ready(c):_error('REVISION_SCHEMA_NOT_READY',503)
            runtime=c.execute('SELECT version,last_purge FROM runtime WHERE id=1').fetchone()
            return [{'schema_version':runtime['version'],'revision_version':1,'cleanup_fresh':runtime['last_purge'] is not None and 0<=now-runtime['last_purge']<180}]
        if op=='lookup':
            rows=self._rows(c,'revision_jobs','WHERE user_id=? AND request_id=?',(a['owner'],a['request_id']))
            rows=[j for j in rows if _time(j['expires_at'])>now]
            if rows:rows[0]['remaining_creates']=self._remaining(c,rows[0]['root_id'],a['owner'],now)
            return rows
        if op=='current':
            rows=self._rows(c,'revision_jobs',"WHERE user_id=? AND plan_id=? AND json_extract(data,'$.status') IN ('queued','submitting','running','candidate','submission_unknown') AND json_extract(data,'$.expires_at')>? LIMIT 2",(a['owner'],a['plan'],_stamp(now)))
            if len(rows)>1:_error('REVISION_STORAGE_UNCONFIRMED',503)
            if rows:rows[0]['remaining_creates']=self._remaining(c,rows[0]['root_id'],a['owner'],now)
            return rows
        if op=='reserve':return self._revision_reserve(c,a,now)
        if op=='claim_next':
            rows=self._rows(c,'revision_jobs',"WHERE json_extract(data,'$.status') IN ('queued','submitting','running') AND COALESCE(json_extract(data,'$.lease_until'),'')<=? AND json_extract(data,'$.expires_at')>? ORDER BY (json_extract(data,'$.status')='running') DESC,json_extract(data,'$.created_at') LIMIT 3",(_stamp(now),_stamp(now)))
            for j in rows:
                if j['status']=='submitting':
                    j.update(status='submission_unknown',error_code='REVISION_SUBMISSION_UNCONFIRMED',lease_token=None,lease_until=None,storage_bytes=ROW_BYTES);self._save(c,'revision_jobs',j);continue
                if j['status']=='queued' and self._paid_work_count(c,now)>=2:continue
                j.update(lease_token=str(uuid4()),lease_until=_stamp(now+60),worker_id=a['worker']);self._save(c,'revision_jobs',j);return [j]
            return []
        if op=='continue':
            p=self._one(c,'plans',a['plan'],a['owner'],now)
            if not p:_error('REVISION_BASE_EXPIRED',410)
            root=p.get('revision_budget_root',p['id']);prior=c.execute('SELECT root_id FROM revision_controls WHERE user_id=? AND request_id=?',(a['owner'],a['request_id'])).fetchone()
            if prior:
                if prior[0]!=root:_error('REVISION_REQUEST_CONFLICT',409)
            else:
                if _time(p['expires_at'])-now<480:_error('REVISION_INSUFFICIENT_RETENTION',409)
                if self._remaining(c,root,a['owner'],now)!=0 or self._owner_revision(c,a['owner'],now) or c.execute("SELECT 1 FROM plans WHERE user_id=? AND json_extract(data,'$.status') IN ('active','paused') AND json_extract(data,'$.expires_at')>?",(a['owner'],_stamp(now))).fetchone():_error('REVISION_CONTINUE_CONFLICT',409)
                self._quota(c,p,512)
                c.execute('INSERT INTO revision_controls VALUES(?,?,?)',(root,a['owner'],a['request_id']))
            return [dict(user_id=a['owner'],plan_id=p['id'],remaining_creates=self._remaining(c,root,a['owner'],now))]
        j=self._one(c,'revision_jobs',a['revision'],a['owner'],now)
        if not j:return []
        j['remaining_creates']=self._remaining(c,j['root_id'],j['user_id'],now)
        if op=='get':return [j]
        if op=='retry':
            if j['status']!='failed':_error('REVISION_RETRY_CONFLICT',409)
            return self._revision_reserve(c,dict(owner=a['owner'],plan=j['plan_id'],request={'requestId':a['request_id'],'targetDate':j['target_date'],'instruction':j['instruction']},retry_of=j['id']),now)
        if op=='reject':
            if j['status']=='accepted':_error('REVISION_ALREADY_ACCEPTED',409)
            j.update(status='rejected',candidate=None,candidate_hash=None,storage_bytes=ROW_BYTES,lease_token=None,lease_until=None)
            self._save(c,'revision_jobs',j);return [j]
        if op=='accept':return self._revision_accept(c,j,now)
        if op=='transition':return self._revision_transition(c,j,a,now)
        _error('REVISION_REQUEST_INVALID',400)

    def _revision_transition(self,c,j,a,now):
        if type(a['expected_version']) is not int or j['version']!=a['expected_version'] or j['lease_token']!=a['lease'] or _time(j['lease_until'])<=now:return []
        status=a['next_status'];allowed={'queued':{'submitting','failed'},'submitting':{'running','failed','submission_unknown'},'running':{'running','candidate','failed'}}
        if status not in allowed.get(j['status'],set()):return []
        response=a['response_id'] if a['response_id'] is not None else j['provider_response_id']
        if response is not None and (type(response) is not str or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}',response)):_error('REVISION_TRANSITION_INVALID',400)
        if status=='running' and not response:_error('REVISION_TRANSITION_INVALID',400)
        if j['provider_response_id'] and j['provider_response_id']!=response:_error('REVISION_REQUEST_CONFLICT',409)
        code=a['error_code']
        if code is not None and (type(code) is not str or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code)):_error('REVISION_TRANSITION_INVALID',400)
        if (status=='candidate')!=(a['output_text'] is not None):_error('REVISION_RESULT_INVALID',400)
        if status=='submitting':
            if _time(j['expires_at'])-now<480:_error('REVISION_INSUFFICIENT_RETENTION',409)
            if self._remaining(c,j['root_id'],j['user_id'],now)<1:_error('REVISION_ALLOWANCE_REACHED',409)
            self._context(c,j,now)
        if status=='candidate':
            try:
                if type(a['output_text']) is not str or len(a['output_text'].encode())>CANDIDATE_BYTES:_error('REVISION_RESULT_INVALID',400)
                result=RevisionContract(self._context(c,j,now)).decode(a['output_text'])
                if not isinstance(result,RevisionCandidate):_error('REVISION_CONSTRAINT_CONFLICT',409)
                candidate=dict(checkpoint=result.checkpoint,totalSpentCents=result.total_spent_cents,targetDate=result.target_date,
                    sourceDigest=result.source_digest,baseVersion=result.base_version,status='candidate',accepted=False)
                _bounded_json(candidate,CANDIDATE_BYTES)
            except AdaptiveError as e:_error(e.code,400)
            j.update(candidate=candidate,candidate_hash=canonical_hash(candidate),storage_bytes=ROW_BYTES+len(_bounded_json(candidate)))
        elif status in ('failed','submission_unknown'):j.update(candidate=None,candidate_hash=None,storage_bytes=ROW_BYTES)
        j.update(status=status,provider_response_id=response,error_code=code,submitted_at=_stamp(now) if status=='submitting' else j['submitted_at'],
            lease_token=j['lease_token'] if status=='submitting' else None,lease_until=_stamp(now+60) if status=='submitting' else None)
        self._save(c,'revision_jobs',j)
        j['remaining_creates']=self._remaining(c,j['root_id'],j['user_id'],now)
        return [j]

    def _revision_accept(self,c,j,now):
        if j['status']=='accepted':return [j]
        if j['status']!='candidate':_error('REVISION_ACCEPT_CONFLICT',409)
        ctx=self._context(c,j,now);candidate=j['candidate']
        if canonical_hash(candidate)!=j['candidate_hash']:_error('REVISION_BASE_CHANGED',409)
        from .adaptive_revision import validate_revision_candidate
        try:validate_revision_candidate(ctx,candidate)
        except AdaptiveError as e:_error(e.code,409)
        base=self._one(c,'plans',j['plan_id'],j['user_id'],now)
        total_size=PLAN_ROW_RESERVATION_BYTES
        for s in self._accepted(c,base['id'],base['user_id']):
            cp=candidate['checkpoint'] if s['id']==ctx.target_section['id'] else s['checkpoint']
            total_size+=SECTION_ROW_RESERVATION_BYTES+len(_bounded_json(cp))
        if total_size>base['storage_limit_bytes'] or self._allocated(c)+total_size>GLOBAL_STORAGE_BYTES:_error('REVISION_STORAGE_LIMIT',413)
        new=deepcopy(base);newid=str(uuid5(NAMESPACE_URL,'accepted-revision:'+j['id']))
        new.update(id=newid,request_id=str(uuid5(NAMESPACE_URL,'accepted-revision-request:'+j['id'])),version=1,created_at=_stamp(now),
            spent_cents=candidate['totalSpentCents'],storage_used_bytes=total_size,remaining_creates=self._remaining(c,j['root_id'],j['user_id'],now),
            revision_budget_root=j['root_id'],revision_of=base['id'],active_research=None,research_latest=None,research_trigger=None)
        c.execute('INSERT INTO plans VALUES(?,?,?,?)',(new['id'],new['user_id'],new['request_id'],_json(new)))
        for source in self._accepted(c,base['id'],base['user_id']):
            s=deepcopy(source);s.update(id=str(uuid4()),plan_id=newid,request_id=str(uuid4()),version=1,provider_response_id=None,lease_token=None,lease_until=None,worker_id=None,research_source_id=None)
            if source['id']==ctx.target_section['id']:
                s['checkpoint']=candidate['checkpoint'];s['budget_limit_cents']=ctx.total_budget_cents-(ctx.original_total_cents-source['checkpoint']['spentCents'])
            validate_checkpoint(s['checkpoint'],s)
            c.execute('INSERT INTO sections VALUES(?,?,?,?,?,?)',(s['id'],newid,s['user_id'],s['request_id'],s['sequence'],_json(s)))
        j.update(status='accepted',accepted_plan_id=newid,candidate=None,candidate_hash=None,storage_bytes=ROW_BYTES)
        self._save(c,'revision_jobs',j);return [j]
