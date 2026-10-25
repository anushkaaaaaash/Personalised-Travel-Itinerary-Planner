"""Explicit production origin and at most one operator-approved preview origin."""
import os
import re
from urllib.parse import urlsplit

def valid_origin(value):
    try:
        p=urlsplit(value)
        if (p.scheme!='https' or not p.hostname or p.username or p.password
                or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*',p.hostname)
                or p.path not in ('','/') or p.query or p.fragment or p.port not in (None,443)
                or ',' in value or '*' in value or any(ord(c)<33 for c in value)):
            return None
    except ValueError:return None
    return value.rstrip('/')

def configured_frontend_origins():
    primary=os.environ.get('FRONTEND_ORIGIN','').strip()
    preview=os.environ.get('FRONTEND_PREVIEW_ORIGIN','').strip()
    if not primary:return []  # Preview cannot independently enable cross-origin access.
    values=[primary]+([preview] if preview else [])
    origins=[valid_origin(value) for value in values]
    if not all(origins):return []  # A malformed optional origin fails the whole setup closed.
    return list(dict.fromkeys(origins))
