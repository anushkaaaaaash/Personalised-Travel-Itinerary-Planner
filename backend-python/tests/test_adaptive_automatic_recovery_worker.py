"""Strict terminal proof and long same-response reconciliation; fake providers only."""
import json
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from app.adaptive_worker import AdaptivePlanningWorker
from app.openai_background import _parse,BackgroundError
from app.adaptive_planning import SectionSpec
from test_openai_background import envelope
from test_section_preview_store import setup,run
from test_adaptive_stream_worker import Client
from test_adaptive_planning import section_wire
from test_itineraries import generated

@pytest.mark.parametrize('code,expected', [('server_error','server_error'),('rate_limit_exceeded','rate_limit_exceeded'),('invalid_prompt',None),('insufficient_quota',None),('authentication_error',None),('PRIVATE',None),(None,None)])
def test_parser_carries_only_allowlisted_server_recovery_evidence(code,expected):
    response=_parse(json.dumps(envelope('failed',error={'code':code,'message':'PRIVATE ERROR'})).encode(),expected_id='resp_test123')
    assert response.recovery_reason==expected
    assert 'PRIVATE' not in repr(response) and 'PRIVATE' not in str(response.safe_metadata())

@pytest.mark.parametrize('reason,expected', [('max_output_tokens','max_output_tokens'),('max_messages',None),('content_filter',None),('steered',None),(None,None)])
def test_only_output_token_limit_is_automatically_recoverable(reason,expected):
    response=_parse(json.dumps(envelope('incomplete',incomplete_details={'reason':reason})).encode(),expected_id='resp_test123')
    assert response.recovery_reason==expected

def test_refusal_and_wrong_id_cannot_authorize_recovery():
    body=envelope('failed',error={'code':'server_error'},output=[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}])
    assert _parse(json.dumps(body).encode(),expected_id='resp_test123').recovery_reason is None
    with pytest.raises(BackgroundError):_parse(json.dumps(body).encode(),expected_id='resp_other')

def prepare(setup,client):
    _,clock,g,r,_,p,s=setup
    run(r.transition(p['user_id'],s['id'],s['lease_token'],s['version'],'running'))
    w=AdaptivePlanningWorker(r,client,enabled=True,deadline_seconds=1800,clock=lambda:datetime.fromtimestamp(clock[0],timezone.utc))
    return clock,g,r,p,s,w

def test_slow_known_response_keeps_same_id_and_original_submission_time(setup):
    client=Client([],status='in_progress');clock,g,r,p,s,w=prepare(setup,client)
    original=s['submitted_at'];clock[0]+=600
    first=run(w.tick());assert first['status']=='running' and first['submitted_at']==original
    clock[0]+=600
    fresh=AdaptivePlanningWorker(r,client,enabled=True,deadline_seconds=1800,clock=lambda:datetime.fromtimestamp(clock[0],timezone.utc))
    second=run(fresh.tick());assert second['status']=='running' and second['submitted_at']==original
    assert client.creates==0 and client.gets==2 and client.cancelled==0

def test_deadline_bounds_nonterminal_work_without_new_submission(setup):
    client=Client([],status='in_progress');clock,g,r,p,s,w=prepare(setup,client);clock[0]+=1800
    result=run(w.tick());assert result['error_code']=='SECTION_DEADLINE_REACHED'
    assert client.creates==0 and client.gets==1 and client.cancelled==1
    assert run(r.get_plan(p['user_id'],p['id']))['completed_days']==0

def test_completed_response_at_deadline_is_validated_not_discarded(setup,payload,generated):
    client=Client([],status='completed',output=json.dumps(section_wire(payload,generated,SectionSpec.from_manifest(payload))))
    clock,g,r,p,s,w=prepare(setup,client);clock[0]+=1800
    result=run(w.tick());assert result['status']=='succeeded'
    assert client.creates==0 and client.cancelled==0 and run(r.get_plan(p['user_id'],p['id']))['completed_days']==3

