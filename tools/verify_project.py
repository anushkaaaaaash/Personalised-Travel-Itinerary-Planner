"""One offline verification batch. No servers, AI calls or database operations."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='Execute the displayed checks')
    parser.add_argument('--install-dependencies',action='store_true',help='Sync npm dependencies from the preserved package files first')
    args=parser.parse_args()
    if not ROOT.name.endswith('-FastAPI') or not (ROOT/'package.json').is_file():
        sys.exit('STOP: run this only from the separate project ending in -FastAPI.')
    npm=shutil.which('npm.cmd' if sys.platform=='win32' else 'npm')
    if not npm:sys.exit('STOP: npm was not found. Install/configure Node before retrying.')
    steps=[]
    if args.install_dependencies:
        steps.append([npm,'install','--ignore-scripts','--no-audit','--no-fund'])
    steps.extend([[sys.executable,'-m','pytest','-c','backend-python/pytest.ini','backend-python/tests'],
                  [npm,'test'],[npm,'run','build']])
    for step in steps:print('Will run: '+' '.join(step))
    if not args.run:
        print('Preview only. Add --run to execute. No files changed.');return
    if args.install_dependencies:
        backup=ROOT.parent/(ROOT.name+'-before-dependency-sync-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir()
        for rel in ['package.json','package-lock.json','frontend/package.json','backend/package.json']:
            p=ROOT/rel
            if p.is_file():
                dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        print('Dependency manifests backed up to: '+str(backup))
    for step in steps:
        code=subprocess.run(step,cwd=ROOT).returncode
        if code:sys.exit('STOP: this step failed; later steps were not run. Share the error, not environment-file contents.')
    print('All local checks passed. This does not claim a live AI request or deployed site.')

if __name__=='__main__':main()
