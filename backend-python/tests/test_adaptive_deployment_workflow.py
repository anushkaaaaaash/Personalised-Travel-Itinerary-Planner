from pathlib import Path
import tomllib
ROOT=Path(__file__).resolve().parents[2]

def test_sqlite_rollout_is_explicit_staged_and_no_ssh_or_new_credentials():
    workflow=(ROOT/'.github/workflows/fly-deploy.yml').read_text()
    assert 'options: [stage, initialize, activate]' in workflow
    assert workflow.index('--preflight-store')<workflow.index('--env ADAPTIVE_PLANNING_ENABLED=true')
    assert workflow.index('--verify\n')<workflow.index('Deploy one Machine with explicit processing state')
    assert '--verify-attached' in workflow and '--initialize-store' in workflow
    assert '--ha=false --strategy immediate' in workflow
    assert 'fly ssh' not in workflow and 'secrets set' not in workflow
    assert 'persist-credentials: false' in workflow and 'contents: read' in workflow
    assert 'cancel-in-progress: false' in workflow
    config=tomllib.loads((ROOT/'fly.toml').read_text())
    assert config['env']['ADAPTIVE_PLANNING_ENABLED']=='false'
    assert config['env']['PLANNING_WORKER_TRANSPORT']=='sqlite'
    assert config['mounts']==[{'source':'planner_checkpoints','destination':'/data','scheduled_snapshots':False}]
