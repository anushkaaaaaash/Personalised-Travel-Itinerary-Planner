import pytest
from app.cors import configured_frontend_origins

@pytest.mark.parametrize('value,expected',[
 ('',[]),('*',[]),('http://example.com',[]),('https://example.com',['https://example.com']),
 ('https://example.com/',['https://example.com']),('https://user:pass@example.com',[]),
 ('https://example.com/path',[]),('https://example.com?x=1',[]),('https://example.com:bad',[]),
 ('https://example.com\n.evil.com',[]),('https://example.com,https://evil.com',[]),
])
def test_explicit_origin(monkeypatch,value,expected):
    monkeypatch.setenv('FRONTEND_ORIGIN',value)
    assert configured_frontend_origins()==expected
