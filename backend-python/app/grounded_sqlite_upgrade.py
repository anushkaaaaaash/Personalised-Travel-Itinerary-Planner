"""Explicit, atomic local schema-v2 provisioning; never run by gateway startup."""
from pathlib import Path
import os
from .adaptive_sqlite_runtime import verify_volume,DATABASE,prepare_existing_storage_user
import sqlite3
from .research_sqlite import _RESEARCH_SCHEMA
from .revision_repository import REVISION_SCHEMA,revision_tables_ready
from .planning_repository import JobRepositoryError
from .adaptive_sqlite import _error


def upgrade_grounded_schema(path,*,approved=False):
    if approved is not True:_error('GROUNDED_MIGRATION_NOT_APPROVED',403)
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():_error('SECTIONS_STORAGE_UNAVAILABLE',503)
    c=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=5)
    try:
        c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
        version=c.execute('PRAGMA user_version').fetchone()[0]
        if version not in (1,2):_error('GROUNDED_SCHEMA_NOT_READY',503)
        for table,statuses in (('plans',('active','paused','completed','cancelled')),('sections',('queued','submitting','running','succeeded','failed','submission_unknown','cancelled'))):
            marks=','.join('?' for _ in statuses)
            if c.execute("SELECT COUNT(*) FROM "+table+" WHERE json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ("+marks+")",statuses).fetchone()[0]:_error('GROUNDED_SCHEMA_NOT_READY',503)
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version==2 and {'research_jobs','revision_jobs','revision_controls'}<=tables:
            if not revision_tables_ready(c):_error('GROUNDED_SCHEMA_NOT_READY',503)
            c.commit();return
        if c.execute("SELECT 1 FROM plans WHERE json_extract(data,'$.status')='active'").fetchone() or c.execute("SELECT 1 FROM sections WHERE json_extract(data,'$.status') IN ('queued','submitting','running','submission_unknown')").fetchone():_error('PLANNING_IN_PROGRESS',409)
        if version==2:
            if 'research_jobs' not in tables or {'revision_jobs','revision_controls'}&tables:_error('GROUNDED_SCHEMA_NOT_READY',503)
            if c.execute("SELECT 1 FROM research_jobs WHERE json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ('queued','submitting','running','succeeded','failed','submission_unknown','cancelled')").fetchone():_error('GROUNDED_SCHEMA_NOT_READY',503)
            if c.execute("SELECT 1 FROM research_jobs WHERE json_extract(data,'$.status') IN ('queued','submitting','running','submission_unknown')").fetchone():_error('PLANNING_IN_PROGRESS',409)
        for statement in ((_RESEARCH_SCHEMA if version==1 else '')+REVISION_SCHEMA).split(';'):
            if statement.strip():c.execute(statement)
        c.execute('PRAGMA user_version=2');c.execute('UPDATE runtime SET version=2,last_purge=NULL WHERE id=1');c.commit()
    except JobRepositoryError:c.rollback();raise
    except Exception:c.rollback();_error('GROUNDED_MIGRATION_UNCONFIRMED',503)
    finally:c.close()


def check_grounded_schema(path):
    """Read-only readiness; no runtime table update, cleanup or schema repair."""
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():_error('SECTIONS_STORAGE_UNAVAILABLE',503)
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=5)
    try:
        version=c.execute('PRAGMA user_version').fetchone()[0]
        expected={'research_jobs':{'id','plan_id','user_id','request_id','run_index','phase','data'},
            'revision_jobs':{'id','plan_id','user_id','request_id','root_id','data'},
            'revision_controls':{'root_id','user_id','request_id'}}
        ready=version==2 and all({row[1] for row in c.execute('PRAGMA table_info('+table+')')}==columns for table,columns in expected.items())
        if not ready or not revision_tables_ready(c) or c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():_error('GROUNDED_SCHEMA_NOT_READY',503)
        return {'schemaVersion':2,'researchReady':True,'revisionReady':True}
    except JobRepositoryError:raise
    except Exception:_error('GROUNDED_SCHEMA_NOT_READY',503)
    finally:c.close()


def main(argv=None, *, configuration=None):
    import argparse
    import json
    parser=argparse.ArgumentParser(description='Explicit grounded schema provisioning; no paid calls.')
    parser.add_argument('--path',required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--approve',action='store_true');mode.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    try:
        config=os.environ if configuration is None else configuration
        if args.path!=str(DATABASE) or verify_volume()!=str(DATABASE):_error('SQLITE_STORAGE_UNVERIFIED',503)
        if args.approve:
            if any(config.get(key)!='false' for key in ('ADAPTIVE_PLANNING_ENABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_STREAMING_ENABLED')) or config.get('PLANNING_JOBS_ENABLED')=='true':_error('GROUNDED_STAGE_REQUIRED',409)
            prepare_existing_storage_user()
            upgrade_grounded_schema(args.path,approved=True)
        if args.check:prepare_existing_storage_user()
        verify_volume();check_grounded_schema(args.path)
        print(json.dumps({'ready':True,'code':'READY'},sort_keys=True,separators=(',',':')))
        return 0
    except JobRepositoryError as error:
        allowed={'GROUNDED_MIGRATION_NOT_APPROVED','SECTIONS_STORAGE_UNAVAILABLE','GROUNDED_SCHEMA_NOT_READY','PLANNING_IN_PROGRESS','GROUNDED_MIGRATION_UNCONFIRMED','SQLITE_VOLUME_UNVERIFIED','SQLITE_STORAGE_UNVERIFIED','GROUNDED_STAGE_REQUIRED','SQLITE_PRIVILEGE_DROP_FAILED'}
        print(json.dumps({'ready':False,'code':error.code if error.code in allowed else 'GROUNDED_MIGRATION_UNCONFIRMED'},sort_keys=True,separators=(',',':')))
        return 1

if __name__=='__main__':raise SystemExit(main())
