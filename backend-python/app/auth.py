"""Supabase Auth REST adapter. No local JWT minting/decoding or credential logging."""
import os
import re
import time
from urllib.parse import urlsplit
from uuid import UUID
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from .local_guard import LocalOnlyBoundary


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value):
            raise ValueError('Enter a valid email address.')
        return value

    @field_validator('password')
    @classmethod
    def valid_password(cls, value):
        if not 8 <= len(value.get_secret_value()) <= 128:
            raise ValueError('Use a password of 8 to 128 characters.')
        return value


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None


class AuthSession(BaseModel):
    access_token: str = Field(min_length=1, max_length=16384, repr=False)
    token_type: str = 'bearer'
    expires_in: int = Field(gt=0, le=604800)
    expires_at: int


class AuthResult(BaseModel):
    user: AuthUser | None = None
    session: AuthSession | None = None
    pending_confirmation: bool = False


class AuthError(Exception):
    def __init__(self, status=401, code='AUTH_REQUIRED', message='Sign in again to continue.'):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def auth_error(exc):
    return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}}, headers={'Cache-Control': 'no-store'})


def read_auth_configuration():
    # Environment only: never open private .env files at import or during tests.
    from .configuration import public_auth_values
    return public_auth_values()


def ownership_enabled():
    return os.getenv('TRIP_OWNERSHIP_ENABLED', '').lower() == 'true'


def production_mode():
    from .configuration import hosted_environment
    return hosted_environment()


