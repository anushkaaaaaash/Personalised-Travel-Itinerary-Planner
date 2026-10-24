"""Existing public.trips adapter via Supabase's REST API. No DDL or retries."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from dotenv import dotenv_values
from .models import TripPreferences

class StorageNotConfigured(Exception):
    pass

class SaveUnconfirmed(Exception):
    pass

def confirmed_id(value):
    if type(value) is int and 0 < value <= 9223372036854775807:
        return value if value <= 9007199254740991 else str(value)
    if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,18}', value) and int(value) <= 9223372036854775807:
        return value
    raise SaveUnconfirmed()

def trip_row(p: TripPreferences):
    p = TripPreferences.model_validate(p.model_dump())
    return {
        'destination': p.destination, 'start_date': p.startDate, 'end_date': p.endDate,
        'budget': p.budget, 'travelers': p.travelers,
        'preferences': json.dumps({
            'departureCity': p.departureCity, 'currency': p.currency,
            'interests': p.interests, 'dietaryNeeds': p.dietaryNeeds, 'travelPace': p.travelPace,
            'travelStyle': p.travelStyle, 'mobilityConcerns': p.mobilityConcerns,
        }, ensure_ascii=True, separators=(',', ':')),
    }

def read_configuration():
    from .auth import production_mode
    if production_mode():raise StorageNotConfigured()
    # Read only on an explicit save. Tests replace this function; never print values.
    # Reuse the separate copy's existing private backend/.env, not the original project.
    from .configuration import private_backend_values
    values = private_backend_values()
    return values.get('SUPABASE_URL', ''), values.get('SUPABASE_SECRET_KEY', '')

class SupabaseTripStore:
    def __init__(self, configuration=read_configuration, transport=None, owner_id=None, access_token=None):
        self.configuration = configuration
        self.owner_id = owner_id
        self.access_token = access_token
        if owner_id is not None:
            from uuid import UUID
            if str(UUID(owner_id)) != owner_id or not isinstance(access_token, str) or not access_token or len(access_token) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in access_token):
                raise StorageNotConfigured()
        self.transport = transport  # MockTransport in tests; no live requests.

    def for_user(self, owner_id, access_token):
        from .auth import SupabaseAuthService
        # settings() permits only publishable / legacy anon keys, never the secret key.
        def settings():
            try:
                return SupabaseAuthService().settings()
            except Exception:
                raise StorageNotConfigured() from None
        return SupabaseTripStore(settings, self.transport, owner_id, access_token)

    async def save(self, preferences: TripPreferences):
        row = trip_row(preferences)
        if self.owner_id is not None:
            row['user_id'] = self.owner_id
        url, key = self.configuration()
        if not url or not key:
            raise StorageNotConfigured()
        parts = urlsplit(url)
        # Fail closed: hosted project HTTPS URLs only; never send a key to arbitrary paths.
        if (parts.scheme != 'https' or not parts.hostname or not parts.hostname.endswith('.supabase.co')
            or parts.username or parts.password or parts.port or parts.query or parts.fragment
            or parts.path not in ('', '/')):
            raise StorageNotConfigured()
        headers = {'apikey': key, 'Prefer': 'return=representation', 'Content-Type': 'application/json'}
        # Legacy service-role JWTs use Authorization as well; new sb_secret keys are NOT JWTs.
        if self.owner_id is not None:
            headers['Authorization'] = f'Bearer {self.access_token}'
        elif key.startswith('eyJ'):
            headers['Authorization'] = f'Bearer {key}'
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                response = await client.post(url.rstrip('/') + '/rest/v1/trips', params={'select': 'id,user_id' if self.owner_id else 'id'}, headers=headers, json=row)
            if response.status_code != 201:
                raise SaveUnconfirmed()
            data = response.json()
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise SaveUnconfirmed()
            if self.owner_id is not None and data[0].get('user_id') != self.owner_id:
                raise SaveUnconfirmed()
            return confirmed_id(data[0].get('id'))
        except Exception:
            # No raw response, key, SQL details, request or network exception reaches callers.
            raise SaveUnconfirmed() from None

    async def _read(self, params):
        """Allowlisted read-only query. No schema changes, raw error exposure or retries."""
        url, key = self.configuration()
        if not url or not key:
            raise StorageNotConfigured()
        try:
            parts = urlsplit(url)
            valid = (parts.scheme == 'https' and parts.hostname and parts.hostname.endswith('.supabase.co')
                and not parts.username and not parts.password and not parts.port and not parts.query
                and not parts.fragment and parts.path in ('', '/'))
        except ValueError:
            valid = False
        if not valid:
            raise StorageNotConfigured()
        headers = {'apikey': key, 'Accept': 'application/json'}
        if self.owner_id is not None:
            headers['Authorization'] = f'Bearer {self.access_token}'
        elif key.startswith('eyJ'):
            headers['Authorization'] = f'Bearer {key}'
        params = {'select': 'id,destination,start_date,end_date,budget,travelers,preferences,created_at', **params}
        if self.owner_id is not None:
            params['select'] += ',user_id'
            params['user_id'] = 'eq.' + self.owner_id
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                async with client.stream('GET', url.rstrip('/') + '/rest/v1/trips', params=params, headers=headers) as response:
                    if response.status_code != 200:
                        raise ValueError()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1048576:
                            raise ValueError()
            rows = json.loads(body)
            if not isinstance(rows, list) or len(rows) > int(params['limit']) or any(not isinstance(row, dict) for row in rows):
                raise ValueError()
            if self.owner_id is not None and any(row.get('user_id') != self.owner_id for row in rows):
                raise ValueError()
            return rows
        except Exception:
            raise ReadUnconfirmed() from None

    async def list(self, limit=21, offset=0):
        if type(limit) is not int or not 1 <= limit <= 51 or type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('Invalid page')
        return await self._read({'order': 'created_at.desc,id.desc', 'limit': str(limit), 'offset': str(offset)})

    async def get(self, identity):
        identity = confirmed_id(identity)
        rows = await self._read({'id': 'eq.' + str(identity), 'limit': '1'})
        if not rows:
            return None
        if str(confirmed_id(rows[0].get('id'))) != str(identity):
            raise ReadUnconfirmed()
        return rows[0]

class ReadUnconfirmed(Exception):
    pass
