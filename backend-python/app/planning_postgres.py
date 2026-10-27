"""Least-privileged queue-only SQL gateway. Disabled unless explicitly injected.

No role creation, credential discovery, network access at import, or retries.
The LOGIN role needs reviewed queue/runtime grants AND scoped RLS policies, but
must have no auth/trips/saved-itinerary privileges. `elevated` means a trusted
server queue context, not a database administrator or service-role identity.
"""
import asyncio
import json
import os
import re
from urllib.parse import urlsplit, unquote
from uuid import UUID
from .planning_repository import JobRepositoryError

MAX_BYTES = 524288
RPCS = {
    'rpc/planning_queue_health': ('planning_queue_health', ()),
    'rpc/enqueue_planning_job': ('enqueue_planning_job', (('request_row', 'jsonb'),)),
    'rpc/claim_planning_job': ('claim_planning_job', (('worker', 'uuid'),)),
    'rpc/cancel_planning_job': ('cancel_planning_job', (('owner', 'uuid'), ('job', 'uuid'))),
    'rpc/transition_planning_job': ('transition_planning_job', (
        ('job', 'uuid'), ('lease', 'uuid'), ('expected_version', 'integer'), ('next_status', 'text'),
        ('response_id', 'text'), ('output', 'jsonb'), ('failure_code', 'text'), ('evidence_payload', 'jsonb'))),
}
# Exact, catalog-verified platform metadata compatibility. No namespace-wide
# exception: object identity, extension membership, owner, effective bits and RLS
# must all match the reviewed Supabase metadata. No private application exception.
_PLATFORM_TABLE_METADATA = """(
 NOT has_schema_privilege(current_user,n.oid,'USAGE')
 AND EXISTS (SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e ON e.oid=d.refobjid
   WHERE d.classid='pg_catalog.pg_class'::regclass AND d.objid=c.oid
   AND d.refclassid='pg_catalog.pg_extension'::regclass AND d.deptype='e'
   AND ((n.nspname='extensions' AND e.extname='pg_stat_statements') OR (n.nspname='cron' AND e.extname='pg_cron')))
 AND has_table_privilege(current_user,c.oid,'SELECT')
 AND NOT has_table_privilege(current_user,c.oid,'INSERT,UPDATE,TRUNCATE,REFERENCES,TRIGGER')
 AND NOT has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES')
 AND ((n.nspname='extensions' AND c.relname IN ('pg_stat_statements','pg_stat_statements_info')
     AND c.relkind='v' AND pg_get_userbyid(c.relowner)='postgres'
     AND NOT has_table_privilege(current_user,c.oid,'DELETE'))
   OR (n.nspname='cron' AND c.relname IN ('job','job_run_details') AND c.relkind='r'
     AND pg_get_userbyid(c.relowner)='supabase_admin' AND c.relrowsecurity
     AND (c.relname='job_run_details' OR NOT has_table_privilege(current_user,c.oid,'DELETE'))
     AND (SELECT count(*) FROM pg_catalog.pg_policy policy WHERE policy.polrelid=c.oid)=1
     AND EXISTS (SELECT 1 FROM pg_catalog.pg_policy policy WHERE policy.polrelid=c.oid
       AND policy.polcmd='*' AND policy.polroles=ARRAY[0::oid] AND policy.polpermissive
       AND policy.polwithcheck IS NULL
       AND regexp_replace(pg_get_expr(policy.polqual,policy.polrelid),'[()[:space:]]','','g')='username=CURRENT_USER')))
)"""
_PLATFORM_SEQUENCE_METADATA = """(
 n.nspname='cron' AND c.relname IN ('jobid_seq','runid_seq') AND c.relkind='S'
 AND pg_get_userbyid(c.relowner)='supabase_admin'
 AND NOT has_schema_privilege(current_user,n.oid,'USAGE')
 AND EXISTS (SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e ON e.oid=d.refobjid
   WHERE d.classid='pg_catalog.pg_class'::regclass AND d.objid=c.oid
   AND d.refclassid='pg_catalog.pg_extension'::regclass AND d.deptype='e' AND e.extname='pg_cron')
)"""