def test_expired_provider_response_stops_without_recreating(setup):
    class Missing(Client):
        async def retrieve(self,id):self.gets+=1;raise BackgroundError('BACKGROUND_HTTP_FAILED',phase='retrieve',http_status=404)
    client=Missing([]);clock,g,r,p,s,w=prepare(setup,client)
    result=run(w.tick());assert result['error_code']=='SECTION_RESPONSE_UNAVAILABLE'
    assert client.creates==0 and client.gets==1 and client.cancelled==0

@pytest.mark.parametrize('status,reason,refused,expected', [
    ('failed','server_error',False,'SECTION_AUTO_RETRYABLE_FAILURE'),
    ('failed','rate_limit_exceeded',False,'SECTION_AUTO_RETRYABLE_FAILURE'),
    ('incomplete','max_output_tokens',False,'SECTION_AUTO_RETRYABLE_INCOMPLETE'),
    ('failed',None,False,'SECTION_PROVIDER_FAILED'),
    ('failed','server_error',True,'SECTION_PROVIDER_FAILED'),
    ('cancelled','server_error',False,'SECTION_PROVIDER_FAILED'),
    ('incomplete','content_filter',True,'SECTION_PROVIDER_INCOMPLETE'),
])
def test_worker_classifies_only_terminal_allowlist(setup,status,reason,refused,expected):
    class Terminal(Client):
        async def retrieve(self,id):
            self.gets+=1
            return SimpleNamespace(response_id=id,status=status,refused=refused,recovery_reason=reason,output_text=None)
    client=Terminal([]);clock,g,r,p,s,w=prepare(setup,client);g.supports_auto_recovery=True
    result=run(w.tick());assert result['error_code']==expected
    assert client.creates==0 and client.gets==1


def test_mismatched_response_cannot_authorize_automatic_recovery(setup):
    class Wrong(Client):
        async def retrieve(self,id):return SimpleNamespace(response_id='resp_wrong',status='failed',refused=False,recovery_reason='server_error')
    client=Wrong([]);clock,g,r,p,s,w=prepare(setup,client);g.supports_auto_recovery=True
    result=run(w.tick());assert result['error_code']=='SECTION_RESPONSE_MISMATCH'
    assert client.creates==0 and run(r.get_plan(p['user_id'],p['id']))['status']=='paused'


def test_poll_transport_uncertainty_never_recreates_or_resets_timer(setup):
    class Offline(Client):
        async def retrieve(self,id):self.gets+=1;raise TimeoutError()
    client=Offline([]);clock,g,r,p,s,w=prepare(setup,client);clock[0]+=900
    pending=run(w.tick());assert pending['status']=='running' and pending['submitted_at']==s['submitted_at']
    clock[0]+=900
    stopped=run(w.tick());assert stopped['error_code']=='SECTION_DEADLINE_REACHED'
    assert client.creates==0 and client.cancelled==1 and client.gets==2


def test_legacy_gateway_does_not_receive_new_recovery_codes(setup):
    class Terminal(Client):
        async def retrieve(self,id):return SimpleNamespace(response_id=id,status='failed',refused=False,recovery_reason='server_error')
    client=Terminal([]);clock,g,r,p,s,w=prepare(setup,client);g.supports_auto_recovery=False
    result=run(w.tick());assert result['error_code']=='SECTION_PROVIDER_FAILED'
    assert run(r.get_plan(p['user_id'],p['id']))['status']=='paused'


def test_malformed_completed_output_requires_attention_not_paid_auto_replay(setup):
    client=Client([],status='completed',output='not JSON');clock,g,r,p,s,w=prepare(setup,client)
    result=run(w.tick());assert result['status']=='failed'
    assert run(r.get_plan(p['user_id'],p['id']))['status']=='paused' and client.creates==0

@pytest.mark.parametrize('http_status',[401,403])
def test_provider_auth_failure_stops_promptly_without_paid_replay(setup,http_status):
    class Denied(Client):
        async def retrieve(self,id):self.gets+=1;raise BackgroundError('BACKGROUND_HTTP_FAILED',phase='retrieve',http_status=http_status)
    client=Denied([]);clock,g,r,p,s,w=prepare(setup,client)
    result=run(w.tick());assert result['error_code']=='SECTION_PROVIDER_REJECTED'
    assert client.creates==0 and client.gets==1 and run(r.get_plan(p['user_id'],p['id']))['status']=='paused'
