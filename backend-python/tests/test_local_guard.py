import asyncio
import pytest
from app.local_guard import LocalOnlyBoundary

@pytest.mark.parametrize('host,headers,allowed',[
 ('127.0.0.1',[],True),('::1',[],True),('testclient',[],True),
 ('192.168.1.4',[],False),('8.8.8.8',[],False),('',[],False),
 ('127.0.0.1',[(b'x-forwarded-for',b'8.8.8.8')],False),
 ('127.0.0.1',[(b'forwarded',b'for=8.8.8.8')],False),
],ids=['localhost','ipv6-local','testclient','lan','public','missing','proxy-xff','proxy-forwarded'])
def test_local_boundary(host,headers,allowed):
    reached=[];sent=[]
    async def endpoint(scope,receive,send):reached.append(True)
    async def receive():return {'type':'http.request','body':b''}
    async def send(message):sent.append(message)
    asyncio.run(LocalOnlyBoundary(endpoint)({'type':'http','client':(host,123),'headers':[(b'host',b'localhost:5000'),*headers]},receive,send))
    assert bool(reached)==allowed
    if not allowed: assert sent[0]['status']==503

@pytest.mark.parametrize('variable,value',[('RENDER','true'),('VERCEL','1'),('APP_ENV','production'),('APP_ENV','staging')])
def test_cloud_flag_fails_closed(monkeypatch,variable,value):
    monkeypatch.setenv(variable,value)
    test_local_boundary('127.0.0.1',[],False)


@pytest.mark.parametrize('headers', [
 [(b'host',b'evil.example')], [(b'origin',b'https://evil.example')],
 [(b'host',b'localhost.evil.example')], [(b'origin',b'null')],
 [(b'host',b'user@localhost')], [(b'host',b'localhost:bad')],
],ids=['rebind-host','foreign-origin','host-suffix','null-origin','userinfo','invalid-port'])
def test_dns_rebinding_and_foreign_origin(headers):
    test_local_boundary('127.0.0.1',headers,False)