# Fixed catalog-only check. No user-supplied identifier ever enters SQL.
ROLE_AUDIT = """SELECT json_build_object('role', current_user,
 'safe', NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls)
 AND r.rolcanlogin
 AND NOT has_database_privilege(current_user,current_database(),'CREATE')
 AND NOT has_schema_privilege(current_user,'auth','USAGE')
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)
 -- Schema CREATE permits shadowing/privilege escalation through trusted code.
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
   AND has_schema_privilege(current_user,n.oid,'CREATE'))
 -- Raw relation/sequence grants remain conservative: OID calls and prebound
 -- wrappers can bypass namespace lookup even without schema USAGE.
 -- Whitelist only the two actual queue tables, never similarly named views.
 -- Column-only grants are independent of table-level grants and must be denied.
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
   AND c.relkind IN ('r','p','v','m','f')
   AND NOT (n.nspname='public' AND c.relname IN ('planning_jobs','planning_job_runtime') AND c.relkind IN ('r','p'))
   AND CASE WHEN c.relkind IN ('r','p','v','m','f') THEN
     NOT /*PLATFORM_TABLE_METADATA*/ AND (has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')) ELSE false END)
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND c.relkind='S'
   AND CASE WHEN c.relkind='S' THEN
     (has_sequence_privilege(current_user,c.oid,'USAGE,UPDATE') OR
      (has_sequence_privilege(current_user,c.oid,'SELECT') AND NOT /*PLATFORM_SEQUENCE_METADATA*/)) ELSE false END)
 -- PUBLIC EXECUTE on a SECURITY DEFINER is privilege escalation even when the
 -- role has no direct table grant. No implicit extension/function allowlist.
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
   AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE'))
 -- Reachable invoker wrappers can call prebound hidden objects. Only exact
 -- reviewed queue RPC signatures are allowed in reachable application schemas.
 AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
   AND has_schema_privilege(current_user,n.oid,'USAGE') AND has_function_privilege(current_user,p.oid,'EXECUTE')
   AND NOT (n.nspname='public' AND NOT p.prosecdef AND pg_get_userbyid(p.proowner) IN ('postgres','supabase_admin') AND coalesce(p.oid=ANY(ARRAY[
     to_regprocedure('public.enqueue_planning_job(jsonb)')::oid,
     to_regprocedure('public.claim_planning_job(uuid)')::oid,
     to_regprocedure('public.transition_planning_job(uuid,uuid,integer,text,text,jsonb,text,jsonb)')::oid,
     to_regprocedure('public.cancel_planning_job(uuid,uuid)')::oid,
     to_regprocedure('public.planning_queue_health()')::oid,
     to_regprocedure('public.purge_expired_planning_jobs()')::oid]),false)))
 )::text FROM pg_catalog.pg_roles r WHERE r.rolname=current_user""".replace('/*PLATFORM_TABLE_METADATA*/',_PLATFORM_TABLE_METADATA).replace('/*PLATFORM_SEQUENCE_METADATA*/',_PLATFORM_SEQUENCE_METADATA)


def invalid():
    return JobRepositoryError('INVALID_JOB_OPERATION', 400)


def uuid(value):
    try:
        if not isinstance(value, str): raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise invalid() from None


def json_value(value):
    if value is None: return None
    try:
        text = json.dumps(value, allow_nan=False, separators=(',', ':'))
        if len(text.encode()) > MAX_BYTES: raise ValueError()
        return text
    except (ValueError, TypeError, OverflowError):
        raise invalid() from None


