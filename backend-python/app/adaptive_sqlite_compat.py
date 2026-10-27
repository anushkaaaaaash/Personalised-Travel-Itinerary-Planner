"""Flags-off startup across an explicitly upgraded store; never migrates it.

V2 still uses all grounded resource/owner guards. Disabling research must never
silently discard its paid-work reservations or reinterpret its pending work.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
from .adaptive_sqlite import AdaptiveSQLiteGateway,_error
from .planning_repository import JobRepositoryError


def build_legacy_sqlite_gateway(path,*,enabled=False,clock=None):
    if enabled is not True:_error('SECTIONS_DISABLED',503)
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():_error('SECTIONS_STORAGE_UNAVAILABLE',503)
    try:
        identity=(path.stat().st_dev,path.stat().st_ino)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as c:
            c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
            version=c.execute('PRAGMA user_version').fetchone()[0]
            runtime=c.execute('SELECT version FROM runtime WHERE id=1').fetchone()
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required={'plans','sections','controls','runtime'}
            if version==2:required|={'research_jobs','revision_jobs','revision_controls'}
            if version not in (1,2) or runtime!=(version,) or not required<=tables:_error('SECTIONS_SCHEMA_NOT_READY',503)
        if version==1:gateway=AdaptiveSQLiteGateway(path,enabled=True,clock=clock)
        else:
            from .revision_sqlite import RevisionSQLiteGateway
            gateway=RevisionSQLiteGateway(path,enabled=True,research_enabled=False,clock=clock)
        if gateway._identity!=identity:_error('SECTIONS_STORAGE_UNAVAILABLE',503)
        return gateway
    except JobRepositoryError:raise
    except Exception:_error('SECTIONS_SCHEMA_NOT_READY',503)
