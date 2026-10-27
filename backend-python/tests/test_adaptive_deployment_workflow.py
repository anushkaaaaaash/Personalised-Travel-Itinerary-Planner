from pathlib import Path
import tomllib
ROOT=Path(__file__).resolve().parents[2]

def test_sqlite_rollout_is_explicit_staged_and_no_ssh_or_new_credentials():
    workflow=(ROOT/'.github/workflows/fly-deploy.yml').read_text()
    assert 'options: [stage, upgrade, activate]' in workflow
    assert workflow.index('--upgrade-grounded-store')<workflow.index('--check-grounded-store')<workflow.index('--env ADAPTIVE_PLANNING_ENABLED=true')
    assert workflow.index('--verify\n')<workflow.index('Deploy one Machine with explicit processing state')
    assert '--verify-after-deploy' in workflow and '--initialize-store' not in workflow
    assert workflow.index('--check-quiescence') < workflow.index('Deploy one Machine with explicit processing state')
    assert '--ha=false --strategy immediate' in workflow
    assert 'fly ssh' not in workflow and 'secrets set' not in workflow
    assert 'persist-credentials: false' in workflow and 'contents: read' in workflow
    assert 'cancel-in-progress: false' in workflow
    stage=workflow.split('stage)',1)[1].split(';;',1)[0]
    for name in ('ADAPTIVE_PLANNING_ENABLED','PLANNING_JOBS_ENABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_STREAMING_ENABLED'):
        assert f'--env {name}=false' in stage
    assert '--env ADAPTIVE_RESEARCH_MAX_TOOLS=6' in workflow
    config=tomllib.loads((ROOT/'fly.toml').read_text())
    assert config['env']['ADAPTIVE_PLANNING_ENABLED']=='false'
    assert config['env']['PLANNING_WORKER_TRANSPORT']=='sqlite'
    assert config['mounts']==[{'source':'planner_checkpoints','destination':'/data','scheduled_snapshots':False}]
