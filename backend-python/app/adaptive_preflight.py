"""Explicit read-only startup check, usable before enabling adaptive generation.

Reads only the already-provisioned worker connection from process environment;
never reads dotenv, accepts user SQL, creates jobs, or calls a model provider.
"""
import asyncio
import json
import os
from .adaptive_postgres import AdaptivePostgresGateway
from .section_repository import SectionCheckpointRepository
from .planning_repository import JobRepositoryError

async def preflight(configuration=None, *, gateway_factory=None):
    config=os.environ if configuration is None else configuration
    if config.get('ADAPTIVE_PREFLIGHT_APPROVED')!='true':
        return {'ready':False,'code':'PREFLIGHT_DISABLED'}
    try:
        gateway=(gateway_factory or AdaptivePostgresGateway)(config.get('PLANNING_DATABASE_URL',''),
            enabled=True,sslrootcert=config.get('PLANNING_DB_SSLROOTCERT','system'))
        await SectionCheckpointRepository(gateway,enabled=True).verify_ready()
        return {'ready':True,'code':'READY'}
    except JobRepositoryError as error:
        code=error.code if error.code in {'JOB_STORAGE_CONFIGURATION_INVALID','JOB_SQL_DRIVER_UNAVAILABLE',
            'JOB_WORKER_CONTEXT_REQUIRED','JOB_STORAGE_UNCONFIRMED','SECTIONS_SCHEMA_NOT_READY'} else 'PREFLIGHT_FAILED'
        return {'ready':False,'code':code}
    except Exception:
        return {'ready':False,'code':'PREFLIGHT_FAILED'}

if __name__=='__main__':
    result=asyncio.run(preflight())
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result['ready'] else 1)
