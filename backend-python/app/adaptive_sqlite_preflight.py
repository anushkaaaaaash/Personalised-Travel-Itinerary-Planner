"""Explicit volume initialization/expiry cleanup check; no model or job creation."""
import argparse
import asyncio
import json
import os
from .planning_repository import JobRepositoryError
from .section_repository import SectionCheckpointRepository
from .adaptive_sqlite_runtime import verify_volume, prepare_new_directory

async def preflight(configuration=None, *, initialize=False, gateway_factory=None):
    config=os.environ if configuration is None else configuration
    if config.get('ADAPTIVE_PREFLIGHT_APPROVED')!='true': return {'ready':False,'code':'PREFLIGHT_DISABLED'}
    if initialize and config.get('ADAPTIVE_SQLITE_INITIALIZE_APPROVED')!='true': return {'ready':False,'code':'INITIALIZATION_DISABLED'}
    gateway=None
    try:
        from .adaptive_sqlite import AdaptiveSQLiteGateway
        path=prepare_new_directory() if initialize else verify_volume()
        gateway=(gateway_factory or AdaptiveSQLiteGateway)(path,enabled=True,initialize=initialize)
        verify_volume()
        await gateway.purge_expired()
        await SectionCheckpointRepository(gateway,enabled=True).verify_ready()
        return {'ready':True,'code':'READY'}
    except JobRepositoryError as error:
        safe={'SQLITE_DIRECTORY_CREATE_DENIED','SQLITE_PRIVILEGE_DROP_FAILED','SQLITE_VOLUME_UNVERIFIED','SQLITE_STORAGE_UNVERIFIED','SQLITE_ALREADY_INITIALIZED','SECTION_STORAGE_UNCONFIRMED','SECTIONS_SCHEMA_NOT_READY','SECTION_RESOURCE_LIMIT'}
        return {'ready':False,'code':error.code if error.code in safe else 'PREFLIGHT_FAILED'}
    except Exception: return {'ready':False,'code':'PREFLIGHT_FAILED'}
    finally:
        if gateway is not None:
            try: await gateway.close()
            except Exception: pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Verify approved local checkpoint storage.')
    parser.add_argument('--initialize',action='store_true');args=parser.parse_args()
    result=asyncio.run(preflight(initialize=args.initialize));print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result['ready'] else 1)
