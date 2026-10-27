"""Fail-closed production composition; no files, network or activation on import."""
import os
from .planning_coordinator import DurablePlanningCoordinator

REQUIRED_APPROVALS = ('OPENAI_BACKGROUND_RETENTION_APPROVED', 'PLANNING_DATA_RETENTION_APPROVED',
    'PLANNING_SCHEMA_VERIFIED', 'PLANNING_CLEANUP_VERIFIED', 'PLANNING_WORKER_VERIFIED', 'PLANNING_WORKER_CREDENTIAL_APPROVED', 'PLANNING_SCOPED_ROLE_VERIFIED')


def activation_approved(configuration=None):
    config=os.environ if configuration is None else configuration
    return (config.get('PLANNING_JOBS_ENABLED')=='true'
        and all(config.get(name)=='true' for name in REQUIRED_APPROVALS)
        and config.get('PLANNING_PURGE_JOB_NAME')=='purge-planning-jobs'
        and config.get('PLANNING_WORKER_TRANSPORT')=='postgres')


def build_production_planning(configuration=None, *, gateway_factory=None, client_factory=None):
    config=os.environ if configuration is None else configuration
    if config.get('PLANNING_JOBS_ENABLED')!='true':return None
    if not activation_approved(config):
        raise RuntimeError('Durable planning approval and verification gates are incomplete.')
    from .planning_repository import DurablePlanningRepository
    from .planning_postgres import PlanningPostgresGateway
    from .openai_background import OpenAIBackgroundClient, BackgroundActivation
    from .planning_worker import PlanningWorker
    try:
        gateway=(gateway_factory or PlanningPostgresGateway)(config.get('PLANNING_DATABASE_URL',''),enabled=True,
            sslrootcert=config.get('PLANNING_DB_SSLROOTCERT','system'))
        repository=DurablePlanningRepository(gateway,enabled=True)
        provider=(client_factory or OpenAIBackgroundClient)(config.get('OPENAI_API_KEY',''),
            activation=BackgroundActivation(enabled=True,temporary_retention_approved=True))
        return DurablePlanningCoordinator(repository,PlanningWorker(repository,provider,enabled=True),enabled=True,require_health=True)
    except Exception:
        raise RuntimeError('Durable planning server configuration is incomplete.') from None


def route_enabled(engine):
    from .planning_routes import preview_enabled
    if preview_enabled():return engine is not None
    return isinstance(engine,DurablePlanningCoordinator) and engine.require_health and activation_approved()
