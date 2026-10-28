"""Native local-only migration compatibility with a non-superuser hosted-like actor.
No live project is contacted. A fresh child database isolates every schema write.
"""
import json,os
from pathlib import Path
from urllib.parse import urlparse,unquote
from uuid import uuid4
import pytest
from test_adaptive_archive_postgres import example

@pytest.fixture
def restricted_migration():
    raw=os.environ.get('PLANNING_SQL_TEST_DATABASE_URL','')
    if not raw:pytest.skip('Explicit disposable loopback PostgreSQL URL required')
    try:
        p=urlparse(raw)
        if not (p.scheme in {'postgres','postgresql'} and p.hostname in {'localhost','127.0.0.1'} and p.path=='/planning_queue_test' and p.username=='postgres' and not p.query and not p.fragment):raise ValueError()
        params=dict(host=p.hostname,hostaddr='127.0.0.1',port=p.port or 5432,dbname='planning_queue_test',user='postgres',password=unquote(p.password or ''),connect_timeout=5)
    except Exception:pytest.fail('Refusing non-disposable PostgreSQL target',pytrace=False)
    import psycopg
    from psycopg import sql
    suffix=uuid4().hex[:12];database='archive_migration_'+suffix;actor='archive_actor_'+suffix;auth_owner='archive_auth_'+suffix
    created=False
    with psycopg.connect(**params,autocommit=True) as admin:
        assert admin.execute('select current_database(),host(inet_server_addr())').fetchone()==('planning_queue_test','127.0.0.1')
        assert admin.execute("select count(*) from pg_roles where rolname='adaptive_archive_rpc'").fetchone()[0]==0
        try:
            admin.execute(sql.SQL('create role {} nologin nosuperuser createrole createdb bypassrls').format(sql.Identifier(actor)))
            admin.execute(sql.SQL('create role {} nologin nosuperuser').format(sql.Identifier(auth_owner)))
            admin.execute(sql.SQL('create database {} owner {}').format(sql.Identifier(database),sql.Identifier(actor)));created=True
            child={**params,'dbname':database}
            with psycopg.connect(**child,autocommit=True) as conn:
                assert conn.execute('select current_database(),host(inet_server_addr())').fetchone()==(database,'127.0.0.1')
                conn.execute("do $$begin if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if; if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if; end$$")
                conn.execute('revoke create on schema public from public')
                conn.execute(sql.SQL('create schema auth authorization {}').format(sql.Identifier(auth_owner)))
                conn.execute('create table auth.users(id uuid primary key)')
                conn.execute(sql.SQL('alter table auth.users owner to {}').format(sql.Identifier(auth_owner)))
                conn.execute("create function auth.uid() returns uuid language sql stable as $$select coalesce(nullif(current_setting('request.jwt.claim.sub',true),''),(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub'))::uuid$$")
                conn.execute(sql.SQL('alter function auth.uid() owner to {}').format(sql.Identifier(auth_owner)))
                conn.execute('revoke all on schema auth from public')
                conn.execute(sql.SQL('grant usage on schema auth to {}').format(sql.Identifier(actor)))
                conn.execute(sql.SQL('grant references(id) on auth.users to {}').format(sql.Identifier(actor)))
            yield psycopg,sql,child,actor
        finally:
            if created:admin.execute(sql.SQL('drop database {} with (force)').format(sql.Identifier(database)))
            # All role object grants were confined to that fresh child database.
            admin.execute('drop role if exists adaptive_archive_rpc')
            admin.execute(sql.SQL('drop role if exists {}').format(sql.Identifier(actor)))
            admin.execute(sql.SQL('drop role if exists {}').format(sql.Identifier(auth_owner)))


