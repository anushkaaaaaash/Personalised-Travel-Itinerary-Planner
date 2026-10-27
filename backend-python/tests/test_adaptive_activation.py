import pytest
from app.adaptive_activation import approved,build_production_adaptive,APPROVALS


def configuration():
    return {**dict.fromkeys(APPROVALS,'true'),'ADAPTIVE_PLANNING_ENABLED':'true',
        'PLANNING_WORKER_TRANSPORT':'postgres','ADAPTIVE_PURGE_JOB_NAME':'adaptive-section-retention'}


def test_disabled_makes_no_credentials_or_network_access():
    assert build_production_adaptive({}) is None
    assert not approved({})

@pytest.mark.parametrize('flag',APPROVALS)
def test_all_approvals_required(flag):
    config=configuration();config[flag]='false'
    assert not approved(config)
    with pytest.raises(RuntimeError):build_production_adaptive(config)


def test_legacy_background_cannot_have_independent_paid_capacity():
    config=configuration();assert approved(config)
    config['PLANNING_JOBS_ENABLED']='true';assert not approved(config)
