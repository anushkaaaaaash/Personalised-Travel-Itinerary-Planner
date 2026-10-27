"""Offline deployment boundary checks; no container, Fly or provider calls."""
from pathlib import Path
import json
import tomllib
import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]
CONFIG=tomllib.loads((ROOT/'fly.toml').read_text())


def test_container_is_backend_only_nonroot_one_process():
    docker=(ROOT/'Dockerfile').read_text()
    copies=[line for line in docker.splitlines() if line.startswith('COPY ')]
    assert len(copies)==2 and all('backend-python/' in line for line in copies)
    assert 'USER 10001:10001' in docker and 'ca-certificates' in docker
    cmd=json.loads(next(line[4:] for line in docker.splitlines() if line.startswith('CMD ')))
    assert cmd[:4]==['python','-m','uvicorn','app.production:create_production_app']
    assert cmd[cmd.index('--workers')+1]=='1'
    assert cmd[cmd.index('--port')+1]==str(CONFIG['http_service']['internal_port'])
    assert '--no-access-log' in cmd and '--reload' not in cmd
    ignore=(ROOT/'.dockerignore').read_text().splitlines()
    assert '**' in ignore
    assert {line for line in ignore if line.startswith('!')}=={
        '!Dockerfile','!backend-python/','!backend-python/requirements.txt',
        '!backend-python/app/','!backend-python/app/*.py'}


def test_review_config_never_enables_storage_or_new_credentials():
    assert CONFIG['app']=='personalised-travel-itinerary-planner' and CONFIG['primary_region']=='sin'
    env=CONFIG['env']
    assert env['PLANNING_JOBS_ENABLED']=='false'
    assert env['SAVED_ITINERARIES_SCHEMA_VERIFIED']=='false'
    assert env['API_HOST']==CONFIG['app']+'.fly.dev'
    assert not any('KEY' in name or 'PASSWORD' in name or name=='PLANNING_DATABASE_URL' for name in env)
    assert CONFIG['http_service']['force_https'] is True
    assert CONFIG['http_service']['checks'][0]['headers']['Host']==env['API_HOST']
    assert not any(key in CONFIG for key in ('mounts','release_command','processes'))


def fake_verified_environment(monkeypatch):
    for name,value in CONFIG['env'].items():monkeypatch.setenv(name,value)
    monkeypatch.setenv('API_HOST','approved-api.fly.dev')
    monkeypatch.setenv('SAVED_ITINERARIES_SCHEMA_VERIFIED','true')
    monkeypatch.setenv('SUPABASE_URL','https://synthetic.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_synthetic')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-provider-only')


def test_fly_private_health_probe_requires_correct_host_and_keeps_auth(monkeypatch):
    from app.production import create_production_app
    fake_verified_environment(monkeypatch)
    with TestClient(create_production_app(),base_url='http://127.0.0.1:8080') as client:
        assert client.get('/api/health').status_code==400
        headers={'Host':'approved-api.fly.dev'}
        assert client.get('/api/health',headers=headers).status_code==200
        assert client.get('/api/auth/config',headers=headers).json()['planning_jobs_enabled'] is False
        assert client.get('/api/saved-itineraries',headers=headers).status_code==401
        assert client.get('/api/health',headers={**headers,'Origin':'https://unapproved.example'}).status_code==403


def test_unreviewed_fly_config_fails_startup(monkeypatch):
    from app.production import create_production_app
    fake_verified_environment(monkeypatch)
    monkeypatch.setenv('SAVED_ITINERARIES_SCHEMA_VERIFIED','false')
    with pytest.raises(ValueError):create_production_app()
