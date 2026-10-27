"""Owner-scoped durable research intent API; no provider access or retries."""
from .planning_repository import JobRepositoryError, identity
from .section_repository import _bounded_json

class ResearchCheckpointRepository:
    def __init__(self,gateway,*,enabled=False):
        if enabled is not True or getattr(gateway,'supports_research',False) is not True:
            raise JobRepositoryError('RESEARCH_DISABLED',503)
        self.gateway=gateway

    async def _call(self,operation,owner,payload,*,optional=False):
        owner=identity(owner)
        try:
            rows=await self.gateway.research_request(operation,{'owner':owner,**payload})
            if type(rows) is not list or len(rows)>1 or any(type(r) is not dict or r.get('user_id')!=owner for r in rows):raise ValueError()
            _bounded_json(rows,131072)
            if not rows:
                if optional:return None
                raise JobRepositoryError('RESEARCH_NOT_FOUND_OR_CONFLICT',409)
            return rows[0]
        except JobRepositoryError:raise
        except Exception:raise JobRepositoryError('RESEARCH_STORAGE_UNCONFIRMED',503) from None

    async def request_research(self,owner,section,lease,version,kind):
        return await self._call('request_research',owner,{'section':identity(section),'lease':identity(lease),'expected_version':version,'kind':kind})

    async def continue_researched(self,owner,plan):
        return await self._call('continue_researched',owner,{'plan':identity(plan)},optional=True)

    async def reserve(self,owner,plan,request_id,query,*,phase='initial'):
        return await self._call('reserve',owner,{'plan':identity(plan),'request_id':identity(request_id),'phase':phase,'query':query})

    async def get(self,owner,research):
        return await self._call('get',owner,{'research':identity(research)})

    async def latest(self,owner,plan):
        return await self._call('latest',owner,{'plan':identity(plan)},optional=True)

    async def claim_next(self,worker):
        try:
            rows=await self.gateway.research_request('claim_next',{'worker':identity(worker)})
            if type(rows) is not list or len(rows)>1:raise ValueError()
            if not rows:return None
            if type(rows[0]) is not dict:raise ValueError()
            identity(rows[0]['user_id']);_bounded_json(rows,131072)
            return rows[0]
        except JobRepositoryError:raise
        except Exception:raise JobRepositoryError('RESEARCH_STORAGE_UNCONFIRMED',503) from None

    async def transition(self,owner,research,lease,version,status,*,provider_response_id=None,error_code=None,sourcepack=None):
        if type(version) is not int or version<1 or status not in {'submitting','running','succeeded','failed','submission_unknown'}:
            raise JobRepositoryError('RESEARCH_TRANSITION_INVALID',400)
        return await self._call('transition',owner,{'research':identity(research),'lease':identity(lease),'expected_version':version,
            'next_status':status,'response_id':provider_response_id,'failure_code':error_code,'sourcepack':sourcepack})

    async def verify_ready(self):
        try:
            rows=await self.gateway.research_request('health',{})
            if rows!=[{'schema_version':2,'research_version':1,'cleanup_fresh':True}]:raise ValueError()
        except Exception:raise JobRepositoryError('RESEARCH_SCHEMA_NOT_READY',503) from None
