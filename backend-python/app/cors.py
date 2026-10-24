"""One explicit HTTPS frontend origin for a reviewed cross-origin deployment."""
import os
from urllib.parse import urlsplit

def configured_frontend_origins():
    value=os.environ.get('FRONTEND_ORIGIN','').strip()
    if not value:return []  # Local Vite uses its same-origin /api proxy.
    try:
        p=urlsplit(value)
        if (p.scheme!='https' or not p.hostname or p.username or p.password
                or p.path not in ('','/') or p.query or p.fragment or p.port not in (None,443)
                or ',' in value or '*' in value or any(ord(c)<33 for c in value)):
            return []
    except ValueError:return []
    return [value.rstrip('/')]
