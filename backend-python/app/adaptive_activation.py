"""Explicit future activation; defaults never open a connection or provider call."""
import os
from .adaptive_coordinator import AdaptiveCoordinator

APPROVALS = ('OPENAI_BACKGROUND_RETENTION_APPROVED','PLANNING_DATA_RETENTION_APPROVED',
    'PLANNING_WORKER_CREDENTIAL_APPROVED','PLANNING_SCOPED_ROLE_VERIFIED',
    'ADAPTIVE_SCHEMA_VERIFIED','ADAPTIVE_CLEANUP_VERIFIED','ADAPTIVE_WORKER_VERIFIED','ADAPTIVE_RESOURCE_POLICY_APPROVED')


def approved(configuration=None):
    config = os.environ if configuration is None else configuration
    return (config.get('ADAPTIVE_PLANNING_ENABLED') == 'true'
        and config.get('PLANNING_JOBS_ENABLED') != 'true'
        and config.get('PLANNING_WORKER_TRANSPORT') == 'postgres'
        and config.get('ADAPTIVE_PURGE_JOB_NAME') == 'adaptive-section-retention'
        and all(config.get(key) == 'true' for key in APPROVALS))


def route_enabled(engine):
    if not isinstance(engine, AdaptiveCoordinator): return False
    from .configuration import hosted_environment
    if not hosted_environment() and os.getenv('APP_MODE','local').lower()=='local' and os.getenv('ADAPTIVE_PLANNING_PREVIEW')=='true':
        return True
    return engine.require_health and approved()


def build_production_adaptive(configuration=None, *, gateway_factory=None, client_factory=None):
    config = os.environ if configuration is None else configuration
    if config.get('ADAPTIVE_PLANNING_ENABLED') != 'true': return None
    if not approved(config): raise RuntimeError('Adaptive planning approvals and resource policy are incomplete.')
    from .adaptive_postgres import AdaptivePostgresGateway
    from .section_repository import SectionCheckpointRepository
    from .adaptive_worker import AdaptivePlanningWorker
    from .openai_background import OpenAIBackgroundClient, BackgroundActivation
    try:
        gateway = (gateway_factory or AdaptivePostgresGateway)(config.get('PLANNING_DATABASE_URL',''),enabled=True,
            sslrootcert=config.get('PLANNING_DB_SSLROOTCERT','system'))
        repository = SectionCheckpointRepository(gateway,enabled=True)
        client = (client_factory or OpenAIBackgroundClient)(config.get('OPENAI_API_KEY',''),
            activation=BackgroundActivation(enabled=True,temporary_retention_approved=True))
        return AdaptiveCoordinator(repository,AdaptivePlanningWorker(repository,client,enabled=True),enabled=True,
            run_allowance=int(config.get('ADAPTIVE_RUN_ALLOWANCE','12')))
    except Exception:
        raise RuntimeError('Adaptive planning configuration is incomplete.') from None
