"""Temporary single-user boundary: fail closed off loopback, not authentication."""
import ipaddress
import os
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

def local_authority(value, origin=False, synthetic=False):
    try:
        parsed=urlsplit(value if origin else '//'+value)
        if (parsed.hostname not in {'localhost','127.0.0.1','::1'} | ({'testserver'} if synthetic else set())
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('','/') or any(ord(c)<33 for c in value)):
            return False
        if origin and parsed.scheme not in {'http','https'}:return False
        port=parsed.port
        return port is None or 1<=port<=65535
    except (ValueError,TypeError):return False

class LocalOnlyBoundary:
    def __init__(self, app):
        self.app=app

    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        client=scope.get('client')
        host=client[0] if client else ''
        # TestClient uses this synthetic host; real sockets always supply IPs.
        allowed=host=='testclient'
        if not allowed:
            try: allowed=ipaddress.ip_address(host).is_loopback
            except ValueError: allowed=False
        # Reject browser DNS rebinding / foreign-origin requests as well as remote IPs.
        headers={name.lower():value for name,value in scope.get('headers',[])}
        try:
            authority=headers.get(b'host',b'').decode('ascii')
            origin=headers.get(b'origin')
            allowed=allowed and local_authority(authority,synthetic=host=='testclient')
            if origin is not None:
                allowed=allowed and local_authority(origin.decode('ascii'),origin=True,synthetic=host=='testclient')
        except UnicodeError:allowed=False
        # Reject known proxy forwarding. A proxy stripping all headers is not detectable.
        forwarded={b'forwarded',b'x-forwarded-for',b'x-real-ip'}
        if any(name.lower() in forwarded for name,value in scope.get('headers',[])):
            allowed=False
        if os.environ.get('RENDER') or os.environ.get('VERCEL') or os.environ.get('APP_ENV', '').lower() in {'production','staging'}:
            allowed=False
        if not allowed:
            response=JSONResponse(status_code=503,content={'error':{
                'code':'PUBLIC_DEPLOYMENT_DISABLED',
                'message':'This project is local-only until authentication and data ownership are configured and verified.'}})
            return await response(scope,receive,send)
        return await self.app(scope,receive,send)
