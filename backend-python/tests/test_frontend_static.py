from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

class Auth:
    def configured(self):return True
    async def verify(self,token):return SimpleNamespace(id='11111111-1111-4111-8111-111111111111')

@pytest.fixture
def ui(monkeypatch,tmp_path):
    root=tmp_path/'dist';root.mkdir();(root/'assets').mkdir()
    (root/'roamora.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    (root/'index.html').write_text('<html>PUBLIC_PLANNER</html>')
    (root/'assets'/'index-abc123.js').write_text('console.log("public")')
    (tmp_path/'private.env').write_text('PRIVATE_SENTINEL')
    for k,v in {'APP_MODE':'production','APP_ENV':'production','SAVED_ITINERARIES_SCHEMA_VERIFIED':'true',
        'TRIP_OWNERSHIP_ENABLED':'false','TRIP_OWNERSHIP_SCHEMA_VERIFIED':'false',
        'API_HOST':'app.example.test','FRONTEND_ORIGIN':'https://app.example.test',
        'SERVE_FRONTEND':'true','FRONTEND_DIST':str(root),'PLANNING_JOBS_ENABLED':'false'}.items():monkeypatch.setenv(k,v)
    from app.main import create_app
    with TestClient(create_app(auth_service=Auth()),base_url='https://app.example.test') as client:
        yield client,root

@pytest.mark.parametrize('path',['/','/index.html','/saved-trips','/itineraries/11111111-1111-4111-8111-111111111111'])
def test_public_pages_and_head_without_session(ui,path):
    client,_=ui;r=client.get(path)
    assert r.status_code==200 and 'PUBLIC_PLANNER' in r.text
    assert r.headers['cache-control']=='no-store' and r.headers['x-content-type-options']=='nosniff'
    r=client.head(path);assert r.status_code==200 and r.content==b''

def test_assets_correct_mime_and_missing_asset_not_html(ui):
    client,_=ui;r=client.get('/assets/index-abc123.js')
    assert r.status_code==200 and 'javascript' in r.headers['content-type']
    r=client.get('/assets/missing.js');assert r.status_code==404 and 'PUBLIC_PLANNER' not in r.text

@pytest.mark.parametrize('path',['/api/saved-itineraries','/api/unknown','/docs','/openapi.json','/.env','/assets/../private.env','/assets/index-abc123.js.map','/__qa/index.html','/saved-trips/private.env','/saved-trips.json'])
def test_private_or_api_paths_never_get_spa_fallback(ui,path):
    client,_=ui;r=client.get(path)
    assert r.status_code in {401,404} and 'PUBLIC_PLANNER' not in r.text and 'PRIVATE_SENTINEL' not in r.text

def test_static_serving_preserves_host_origin_and_post_boundaries(ui):
    client,_=ui
    assert client.get('/',headers={'Host':'unapproved.example'}).status_code==400
    assert client.get('/',headers={'Origin':'https://unapproved.example'}).status_code==403
    assert client.post('/',json={}).status_code==401
    r=client.get('/api/health');assert r.status_code==200 and r.json()['backend']=='fastapi'
    assert r.headers['cache-control']=='no-store'

def test_symlink_asset_cannot_escape_dist(ui,tmp_path):
    client,root=ui;(root/'assets'/'secret.js').symlink_to(tmp_path/'private.env')
    assert client.get('/assets/secret.js').status_code==404

def test_enabled_frontend_missing_build_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setenv('SERVE_FRONTEND','true');monkeypatch.setenv('FRONTEND_DIST',str(tmp_path))
    from app.main import create_app
    with pytest.raises(RuntimeError,match='Frontend build'):create_app(auth_service=Auth())


def test_only_reviewed_public_brand_asset_is_public(ui):
    client,root=ui
    response=client.get('/roamora.svg')
    assert response.status_code==200 and response.headers['content-type'].startswith('image/svg+xml')
    assert response.headers['x-content-type-options']=='nosniff'
    for path in ['/private.svg','/public/roamora.svg','/roamora.svg/private.env']:
        assert client.get(path).status_code in (401,404)