class PlanningPostgresGateway:
    elevated = True

    def __init__(self, connection_url, *, enabled=False, expected_role='planning_queue_worker',
                 sslrootcert='system', connection_factory=None):
        if enabled is not True:
            raise JobRepositoryError('JOB_STORAGE_DISABLED')
        try:
            parsed = urlsplit(connection_url)
            if (parsed.scheme != 'postgresql' or parsed.query or parsed.fragment
                    or not re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com', parsed.hostname or '')
                    or parsed.port not in {5432, 6543} or parsed.path != '/postgres'
                    or not re.fullmatch(r'[a-z_][a-z0-9_]{2,62}', expected_role)
                    or expected_role in {'postgres','service_role','authenticated','anon','supabase_admin'}
                    or not re.fullmatch(re.escape(expected_role)+r'\.[a-z0-9]{10,40}', unquote(parsed.username or ''))
                    or not parsed.password or not isinstance(sslrootcert, str) or not sslrootcert):
                raise ValueError()
            self._kwargs = dict(host=parsed.hostname, port=parsed.port, dbname='postgres',
                user=unquote(parsed.username), password=unquote(parsed.password), sslmode='verify-full',
                sslrootcert=sslrootcert, connect_timeout=10, passfile=os.devnull,
                options='-csearch_path= -cstatement_timeout=10000 -clock_timeout=3000',
                application_name='travel-planning-queue', autocommit=False, prepare_threshold=None)
        except Exception:
            raise JobRepositoryError('JOB_STORAGE_CONFIGURATION_INVALID') from None
        self._factory, self._role = connection_factory, expected_role

    def _query(self, method, resource, params, payload):
        if method == 'GET' and resource == 'planning_jobs':
            if payload is not None or type(params) is not dict or params.get('limit') != '1': raise invalid()
            selector = 'id' if 'id' in params else 'request_id'
            if set(params) != {'user_id', selector, 'limit'}: raise invalid()
            values = []
            for field in ('user_id', selector):
                value = params[field]
                if not isinstance(value, str) or not value.startswith('eq.'): raise invalid()
                values.append(uuid(value[3:]))
            # selector is selected from two hardcoded names, never caller SQL.
            return f'SELECT row_to_json(q)::text FROM (SELECT * FROM public.planning_jobs WHERE user_id=%s::uuid AND {selector}=%s::uuid LIMIT 2) q', values
        if method != 'POST' or resource not in RPCS or params is not None or type(payload) is not dict:
            raise invalid()
        name, fields = RPCS[resource]
        if set(payload) != {key for key, _ in fields}: raise invalid()
        values = []
        for key, kind in fields:
            value = payload[key]
            if kind == 'uuid': value = uuid(value)
            elif kind == 'jsonb': value = json_value(value)
            elif kind == 'integer':
                if type(value) is not int or not 1 <= value <= 2147483647: raise invalid()
            elif value is not None and (not isinstance(value, str) or len(value) > 256 or any(ord(c)<32 for c in value)):
                raise invalid()
            values.append(value)
        placeholders = ','.join('%s::'+kind for _, kind in fields)
        return f'SELECT row_to_json(q)::text FROM public.{name}({placeholders}) q LIMIT 2', values

    async def _connect(self):
        if self._factory is not None:
            return await self._factory(**self._kwargs)
        try:
            from psycopg import AsyncConnection
        except ImportError:
            raise JobRepositoryError('JOB_SQL_DRIVER_UNAVAILABLE') from None
        return await AsyncConnection.connect(**self._kwargs)

    @staticmethod
    async def _rows(cursor):
        rows = await cursor.fetchmany(2)
        if len(rows)>1: raise JobRepositoryError()
        result=[]
        for row in rows:
            if not isinstance(row, (tuple, list)) or len(row)!=1 or not isinstance(row[0], str) or len(row[0].encode())>MAX_BYTES:
                raise JobRepositoryError()
            value=json.loads(row[0])
            if type(value) is not dict: raise JobRepositoryError()
            result.append(value)
        return result

    async def request(self, method, resource, *, params=None, payload=None):
        query, values = self._query(method, resource, params, payload)
        try:
            async with asyncio.timeout(15):
                async with await self._connect() as connection:
                    # Transaction-local settings also cover transaction poolers.
                    await connection.execute("SET LOCAL statement_timeout='10s'")
                    await connection.execute("SET LOCAL lock_timeout='3s'")
                    audit = await self._rows(await connection.execute(ROLE_AUDIT))
                    if audit != [{'role': self._role, 'safe': True}]:
                        raise JobRepositoryError('JOB_WORKER_CONTEXT_REQUIRED', 403)
                    rows = await self._rows(await connection.execute(query, values))
                # Context exit confirms COMMIT. Ambiguous commit errors propagate
                # sanitized; the repository reconciles identity without re-insert.
                return rows
        except JobRepositoryError:
            raise
        except Exception as error:
            if (resource=='rpc/enqueue_planning_job' and getattr(error,'sqlstate',None)=='P0001'
                and getattr(getattr(error,'diag',None),'message_primary',None)=='Planning admission limit reached'):
                raise JobRepositoryError('JOB_ADMISSION_REJECTED',429) from None
            raise JobRepositoryError() from None
