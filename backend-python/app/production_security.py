"""Saved-itinerary-only production boundary. No migrations, credentials or network at import."""
import os
import re
import time
from collections import deque
from fastapi.responses import JSONResponse
from .cors import configured_frontend_origins

AI_PATHS={'/api/planning-jobs','/api/recommendations','/api/itineraries/generate','/api/itineraries/refine'}
PUBLIC_PATHS={'/api/health','/api/auth/config','/api/auth/login','/api/auth/register'}

def settings(auth):
    host=os.getenv('API_HOST','')
    if (os.getenv('APP_MODE')!='production' or os.getenv('APP_ENV','production') not in {'staging','production'} or os.getenv('SAVED_ITINERARIES_SCHEMA_VERIFIED')!='true'
        or os.getenv('TRIP_OWNERSHIP_ENABLED','false').lower()!='false'
        or os.getenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED','false').lower()!='false'
        or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*',host) or '.' not in host
        or not configured_frontend_origins() or not auth.configured()):
        raise ValueError('Production configuration is incomplete. Review deployment settings.')
    return host,configured_frontend_origins()

def denied(status,code,message):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message}},headers={'Cache-Control':'no-store',**({'Retry-After':'60'} if status==429 else {})})

class ProductionAccess:
    """Single-process conservative quotas; not a distributed billing guarantee."""
    def __init__(self,app,auth,clock=time.monotonic):
        self.app,self.auth,self.clock=app,auth,clock
        self.auth_requests=deque();self.ai_requests=deque();self.users={};self.active_ai=0

    def consume(self,bucket,limit,seconds):
        now=self.clock()
        while bucket and bucket[0]<=now-seconds:bucket.popleft()
        if len(bucket)>=limit:return False
        bucket.append(now);return True

    async def __call__(self,scope,receive,send):
        from .auth import bearer,AuthError,auth_error
        try:host,allowed_origins=settings(self.auth)
        except ValueError:
            return await denied(503,'PUBLIC_DEPLOYMENT_DISABLED','Production setup has not been verified.')(scope,receive,send)
        hosts=[v for k,v in scope['headers'] if k.lower()==b'host']
        origins=[v for k,v in scope['headers'] if k.lower()==b'origin']
        if hosts!=[host.encode()] and hosts!=[(host+':443').encode()]:
            return await denied(400,'INVALID_HOST','Unrecognized API host.')(scope,receive,send)
        if origins and (len(origins)!=1 or origins[0] not in [origin.encode() for origin in allowed_origins]):
            return await denied(403,'ORIGIN_FORBIDDEN','This browser origin is not permitted.')(scope,receive,send)
        path=scope['path']
        # Legacy history is deliberately unavailable even with a valid JWT or old ownership flags.
        if path in {'/api/trips','/api/history'} or path.startswith('/api/trips/') or path.startswith('/api/history/'):
            return await denied(404,'LEGACY_HISTORY_DISABLED','Legacy preference history is local-only.')(scope,receive,send)
        if path in {'/api/auth/login','/api/auth/register'} and not self.consume(self.auth_requests,30,60):
            return await denied(429,'AUTH_RATE_LIMITED','Too many account requests. Try again later.')(scope,receive,send)
        if path not in PUBLIC_PATHS:
            try:
                token=bearer(scope);user=await self.auth.verify(token)
                scope.setdefault('state',{}).update(auth_user_id=str(user.id),access_token=token)
            except AuthError as exc:return await auth_error(exc)(scope,receive,send)
        ai=path in AI_PATHS
        if ai:
            now=self.clock()
            self.users={k:v for k,v in self.users.items() if v and v[-1]>now-60}
            uid=scope['state']['auth_user_id']
            if (self.active_ai>=2 or (uid not in self.users and len(self.users)>=1000)
                or not self.consume(self.users.setdefault(uid,deque()),6,60)
                or not self.consume(self.ai_requests,60,3600)):
                return await denied(429,'AI_RATE_LIMITED','AI request allowance reached. Wait before retrying; no automatic retry is made.')(scope,receive,send)
            self.active_ai+=1
        try:return await self.app(scope,receive,send)
        finally:
            if ai:self.active_ai-=1
