"""Request-scoped Supabase clients. User CRUD never obtains an elevated client."""
import json
import httpx
from .auth import SupabaseAuthService, AuthError, read_auth_configuration


class DatabaseError(Exception):
    def __init__(self, status=502, code='PERSISTENCE_UNCONFIRMED'):
        self.status, self.code = status, code
        super().__init__(code)


class SupabaseClient:
    def __init__(self, url, key, token=None, owner_id=None, *, transport=None, elevated=False):
        self._url, self._key, self._token = url, key, token
        self.owner_id, self.elevated, self._transport = owner_id, elevated, transport

    async def request(self, method, resource, *, params=None, payload=None):
        # All current operations are scoped to the new table; no arbitrary REST path.
        if resource != 'saved_itineraries' or method not in {'GET','POST','PATCH','DELETE'}:
            raise DatabaseError(400,'INVALID_OPERATION')
        headers={'apikey':self._key,'Accept':'application/json','Prefer':'return=representation'}
        if self._token: headers['Authorization']='Bearer '+self._token
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False,transport=self._transport) as client:
                async with client.stream(method,self._url+'/rest/v1/'+resource,params=params,headers=headers,json=payload) as response:
                    if response.status_code==409: raise DatabaseError(409,'VERSION_CONFLICT')
                    if response.status_code in {401,403}: raise DatabaseError(403,'PERSISTENCE_FORBIDDEN')
                    if response.status_code not in ({201} if method=='POST' else {200}): raise DatabaseError()
                    body=bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body)>1048576: raise DatabaseError()
            result=json.loads(body)
            if type(result) is not list: raise DatabaseError()
            return result
        except DatabaseError: raise
        except Exception: raise DatabaseError() from None


async def get_client(access_token, *, auth_service=None, transport=None):
    """Verify with Supabase Auth; forward that JWT with public key, never service key."""
    auth=auth_service or SupabaseAuthService()
    user=await auth.verify(access_token)
    url,key=auth.settings()  # rejects secret/service-role configuration
    return SupabaseClient(url,key,access_token,str(user.id),transport=transport)


def get_service_client(*, explicit_admin=False, configuration=None, transport=None):
    """Server-only administrative entry point. No HTTP user route calls this factory."""
    if explicit_admin is not True: raise DatabaseError(403,'ADMIN_CONTEXT_REQUIRED')
    from .storage import read_configuration
    try:
        url,key=(configuration or read_configuration)()
        # Reuse strict hosted-project URL validation without classifying this secret as public.
        url,_=SupabaseAuthService(configuration=lambda:(url,'sb_publishable_url_validation')).settings()
        service=type(key) is str and key.startswith('sb_secret_')
        if type(key) is str and key.startswith('eyJ'):
            import base64
            part=key.split('.')[1]
            service=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4))).get('role')=='service_role'
        if not service: raise ValueError()
        return SupabaseClient(url,key,key if key.startswith('eyJ') else None,transport=transport,elevated=True)
    except Exception: raise DatabaseError(503,'ADMIN_NOT_CONFIGURED') from None
