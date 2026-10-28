from fastapi import FastAPI
from fastapi.testclient import TestClient
from uuid import uuid4
import pytest
from test_adaptive_expenses import completed
from test_adaptive_integration import Auth
from test_adaptive_archive_http import client as archive_client
from app.adaptive_routes import build_adaptive_router
from app.adaptive_coordinator import AdaptiveCoordinator


def test_foreign_owner_cannot_export_retained_or_saved_pdf(completed,monkeypatch):
    _,repo,provider,plan,_=completed
    before=provider.calls
    monkeypatch.setenv('APP_MODE','local');monkeypatch.setenv('ADAPTIVE_PLANNING_PREVIEW','true')
    monkeypatch.setattr('app.itinerary_pdf.render_pdf',lambda *args:pytest.fail('Foreign request must not render'))
    engine=AdaptiveCoordinator(repo,None,enabled=True,require_health=False)
    app=FastAPI();app.include_router(build_adaptive_router(Auth(),engine));client=TestClient(app)
    path='/api/adaptive-plans/'+plan['id']+'/export'
    assert client.get(path,headers={'Accept':'application/pdf'}).status_code==401
    assert client.get(path,headers={'Authorization':'Bearer other','Accept':'application/pdf'}).status_code==404
    client,_,_=archive_client(completed);h={'Authorization':'Bearer owner'}
    body={'requestId':str(uuid4()),'title':'Private trip','expectedVersion':plan['version']}
    url='/api/adaptive-plans/'+plan['id']+'/save'
    client.post(url,headers=h,json=body);saved=client.post(url,headers=h,json=body).json()['savedId']
    path='/api/saved-adaptive-trips/'+saved+'/export'
    assert client.get(path).status_code==401
    assert client.get(path,headers={'Authorization':'Bearer other','Accept':'application/pdf'}).status_code==404
    assert provider.calls==before
