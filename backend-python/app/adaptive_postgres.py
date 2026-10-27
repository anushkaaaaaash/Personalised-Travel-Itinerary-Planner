"""Fixed adaptive RPC transport; same TLS, role guard and commit semantics.

The additional role grants must be explicitly approved and catalog-reviewed.
No credentials are loaded here, no SQL identifiers come from callers.
"""
import json
from .planning_postgres import PlanningPostgresGateway, ROLE_AUDIT, MAX_BYTES, uuid, json_value, invalid
from .planning_repository import JobRepositoryError

RPCS = {
 'adaptive_create_plan': (('owner','uuid'),('request_id','uuid'),('preferences','jsonb'),('input_hash','text'),('budget_cents','bigint'),('run_allowance','integer')),
 'adaptive_get_plan': (('owner','uuid'),('plan','uuid')),
 'adaptive_find_request': (('owner','uuid'),('request_id','uuid')),
 'adaptive_recent_checkpoints': (('owner','uuid'),('plan','uuid')),
 'adaptive_get_section': (('owner','uuid'),('section','uuid')),
 'adaptive_list_sections': (('owner','uuid'),('plan','uuid'),('after_sequence','integer'),('page_size','integer')),
 'adaptive_next_section': (('owner','uuid'),('plan','uuid'),('request_id','uuid'),('section_days','integer')),
 'adaptive_claim_section': (('owner','uuid'),('section','uuid'),('worker','uuid')),
 'adaptive_claim_next': (('worker','uuid'),),
 'adaptive_transition_section': (('owner','uuid'),('section','uuid'),('lease','uuid'),('expected_version','bigint'),('next_status','text'),('response_id','text'),('failure_code','text'),('checkpoint','jsonb'),('failure_details','jsonb')),
 'adaptive_retry_section': (('owner','uuid'),('section','uuid'),('request_id','uuid'),('section_days','integer')),
 'adaptive_continue_run': (('owner','uuid'),('plan','uuid'),('request_id','uuid'),('run_allowance','integer')),
 'adaptive_cancel_plan': (('owner','uuid'),('plan','uuid')),
 'adaptive_checkpoint_health': (),
}
_TABLES = "'planning_jobs','planning_job_runtime','adaptive_plans','adaptive_sections','adaptive_run_requests','adaptive_checkpoint_runtime'"
_ADDITIONAL_SIGNATURES = ',\n'.join("to_regprocedure('public."+name+'('+','.join(kind for _,kind in fields)+")')::oid" for name,fields in RPCS.items())
ADAPTIVE_ROLE_AUDIT = ROLE_AUDIT.replace("'planning_jobs','planning_job_runtime'",_TABLES).replace(
    "to_regprocedure('public.purge_expired_planning_jobs()')::oid]",
    "to_regprocedure('public.purge_expired_planning_jobs()')::oid,\n"+_ADDITIONAL_SIGNATURES+",\nto_regprocedure('public.adaptive_purge_expired()')::oid]")


class AdaptivePostgresGateway(PlanningPostgresGateway):
    role_audit = ADAPTIVE_ROLE_AUDIT

    def _query(self,method,resource,params,payload):
        name = resource.removeprefix('rpc/') if isinstance(resource,str) else ''
        if method!='POST' or resource!='rpc/'+name or name not in RPCS or params is not None or type(payload) is not dict:
            raise invalid()
        fields = RPCS[name]
        if set(payload)!={key for key,_ in fields}: raise invalid()
        values=[]
        for key,kind in fields:
            value=payload[key]
            if kind=='uuid': value=uuid(value)
            elif kind=='jsonb': value=json_value(value)
            elif kind in {'integer','bigint'}:
                if type(value) is not int or not 0<=value<=(2147483647 if kind=='integer' else 9223372036854775807): raise invalid()
                if key!='after_sequence' and value==0: raise invalid()
            elif value is not None and (type(value) is not str or len(value)>256 or any(ord(c)<32 for c in value)):
                raise invalid()
            values.append(value)
        placeholders=','.join('%s::'+kind for _,kind in fields)
        return f'SELECT row_to_json(q)::text FROM public.{name}({placeholders}) q LIMIT 4',values

    @staticmethod
    async def _rows(cursor):
        rows=await cursor.fetchmany(4)
        if len(rows)>3: raise JobRepositoryError('SECTION_RESPONSE_LIMIT')
        result=[]; total=0
        for row in rows:
            if type(row) not in (tuple,list) or len(row)!=1 or type(row[0]) is not str: raise JobRepositoryError()
            total+=len(row[0].encode())
            if total>MAX_BYTES: raise JobRepositoryError('SECTION_RESPONSE_LIMIT')
            value=json.loads(row[0])
            if type(value) is not dict: raise JobRepositoryError()
            result.append(value)
        return result

    def _known_error(self,resource,error):
        if getattr(error,'sqlstate',None)=='P0001':
            fixed=getattr(getattr(error,'diag',None),'message_primary',None)
            if resource=='rpc/adaptive_create_plan' and fixed in {'Adaptive active-plan resource limit reached','Adaptive global storage allowance reached'}:
                return JobRepositoryError('SECTION_ADMISSION_REJECTED',429)
            if fixed in {'Adaptive request conflict','Run request conflict','Section request conflict','Retry request conflict'}:
                return JobRepositoryError('SECTION_REQUEST_CONFLICT',409)
        return None
