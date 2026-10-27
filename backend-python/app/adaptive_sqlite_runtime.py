"""Fixed Fly-volume boundary; never fall back to ephemeral disk or initialize on loss."""
import os
from pathlib import Path
import stat
from .planning_repository import JobRepositoryError

MOUNT = Path('/data')
DIRECTORY = MOUNT / 'checkpoints'
DATABASE = DIRECTORY / 'planning.sqlite3'
UID = GID = 10001


def verify_volume(*, require_database=True):
    if MOUNT.is_symlink() or not MOUNT.is_dir() or not os.path.ismount(MOUNT):
        raise JobRepositoryError('SQLITE_VOLUME_UNVERIFIED')
    try:
        entry = DIRECTORY.lstat()
        if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != UID or stat.S_IMODE(entry.st_mode) != 0o700:
            raise ValueError()
        if require_database:
            entry = DATABASE.lstat()
            if not stat.S_ISREG(entry.st_mode) or entry.st_uid != UID or entry.st_nlink != 1 or stat.S_IMODE(entry.st_mode) != 0o600:
                raise ValueError()
    except (OSError,ValueError):
        raise JobRepositoryError('SQLITE_STORAGE_UNVERIFIED') from None
    return str(DATABASE)


def prepare_new_directory():
    """Explicit one-time operator provisioning only, never called by web startup."""
    if MOUNT.is_symlink() or not MOUNT.is_dir() or not os.path.ismount(MOUNT):
        raise JobRepositoryError('SQLITE_VOLUME_UNVERIFIED')
    if os.geteuid() not in (0,UID): raise JobRepositoryError('SQLITE_STORAGE_UNVERIFIED')
    os.umask(0o077)
    if not DIRECTORY.exists():
        try:
            DIRECTORY.mkdir(mode=0o700)
            if os.geteuid()==0: os.chown(DIRECTORY,UID,GID)
        except OSError: raise JobRepositoryError('SQLITE_DIRECTORY_CREATE_DENIED') from None
    verify_volume(require_database=False)
    if DATABASE.exists() or DATABASE.is_symlink(): raise JobRepositoryError('SQLITE_ALREADY_INITIALIZED')
    if os.geteuid()==0:
        try: os.setgroups([]);os.setgid(GID);os.setuid(UID)
        except OSError: raise JobRepositoryError('SQLITE_PRIVILEGE_DROP_FAILED') from None
    return str(DATABASE)


def prepare_existing_storage_user():
    """Operator commands use the application's UID before opening SQLite journals."""
    path=verify_volume()
    if os.geteuid() not in (0,UID):raise JobRepositoryError('SQLITE_STORAGE_UNVERIFIED')
    os.umask(0o077)
    if os.geteuid()==0:
        try:
            os.setgroups([]);os.setgid(GID);os.setuid(UID)
        except OSError:raise JobRepositoryError('SQLITE_PRIVILEGE_DROP_FAILED') from None
    if os.geteuid()!=UID:raise JobRepositoryError('SQLITE_PRIVILEGE_DROP_FAILED')
    verify_volume()
    return path