class SupabaseAuthService:
    def __init__(self, configuration=read_auth_configuration, transport=None):
        self.configuration, self.transport = configuration, transport

    def settings(self):
        url, key = self.configuration()
        try:
            p = urlsplit(url)
            valid = (p.scheme == 'https' and p.hostname and p.hostname.endswith('.supabase.co')
                     and not p.username and not p.password and not p.port and not p.query
                     and not p.fragment and p.path in ('', '/'))
        except (ValueError, TypeError):
            valid = False
        # Accept public publishable keys or legacy anon keys only, never service-role keys.
        public_key = isinstance(key, str) and key.startswith('sb_publishable_')
        if isinstance(key, str) and key.startswith('eyJ'):
            try:
                import base64, json
                payload = key.split('.')[1]
                public_key = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))).get('role') == 'anon'
            except Exception:
                public_key = False
        # This decode classifies configuration only; user JWTs are NEVER decoded for trust.
        if not valid or not public_key:
            raise AuthError(503, 'AUTH_NOT_CONFIGURED', 'Authentication is not configured on this server.')
        return url.rstrip('/'), key

    def configured(self):
        try:
            self.settings()
            return True
        except AuthError:
            return False

    async def _request(self, method, path, *, payload=None, token=None):
        url, key = self.settings()
        headers = {'apikey': key, 'Accept': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                async with client.stream(method, url + '/auth/v1/' + path, headers=headers, json=payload) as response:
                    if response.status_code == 429:
                        raise AuthError(429, 'AUTH_RATE_LIMITED', 'Too many attempts. Please wait before trying again.')
                    if response.status_code >= 500 or 300 <= response.status_code < 400:
                        raise AuthError(502, 'AUTH_UNAVAILABLE', 'Authentication is temporarily unavailable.')
                    if response.status_code >= 400:
                        raise AuthError(401, 'AUTH_FAILED', 'Authentication failed. Check your details and email confirmation.')
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise ValueError()
                    if not data:
                        return {}
                    import json
                    parsed = json.loads(data)
                    if not isinstance(parsed, dict):
                        raise ValueError()
                    return parsed
        except AuthError:
            raise
        except Exception:
            raise AuthError(502, 'AUTH_UNAVAILABLE', 'Authentication is temporarily unavailable.') from None

    async def authenticate(self, credentials, *, register=False):
        credentials = Credentials.model_validate(credentials)
        data = await self._request('POST', 'signup' if register else 'token?grant_type=password',
                                  payload={'email': credentials.email, 'password': credentials.password.get_secret_value()})
        try:
            if register and not data.get('access_token'):
                # Supabase may intentionally obscure existing users; do not promise account creation.
                AuthUser.model_validate(data.get('user', data))
                return AuthResult(pending_confirmation=True)
            user = AuthUser.model_validate(data['user'])
            if data.get('token_type', '').lower() != 'bearer':
                raise ValueError()
            expires = data['expires_in']
            if type(expires) is not int:
                raise ValueError()
            session = AuthSession(access_token=data['access_token'], expires_in=expires,
                                  expires_at=int(time.time()) + expires)
            return AuthResult(user=user, session=session)
        except Exception:
            raise AuthError(502, 'AUTH_UNAVAILABLE', 'Authentication could not be confirmed.') from None

    async def verify(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(c.isspace() for c in token):
            raise AuthError()
        # Auth server verifies signature, expiry, and user. Never trust unsigned JWT claims.
        data = await self._request('GET', 'user', token=token)
        try:
            if data.get('is_anonymous') is True or not data.get('email_confirmed_at'):
                raise ValueError()
            return AuthUser.model_validate(data)
        except Exception:
            raise AuthError() from None

    async def logout(self, token):
        await self.verify(token)
        await self._request('POST', 'logout?scope=local', token=token)


def bearer(scope):
    values = [v.decode('latin1') for k, v in scope.get('headers', []) if k.lower() == b'authorization']
    if len(values) != 1:
        raise AuthError()
    scheme, sep, token = values[0].partition(' ')
    if not sep or scheme.lower() != 'bearer' or not token:
        raise AuthError()
    return token


class AccessBoundary:
    """Local legacy mode OR explicitly verified owner-scoped production. Default deny."""
    def __init__(self, app, auth_service, ownership_supported=False):
        self.app, self.auth_service = app, auth_service
        self.ownership_supported = ownership_supported
        self.local = LocalOnlyBoundary(app)
        from .production_security import ProductionAccess
        self.production = ProductionAccess(app,auth_service)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if production_mode():
            return await self.production(scope,receive,send)
        protected = ownership_enabled() or production_mode()
        if not protected:
            if os.getenv('APP_MODE', 'local').lower() != 'local':
                return await auth_error(AuthError(503, 'PUBLIC_DEPLOYMENT_DISABLED', 'Deployment mode is not configured.'))(scope, receive, send)
            return await self.local(scope, receive, send)
        ready = (self.ownership_supported and ownership_enabled()
                 and os.getenv('TRIP_OWNERSHIP_SCHEMA_VERIFIED', '').lower() == 'true'
                 and self.auth_service.configured())
        if not ready:
            return await auth_error(AuthError(503, 'PUBLIC_DEPLOYMENT_DISABLED', 'Authentication and data ownership require approved setup and verification.'))(scope, receive, send)
        if scope['path'] not in {'/api/health', '/api/auth/config', '/api/auth/register', '/api/auth/login'}:
            try:
                token = bearer(scope)
                user = await self.auth_service.verify(token)
                scope.setdefault('state', {}).update(auth_user_id=str(user.id), access_token=token)
            except AuthError as exc:
                return await auth_error(exc)(scope, receive, send)
        return await self.app(scope, receive, send)


def build_auth_router(service, planning_capability=None, adaptive_capability=None, adaptive_policy=None):
    router = APIRouter(prefix='/api/auth', tags=['Authentication'])

    @router.get('/config')
    async def config():
        return {'enabled': service.configured(), 'mode': 'production' if production_mode() else 'local', 'ownership_enabled': ownership_enabled(), 'saved_only': production_mode(),
                'planning_jobs_enabled': bool(planning_capability and planning_capability()),
                'adaptive_planning_enabled': bool(adaptive_capability and adaptive_capability()),
                'adaptive_planning_policy': adaptive_policy() if adaptive_capability and adaptive_capability() and adaptive_policy else None}

    @router.post('/register', response_model=AuthResult)
    async def register(credentials: Credentials):
        try:
            result = await service.authenticate(credentials, register=True)
            return JSONResponse(content=result.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})
        except AuthError as exc:
            return auth_error(exc)

    @router.post('/login', response_model=AuthResult)
    async def login(credentials: Credentials):
        try:
            result = await service.authenticate(credentials)
            return JSONResponse(content=result.model_dump(mode='json'), headers={'Cache-Control': 'no-store'})
        except AuthError as exc:
            return auth_error(exc)

    @router.get('/confirmation')
    async def confirmation(request: Request):
        try:
            # Explicit verification also protects local-mode calls. Never infer success
            # from callback query fields or decode unsigned JWT claims.
            await service.verify(bearer(request.scope))
            return JSONResponse(content={'confirmed': True}, headers={'Cache-Control': 'no-store'})
        except AuthError as exc:
            return auth_error(exc)

    @router.post('/logout')
    async def logout(request: Request):
        try:
            await service.logout(bearer(request.scope))
            return JSONResponse(content={'signed_out': True}, headers={'Cache-Control': 'no-store'})
        except AuthError as exc:
            return auth_error(exc)
    return router
