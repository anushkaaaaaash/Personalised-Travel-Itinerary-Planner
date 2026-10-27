"""Private, lease-bound draft stream CAS. No provider requests or acceptance.

The gateway derives draft days from authoritative stored preferences. Each write
commits text and cursor together; callers resume only from the returned cursor.
Early provider identity must first be persisted by the existing transition, then
its released lease reclaimed. Terminal section writes erase all preview state.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date
import re
from .adaptive_day_preview import preview_days
from .adaptive_planning import SectionSpec, AdaptiveError
from .adaptive_sqlite import _stamp, _time
from .models import TripPreferences
from .planning_repository import JobRepositoryError, identity
from .section_repository import _bounded_json, GLOBAL_STORAGE_BYTES

MAX_TEXT_BYTES = 131072
MAX_PREVIEW_STORAGE = 393216
MAX_CURSOR = 2**53 - 1
_BASE = {'owner','plan','section','lease','expected_version'}
_ARGS = {'load': _BASE, 'append': _BASE | {'response_id','expected_cursor','cursor','text_delta'}}
_FIELDS = ('stream_cursor','stream_output_text','stream_preview','reserved_preview_bytes')


def _invalid():
    raise JobRepositoryError('SECTION_PREVIEW_INVALID',400)


def _cursor(value, minimum=-1):
    if type(value) is not int or not minimum <= value <= MAX_CURSOR: _invalid()
    return value


@dataclass(frozen=True)
class SectionPreviewState:
    section_id: str
    version: int
    cursor: int
    lease_token: str = field(repr=False)
    lease_until: str = field(repr=False)
    response_id: str = field(repr=False)
    output_text: str = field(repr=False)
    preview: dict = field(repr=False)


class SectionPreviewStore:
    def __init__(self, gateway, *, enabled=False):
        if enabled is not True or getattr(gateway,'supports_section_preview',False) is not True:
            raise JobRepositoryError('SECTION_PREVIEW_DISABLED',503)
        if getattr(gateway,'elevated',False) is not True:
            raise JobRepositoryError('JOB_WORKER_CONTEXT_REQUIRED',403)
        self.gateway = gateway

    async def _call(self, operation, owner, plan, section, lease, version, **extra):
        args = dict(owner=identity(owner),plan=identity(plan),section=identity(section),
                    lease=identity(lease),expected_version=version,**extra)
        try:
            rows = await self.gateway.preview_request(operation,args)
            if rows == []: raise JobRepositoryError('SECTION_PREVIEW_CONFLICT',409)
            if type(rows) is not list or len(rows)!=1: raise ValueError()
            s=rows[0]
            if s['user_id']!=args['owner'] or s['plan_id']!=args['plan'] or s['id']!=args['section'] or s['status']!='running' or s['checkpoint'] is not None: raise ValueError()
            if s['lease_token']!=args['lease'] or type(s['version']) is not int or s['version']!=version+(operation=='append'): raise ValueError()
            if type(s['provider_response_id']) is not str or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}',s['provider_response_id']): raise ValueError()
            if type(s['lease_until']) is not str: raise ValueError()
            text=s.get('stream_output_text','');cursor=_cursor(s.get('stream_cursor',-1))
            if type(text) is not str or len(text.encode())>MAX_TEXT_BYTES: raise ValueError()
            preview=s.get('stream_preview',{'status':'draft','accepted':False,'days':[]})
            if preview.get('status')!='draft' or preview.get('accepted') is not False or type(preview.get('days')) is not list or len(preview['days'])>3: raise ValueError()
            if operation=='append' and (cursor!=extra['cursor'] or s['provider_response_id']!=extra['response_id']): raise ValueError()
            _bounded_json(s,524288)
            return SectionPreviewState(s['id'],s['version'],cursor,s['lease_token'],s['lease_until'],s['provider_response_id'],text,preview)
        except JobRepositoryError: raise
        except Exception: raise JobRepositoryError('SECTION_PREVIEW_STORAGE_UNCONFIRMED',503) from None

    async def load(self,owner,plan,section,lease,version):
        return await self._call('load',owner,plan,section,lease,version)

    async def append(self,owner,plan,section,lease,version,*,response_id,expected_cursor,cursor,text_delta=''):
        return await self._call('append',owner,plan,section,lease,version,response_id=response_id,
                                expected_cursor=expected_cursor,cursor=cursor,text_delta=text_delta)


class SectionPreviewMixin:
    """Compose before SQLite gateway; all hooks run in its existing transaction."""
    supports_section_preview = True

    async def preview_request(self,operation,payload):
        if operation not in _ARGS or type(payload) is not dict or set(payload)!=_ARGS[operation]: _invalid()
        for key in ('owner','plan','section','lease'): identity(payload[key])
        if type(payload['expected_version']) is not int or payload['expected_version']<1: _invalid()
        if operation=='append':
            old=_cursor(payload['expected_cursor']);new=_cursor(payload['cursor'],0)
            if new<=old or type(payload['text_delta']) is not str or len(payload['text_delta'].encode())>MAX_TEXT_BYTES: _invalid()
            if type(payload['response_id']) is not str or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,192}',payload['response_id']): _invalid()
        _bounded_json(payload,MAX_PREVIEW_STORAGE)
        return await asyncio.to_thread(self._execute,'preview_'+operation,payload)

    def _allocated(self,c):
        return super()._allocated(c)+c.execute("SELECT COALESCE(SUM(json_extract(data,'$.reserved_preview_bytes')),0) FROM sections").fetchone()[0]

    def _save(self,c,table,row):
        if table=='sections' and row.get('status') in {'succeeded','failed','cancelled','submission_unknown'}:
            for key in _FIELDS: row.pop(key,None)
        return super()._save(c,table,row)

    def _dispatch(self,c,op,a,now):
        if not op.startswith('preview_'): return super()._dispatch(c,op,a,now)
        p=self._one(c,'plans',a['plan'],a['owner'],now)
        s=self._one(c,'sections',a['section'],a['owner'],now)
        if not p or not s or s['plan_id']!=p['id'] or p['status']!='active' or p['active_section']!=s['id'] or s['status']!='running' or s['checkpoint'] is not None or not s['provider_response_id'] or s['lease_token']!=a['lease'] or s['version']!=a['expected_version'] or _time(s['lease_until'])<=now: return []
        if op=='preview_load': return [s]
        if op!='preview_append': _invalid()
        if s['provider_response_id']!=a['response_id'] or s.get('stream_cursor',-1)!=a['expected_cursor']: return []
        text=s.get('stream_output_text','')+a['text_delta']
        if len(text.encode())>MAX_TEXT_BYTES: raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
        spec=SectionSpec(TripPreferences.model_validate(p['preferences']),date.fromisoformat(s['start_date']),date.fromisoformat(s['end_date']),s['budget_limit_cents'],s['input_boundary']['location'],s['input_boundary'].get('lastActivityEnd'),p.get('journey_strategy'))
        try: draft=preview_days(text,spec)
        except AdaptiveError: raise JobRepositoryError('SECTION_PREVIEW_INVALID',400) from None
        fields=dict(stream_cursor=a['cursor'],stream_output_text=text,stream_preview=draft)
        size=len(_bounded_json(fields,MAX_PREVIEW_STORAGE))+128
        old=s.get('reserved_preview_bytes',0)
        reserved=c.execute("SELECT COALESCE(SUM(COALESCE(json_extract(data,'$.reserved_preview_bytes'),0)+COALESCE(json_extract(data,'$.reserved_checkpoint_bytes'),0)),0) FROM sections WHERE plan_id=?",(p['id'],)).fetchone()[0]
        if p['storage_used_bytes']+reserved+size-old>p['storage_limit_bytes'] or self._allocated(c)+size-old>GLOBAL_STORAGE_BYTES:
            raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
        s.update(**fields,reserved_preview_bytes=size,lease_until=_stamp(now+60))
        self._save(c,'sections',s)
        return [s]
