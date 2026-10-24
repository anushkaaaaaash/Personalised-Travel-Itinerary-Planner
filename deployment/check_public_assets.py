"""Bounded static bundle check; prints file names only, never matching values."""
from pathlib import Path
import re,sys
root=Path(sys.argv[1] if len(sys.argv)>1 else 'frontend/dist')
if not root.is_dir():raise SystemExit('Build directory missing.')
patterns=[rb'gsk_[A-Za-z0-9_-]{20,}',rb'sb_secret_[A-Za-z0-9_-]{12,}',rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}']
files=list(root.rglob('*'));failed=[];total=0
for path in files:
    if not path.is_file():continue
    data=path.read_bytes();total+=len(data)
    if path.suffix=='.map' or any(re.search(pattern,data) for pattern in patterns):failed.append(str(path.relative_to(root)))
if failed:raise SystemExit('Public asset safety check failed: '+', '.join(failed))
print(f'Public asset pattern check passed; {total} bytes. This is not a proof that arbitrary user-supplied text is secret-free.')
