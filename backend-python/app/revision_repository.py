"""Owner-scoped selected-day revisions. Internal rows are never public DTOs."""
from .planning_repository import JobRepositoryError,identity
from .section_repository import _bounded_json

REVISION_SCHEMA = """CREATE TABLE revision_jobs(
 id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,user_id TEXT NOT NULL,request_id TEXT NOT NULL,
 root_id TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)),UNIQUE(user_id,request_id),
 FOREIGN KEY(plan_id,user_id) REFERENCES plans(id,user_id) ON DELETE CASCADE,
 FOREIGN KEY(root_id,user_id) REFERENCES plans(id,user_id) ON DELETE CASCADE);
CREATE INDEX revision_jobs_owner ON revision_jobs(user_id);
CREATE TABLE revision_controls(
 root_id TEXT NOT NULL,user_id TEXT NOT NULL,request_id TEXT NOT NULL,
 PRIMARY KEY(user_id,request_id),FOREIGN KEY(root_id,user_id) REFERENCES plans(id,user_id) ON DELETE CASCADE);
"""

PUBLIC_REVISION_ERRORS = frozenset({
    'REVISION_REQUEST_FAILED','REVISION_BASE_CHANGED','REVISION_BASE_EXPIRED','REVISION_BUDGET_EXCEEDED',
    'REVISION_BUDGET_EXHAUSTED','REVISION_CONSTRAINT_CONFLICT','REVISION_DEADLINE_REACHED',
    'REVISION_FIXED_COMMITMENT_CONFLICT','REVISION_INSUFFICIENT_RETENTION','REVISION_INVALID_BASE',
    'REVISION_INVALID_RESULT','REVISION_ALLOWANCE_REACHED','REVISION_POLL_UNCONFIRMED',
    'REVISION_PROVIDER_FAILED','REVISION_PROVIDER_REJECTED','REVISION_REPEAT_CONFLICT',
    'REVISION_RESPONSE_MISMATCH','REVISION_REST_CONFLICT','REVISION_RESULT_INVALID',
    'REVISION_RETURN_CONFLICT','REVISION_ROUTE_CONFLICT','REVISION_STORAGE_LIMIT',
    'REVISION_STORAGE_UNCONFIRMED','REVISION_SUBMISSION_UNCONFIRMED','REVISION_TARGET_INVALID',
    'REVISION_UNCHANGED_DAY_MODIFIED','REVISION_WARNING_CAPACITY'})


def revision_tables_ready(c):
    expected={'revision_jobs':{'id','plan_id','user_id','request_id','root_id','data'},
              'revision_controls':{'root_id','user_id','request_id'}}
    for table,columns in expected.items():
        if {r[1] for r in c.execute('PRAGMA table_info('+table+')')}!=columns:return False
        unique=[r[1] for r in c.execute('PRAGMA index_list('+table+')') if r[2]]
        if not any([r[2] for r in c.execute('PRAGMA index_info("'+name.replace('"','""')+'")')]==['user_id','request_id'] for name in unique):return False
        fks=list(c.execute('PRAGMA foreign_key_list('+table+')'))
        expected_refs={('plan_id','id'),('root_id','id'),('user_id','user_id')} if table=='revision_jobs' else {('root_id','id'),('user_id','user_id')}
        if {(r[3],r[4]) for r in fks}!=expected_refs or any(r[2]!='plans' or r[6]!='CASCADE' for r in fks):return False
    return True


class RevisionRepository:
    def __init__(self,gateway,*,enabled=False):
        if enabled is not True or getattr(gateway,'supports_revisions',False) is not True or getattr(gateway,'elevated',False) is not True:
            raise JobRepositoryError('REVISION_DISABLED',503)
        self.gateway=gateway

    async def _call(self,op,owner,*,optional=False,**payload):
        owner=identity(owner)
        try:
            rows=await self.gateway.revision_request(op,dict(owner=owner,**payload))
            if type(rows) is not list or len(rows)>1 or any(type(r) is not dict or r.get('user_id')!=owner for r in rows):raise ValueError()
            _bounded_json(rows,262144)
            if not rows:
                if optional:return None
                raise JobRepositoryError('REVISION_NOT_FOUND_OR_CONFLICT',409)
            return rows[0]
        except JobRepositoryError:raise
        except Exception:raise JobRepositoryError('REVISION_STORAGE_UNCONFIRMED',503) from None

    async def verify_ready(self):
        try:
            rows=await self.gateway.revision_request('health',{})
            if rows!=[{'schema_version':2,'revision_version':1,'cleanup_fresh':True}]:raise ValueError()
        except Exception:raise JobRepositoryError('REVISION_SCHEMA_NOT_READY',503) from None

    async def lookup(self,owner,request_id):
        return await self._call('lookup',owner,optional=True,request_id=identity(request_id))
    async def current(self,owner,base):
        return await self._call('current',owner,optional=True,plan=identity(base))
    async def reserve(self,owner,base,request):
        return await self._call('reserve',owner,plan=identity(base),request=request,retry_of=None)
    async def retry(self,owner,revision,request_id):
        return await self._call('retry',owner,revision=identity(revision),request_id=identity(request_id))
    async def get(self,owner,revision):
        return await self._call('get',owner,revision=identity(revision))
    async def reject(self,owner,revision):
        return await self._call('reject',owner,revision=identity(revision))
    async def accept(self,owner,revision):
        return await self._call('accept',owner,revision=identity(revision))
    async def continue_run(self,owner,base,request_id):
        return await self._call('continue',owner,plan=identity(base),request_id=identity(request_id))
    async def context(self,owner,revision):
        return await self.gateway.revision_context(identity(owner),identity(revision))
    async def claim_next(self,worker):
        try:
            rows=await self.gateway.revision_request('claim_next',{'worker':identity(worker)})
            if type(rows) is not list or len(rows)>1:raise ValueError()
            if not rows:return None
            identity(rows[0]['user_id']);_bounded_json(rows,262144)
            return rows[0]
        except JobRepositoryError:raise
        except Exception:raise JobRepositoryError('REVISION_STORAGE_UNCONFIRMED',503) from None
    async def transition(self,owner,revision,lease,version,status,*,provider_response_id=None,error_code=None,output_text=None):
        return await self._call('transition',owner,revision=identity(revision),lease=identity(lease),expected_version=version,
            next_status=status,response_id=provider_response_id,error_code=error_code,output_text=output_text)


def public_revision(row):
    """No instruction, provider identity, leases, hashes or internal context."""
    return {'id':row['id'],'requestId':row['request_id'],'basePlanId':row['plan_id'],'targetDate':row['target_date'],
        'status':row['status'],'accepted':row['status']=='accepted','expiresAt':row['expires_at'],
        'errorCode':(row.get('error_code') if type(row.get('error_code')) is str and row.get('error_code') in PUBLIC_REVISION_ERRORS else 'REVISION_REQUEST_FAILED') if row.get('error_code') is not None else None,'remainingCreates':row.get('remaining_creates',0),
        'candidate':({k:row['candidate'][k] for k in ('checkpoint','totalSpentCents','targetDate','status','accepted')} if row['status']=='candidate' else None),
        'acceptedPlanId':row.get('accepted_plan_id')}
