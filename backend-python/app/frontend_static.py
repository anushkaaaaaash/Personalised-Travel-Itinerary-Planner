"""Optional same-origin public UI; never serves API/source/configuration paths."""
import os
import re
from pathlib import Path
from fastapi.responses import FileResponse, Response

_ASSET = re.compile(r'/assets/[A-Za-z0-9_-]+\.(?:js|css|svg|png|jpg|jpeg|webp|ico|woff2?)\Z')
_PAGE = re.compile(r'/itineraries/[A-Za-z0-9_-]{1,128}\Z')


def public_frontend_request(scope):
    if os.getenv('SERVE_FRONTEND') != 'true' or scope.get('method') not in {'GET','HEAD'}:
        return False
    path=scope.get('path','')
    return path in {'/','/index.html','/roamora.svg','/saved-trips'} or bool(_ASSET.fullmatch(path) or _PAGE.fullmatch(path))


def attach_frontend(app):
    if os.getenv('SERVE_FRONTEND') != 'true':return
    raw=os.getenv('FRONTEND_DIST','')
    root=Path(raw)
    if (not raw or not root.is_absolute() or root.is_symlink() or
        not (root/'index.html').is_file() or (root/'index.html').is_symlink() or
        not (root/'assets').is_dir() or (root/'assets').is_symlink()):
        raise RuntimeError('Frontend build is missing or invalid.')
    root=root.resolve()

    @app.api_route('/{frontend_path:path}',methods=['GET','HEAD'],include_in_schema=False)
    async def frontend(frontend_path: str):
        path='/'+frontend_path
        if not public_frontend_request({'method':'GET','path':path}):return Response(status_code=404)
        candidate=root/'index.html' if path in {'/','/index.html','/saved-trips'} or _PAGE.fullmatch(path) else root/frontend_path
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root) or not candidate.is_file():
            return Response(status_code=404)
        return FileResponse(candidate,headers={'X-Content-Type-Options':'nosniff',
            'Cache-Control':'no-store' if candidate.name=='index.html' else 'public, max-age=3600'})
