"""Explicit schema-v2 rollout; no migration, model call or fallback on startup."""
from .adaptive_activation import approved

RESEARCH_APPROVALS=('ADAPTIVE_RESEARCH_COST_APPROVED','ADAPTIVE_RESEARCH_SCHEMA_VERIFIED','ADAPTIVE_RESEARCH_WORKER_VERIFIED')

def research_approved(config):
    return (approved(config) and config.get('PLANNING_WORKER_TRANSPORT')=='sqlite'
        and config.get('ADAPTIVE_RESEARCH_ENABLED')=='true'
        and config.get('ADAPTIVE_RESEARCH_MAX_TOOLS','6')=='6'
        and all(config.get(key)=='true' for key in RESEARCH_APPROVALS))

def build_grounded(config,*,gateway_factory=None,client_factory=None,research_client_factory=None):
    if not research_approved(config):raise RuntimeError('Grounded planning approvals are incomplete.')
    from .adaptive_sqlite_runtime import verify_volume
    from .revision_sqlite import RevisionSQLiteGateway
    from .revision_repository import RevisionRepository
    from .revision_worker import RevisionWorker
    from .section_repository import SectionCheckpointRepository
    from .research_repository import ResearchCheckpointRepository
    from .adaptive_worker import AdaptivePlanningWorker
    from .adaptive_research_worker import AdaptiveResearchWorker,GroundedPlanningWorker
    from .adaptive_research import BackgroundResearchClient
    from .openai_background import BackgroundActivation,OpenAIBackgroundClient
    from .openai_output_stream import OpenAIOutputStreamClient
    from .section_preview_store import SectionPreviewStore
    from .grounded_coordinator import GroundedCoordinator
    path=verify_volume()
    gateway=(gateway_factory or RevisionSQLiteGateway)(path,enabled=True,research_enabled=True)
    plans=SectionCheckpointRepository(gateway,enabled=True)
    research=ResearchCheckpointRepository(gateway,enabled=True)
    activation=BackgroundActivation(enabled=True,temporary_retention_approved=True)
    streaming=config.get('ADAPTIVE_STREAMING_ENABLED')=='true'
    client=(client_factory or (OpenAIOutputStreamClient if streaming else OpenAIBackgroundClient))(
        config.get('OPENAI_API_KEY',''),activation=activation)
    research_client=(research_client_factory or BackgroundResearchClient)(config.get('OPENAI_API_KEY',''),
        activation=activation,cost_approved=True)
    preview=SectionPreviewStore(gateway,enabled=True) if streaming else None
    section_worker=AdaptivePlanningWorker(plans,client,enabled=True,preview_store=preview)
    revisions=RevisionRepository(gateway,enabled=True) if getattr(gateway,"supports_revisions",False) else None
    revision_worker=RevisionWorker(revisions,client,enabled=True) if revisions is not None else None
    worker=GroundedPlanningWorker(section_worker,AdaptiveResearchWorker(research,plans,research_client,enabled=True),revision_worker)
    return GroundedCoordinator(plans,worker,research_repository=research,revision_repository=revisions,enabled=True,
        run_allowance=int(config.get('ADAPTIVE_RUN_ALLOWANCE','12')),maintenance=gateway.purge_expired,
        streaming_enabled=streaming)
