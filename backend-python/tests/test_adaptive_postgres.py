import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.adaptive_postgres import AdaptivePostgresGateway, ADAPTIVE_ROLE_AUDIT, RPCS
from app.planning_repository import JobRepositoryError
from test_planning_postgres import URL

class Cursor:
    def __init__(self,rows):self.rows=rows
    async def fetchmany(self,count):return self.rows[:count]
class Connection:
    def __init__(self,rows=None,safe=True):self.rows=rows or [];self.safe=safe;self.queries=[];self.committed=False
    async def __aenter__(self):return self
    async def __aexit__(self,*args):self.committed=True
    async def execute(self,query,values=None):
        self.queries.append((query,values))
        if query.startswith('SET LOCAL'):return Cursor([])
        if query==ADAPTIVE_ROLE_AUDIT:return Cursor([(json.dumps({'role':'planning_queue_worker','safe':self.safe}),)])
        return Cursor([(json.dumps(v),) for v in self.rows])

def gateway(connection):
    async def factory(**kwargs):
        assert kwargs['sslmode']=='verify-full' and kwargs['prepare_threshold'] is None
        return connection
    return AdaptivePostgresGateway(URL,enabled=True,connection_factory=factory)


def test_adaptive_exact_allowlist_does_not_weaken_private_or_definer_audit():
    assert "'adaptive_plans'" in ADAPTIVE_ROLE_AUDIT
    assert "p.prosecdef AND has_function_privilege" in ADAPTIVE_ROLE_AUDIT
    assert "NOT has_schema_privilege(current_user,'auth','USAGE')" in ADAPTIVE_ROLE_AUDIT
    for name,fields in RPCS.items():
        assert 'public.'+name+'('+','.join(kind for _,kind in fields)+')' in ADAPTIVE_ROLE_AUDIT
    assert "'saved_itineraries'" not in ADAPTIVE_ROLE_AUDIT


def test_parameterized_page_query_and_commit_before_return():
    async def run():
        conn=Connection([{'id':str(uuid4())} for _ in range(3)]);api=gateway(conn)
        owner,plan=str(uuid4()),str(uuid4())
        rows=await api.request('POST','rpc/adaptive_list_sections',payload={'owner':owner,'plan':plan,'after_sequence':0,'page_size':3})
        assert len(rows)==3 and conn.committed
        assert owner not in conn.queries[-1][0] and conn.queries[-1][1]==[owner,plan,0,3]
        assert conn.queries[0][0]=="SET LOCAL search_path=''"
    asyncio.run(run())

@pytest.mark.parametrize('operation',[('GET','adaptive_plans',{}),('POST','rpc/purge_expired_planning_jobs',{}),('POST','rpc/adaptive_checkpoint_health',{'sql':'select secret'}),('POST','rpc/adaptive_list_sections',{'owner':str(uuid4()),'plan':str(uuid4()),'after_sequence':-1,'page_size':3})])
def test_unknown_operation_rejected_without_connection(operation):
    async def run():
        conn=Connection();api=gateway(conn)
        with pytest.raises(JobRepositoryError):await api.request(operation[0],operation[1],payload=operation[2])
        assert not conn.queries
    asyncio.run(run())

@pytest.mark.parametrize('rows',[[{}]*4,[{'padding':'x'*200000}]*3])
def test_aggregate_row_and_bytes_bounds(rows):
    async def run():
        with pytest.raises(JobRepositoryError):await AdaptivePostgresGateway._rows(Cursor([(json.dumps(v),) for v in rows]))
    asyncio.run(run())


def test_false_role_audit_never_executes_operation():
    async def run():
        conn=Connection(safe=False)
        with pytest.raises(JobRepositoryError) as caught:await gateway(conn).request('POST','rpc/adaptive_checkpoint_health',payload={})
        assert caught.value.code=='JOB_WORKER_CONTEXT_REQUIRED'
        assert not any('FROM public.adaptive_checkpoint_health' in q for q,_ in conn.queries)
    asyncio.run(run())


def test_only_fixed_rejection_messages_become_definitive():
    api=gateway(Connection())
    error=SimpleNamespace(sqlstate='P0001',diag=SimpleNamespace(message_primary='Adaptive active-plan resource limit reached'))
    mapped=api._known_error('rpc/adaptive_create_plan',error)
    assert mapped.code=='SECTION_ADMISSION_REJECTED' and mapped.status==429
    error.diag.message_primary='private arbitrary server text'
    assert api._known_error('rpc/adaptive_create_plan',error) is None
