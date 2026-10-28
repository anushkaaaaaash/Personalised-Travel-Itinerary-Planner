"""Name-only guard against secret overrides of reviewed processing settings."""
import json
import re
import subprocess

CONTROL_NAMES={'ADAPTIVE_PLANNING_ENABLED','PLANNING_JOBS_ENABLED','PLANNING_WORKER_TRANSPORT','ADAPTIVE_RUN_ALLOWANCE',
 'OPENAI_BACKGROUND_RETENTION_APPROVED','PLANNING_DATA_RETENTION_APPROVED','ADAPTIVE_SCHEMA_VERIFIED',
 'ADAPTIVE_CLEANUP_VERIFIED','ADAPTIVE_WORKER_VERIFIED','ADAPTIVE_RESOURCE_POLICY_APPROVED',
 'ADAPTIVE_SQLITE_STORAGE_APPROVED','ADAPTIVE_SQLITE_VOLUME_VERIFIED','ADAPTIVE_SQLITE_SINGLE_MACHINE_VERIFIED',
 'ADAPTIVE_SQLITE_SNAPSHOTS_DISABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_RESEARCH_MAX_TOOLS',
 'ADAPTIVE_RESEARCH_COST_APPROVED','ADAPTIVE_RESEARCH_SCHEMA_VERIFIED','ADAPTIVE_RESEARCH_WORKER_VERIFIED',
 'ADAPTIVE_STREAMING_ENABLED','ADAPTIVE_SAVED_TRIPS_ENABLED','ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED'}

def verify_names(rows):
    if type(rows) is not list:raise ValueError('unverified')
    for row in rows:
        if type(row) is not dict:raise ValueError('unverified')
        name=row.get('Name',row.get('name'))
        if type(name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name):raise ValueError('unverified')
        if name in CONTROL_NAMES:raise ValueError('override')

def main():
    try:
        result=subprocess.run(['flyctl','secrets','list','--app','personalised-travel-itinerary-planner','--json'],capture_output=True,text=True,timeout=60)
        if result.returncode or len(result.stdout)>262144:raise ValueError('unverified')
        verify_names(json.loads(result.stdout))
    except Exception:
        print('Processing override names could not be verified absent; stopped. No secret values were requested.')
        return 1
    print('Verified no secret overrides of reviewed processing controls. No secret values were requested.')
    return 0
if __name__=='__main__':raise SystemExit(main())
