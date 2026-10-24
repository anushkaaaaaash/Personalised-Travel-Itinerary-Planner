"""Read-only local preflight. Does not print credentials or contact any service."""
from pathlib import Path
import importlib.util
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    if not ROOT.name.endswith('-FastAPI'):
        print('NOTE: this is not the named Windows -FastAPI working copy.')
    checks = {
        'Python 3.12 or newer': sys.version_info >= (3,12),
        'FastAPI installed in this Python': importlib.util.find_spec('fastapi') is not None,
        'HTTPX installed in this Python': importlib.util.find_spec('httpx') is not None,
        'pytest installed in this Python': importlib.util.find_spec('pytest') is not None,
        'Node executable available': shutil.which('node') is not None,
        'npm executable available': shutil.which('npm.cmd' if sys.platform=='win32' else 'npm') is not None,
        'Frontend source present': (ROOT/'frontend/src').is_dir(),
        'Private backend env file exists (contents not read)': (ROOT/'backend/.env').is_file(),
    }
    for label,ok in checks.items(): print(('PASS' if ok else 'CHECK')+': '+label)
    print('No server, database, AI request, package installation or file change was made.')
    return 0 if all(checks.values()) else 1

if __name__=='__main__': raise SystemExit(main())