def test_non_superuser_migration_removes_all_temporary_privileges(restricted_migration):
    psycopg,sql,params,actor=restricted_migration
    source=Path(__file__).resolve().parents[2]/'docs/adaptive_saved_archive_REVIEW_ONLY.sql'
    with psycopg.connect(**params,autocommit=True) as conn:
        conn.execute(sql.SQL('set role {}').format(sql.Identifier(actor)))
        conn.execute("set createrole_self_grant=''")
        assert conn.execute('select rolsuper,rolcreaterole from pg_roles where rolname=current_user').fetchone()==(False,True)
        assert conn.execute("select has_schema_privilege(current_user,'auth','USAGE WITH GRANT OPTION'),has_function_privilege(current_user,'auth.uid()','EXECUTE WITH GRANT OPTION')").fetchone()==(False,False)
        # Prior migration fails at owner transfer without temporary SET membership.
        conn.execute('begin')
        try:
            conn.execute('create role archive_old_transfer nologin')
            conn.execute('create function public.archive_old_transfer() returns integer language sql as $$select 1$$')
            with pytest.raises(psycopg.Error) as old:conn.execute('alter function public.archive_old_transfer() owner to archive_old_transfer')
            assert old.value.sqlstate=='42501'
        finally:conn.execute('rollback')
        # A failure before COMMIT rolls back schema, role and temporary grants.
        injected=source.read_text().rsplit('commit;',1)[0]+'select 1/0; commit;'
        try:
            with pytest.raises(psycopg.Error) as rollback:conn.execute(injected,prepare=False)
            assert rollback.value.sqlstate=='22012'
        finally:conn.execute('rollback')
        assert conn.execute("select to_regnamespace('adaptive_archive') is null and not exists(select 1 from pg_roles where rolname='adaptive_archive_rpc')").fetchone()[0] is True
        conn.execute(source.read_text(),prepare=False)
        assert conn.execute('show createrole_self_grant').fetchone()[0]==''
        members=conn.execute("select member::regrole::text,grantor::regrole::text,admin_option,inherit_option,set_option from pg_auth_members where roleid='adaptive_archive_rpc'::regrole").fetchall()
        # PG16+ retains its automatic creator ADMIN-only edge. The temporary
        # SET edge is gone; neither effective SET nor inherited rights survive.
        bootstrap=conn.execute('select rolname from pg_roles where oid=10').fetchone()[0]
        assert members==[(actor,bootstrap,True,False,False)],members
        assert conn.execute("select pg_has_role(current_user,'adaptive_archive_rpc','SET'),pg_has_role(current_user,'adaptive_archive_rpc','USAGE')").fetchone()==(False,False)
        assert conn.execute("select pg_has_role('anon','adaptive_archive_rpc','MEMBER'),pg_has_role('authenticated','adaptive_archive_rpc','MEMBER')").fetchone()==(False,False)
        conn.execute('reset role')
        assert conn.execute("select has_schema_privilege('adaptive_archive_rpc','public','CREATE'),has_schema_privilege('adaptive_archive_rpc','auth','USAGE')").fetchone()==(False,False)
        assert conn.execute("select rolcanlogin,rolsuper,rolbypassrls,rolcreaterole from pg_roles where rolname='adaptive_archive_rpc'").fetchone()==(False,False,False,False)
        assert conn.execute("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='adaptive_archive' and c.relkind='r' and c.relrowsecurity and c.relforcerowsecurity and c.relowner<>'adaptive_archive_rpc'::regrole").fetchone()[0]==3
        assert conn.execute("select has_function_privilege('anon','public.adaptive_saved_archive(text,jsonb)','EXECUTE'),has_function_privilege('authenticated','public.adaptive_saved_archive(text,jsonb)','EXECUTE')").fetchone()==(False,True)
        owner=str(uuid4());other=str(uuid4());conn.execute('insert into auth.users values(%s::uuid),(%s::uuid)',(owner,other))
        request,_=example()
        # Both verified JWT GUC layouts work without auth schema access.
        conn.execute('begin');conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claim.sub','',true)")
        conn.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({'sub':owner,'user_metadata':{'sub':other}}),))
        result=conn.execute("select public.adaptive_saved_archive('begin',%s::jsonb)",(json.dumps(request),)).fetchone()[0]
        assert result['owner']==owner
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(other,))
        # Direct sub takes precedence over claims JSON, exactly like auth.uid().
        assert conn.execute("select public.adaptive_saved_archive('lookup',%s::jsonb)",(json.dumps({'requestId':request['requestId']}),)).fetchone()[0] is None
        conn.execute('rollback')
        conn.execute('begin');conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claim.sub','',true)");conn.execute("select set_config('request.jwt.claims','',true)")
        with pytest.raises(psycopg.Error) as absent:conn.execute("select public.adaptive_saved_archive('list','{\"offset\":0}'::jsonb)")
        assert absent.value.diag.message_primary=='SAVED_ADAPTIVE_FORBIDDEN'
        conn.execute('rollback')
