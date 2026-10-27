from test_openai import envelope
import copy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.openai import OpenAIProvider
from app.providers import create_provider
from test_itineraries import generated, NoStorage
from test_recommendations import recommendations
from test_private_refinement import request_for, proposal_for
from generation_fixture import private_proposal
from test_openai_schema_limits import assert_pure_refs


@pytest.mark.parametrize('scope',['whole','day','uncapped'])
def test_all_ai_endpoints_route_to_luna_max(monkeypatch,payload,generated,recommendations,scope):
    calls=[]
    request=request_for(payload,generated,cap=None if scope=='uncapped' else 2,
        target=generated['days'][1]['date'] if scope=='day' else None)
    public=copy.deepcopy(generated); public['vibe']='relaxed'
    public['warnings']={'verificationWarning':public['warnings'][0],'additionalWarnings':public['warnings'][1:]}
    response_body=proposal_for(request) if scope=='whole' else public
    generation=copy.deepcopy(generated)
    generation['warnings']={'verificationWarning':generation['warnings'][0],'additionalWarnings':generation['warnings'][1:]}
    outputs=[response_body,private_proposal(generation,payload),recommendations]
    def handler(req):
        body=json.loads(req.content); calls.append(body)
        return httpx.Response(200,json=envelope(json.dumps(outputs[len(calls)-1])))
    original_init=OpenAIProvider.__init__
    def offline_init(self,key,model='gpt-6-luna',transport=None,*,reasoning_effort='max'):
        original_init(self,key,model,transport=httpx.MockTransport(handler),reasoning_effort=reasoning_effort)
    monkeypatch.setattr(OpenAIProvider,'__init__',offline_init)
    monkeypatch.setattr('app.providers.read_configuration',lambda:{'OPENAI_API_KEY':'fake-offline-key-123','OPENAI_MODEL':'gpt-6-luna'})
    client=TestClient(create_app(NoStorage()))
    before=request.previous.model_dump()
    response=client.post('/api/itineraries/refine',json=request.model_dump())
    assert response.status_code==200,response.text
    assert response.json()['model']=='gpt-6-luna'
    if scope=='day':
        assert response.json()['days'][0]==before['days'][0]
    assert client.post('/api/itineraries/generate',json=payload).status_code==200
    assert client.post('/api/recommendations',json=payload).status_code==200
    assert [call['model'] for call in calls]==['gpt-6-luna','gpt-6-luna','gpt-6-luna']
    assert all(c['reasoning']=={'effort':'max'} and c['max_output_tokens']==32768 and c['text']['format']['strict'] is True for c in calls)
    for call in calls:
        assert_pure_refs(call['text']['format']['schema'])
    assert request.previous.model_dump()==before


def test_refinement_error_does_not_retry_or_mutate_previous(monkeypatch,payload,generated):
    request=request_for(payload,generated); before=request.model_dump(); calls=[]
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(400,json={'error':{'code':'json_validate_failed','message':'schema.days expected object'}})
    original_init=OpenAIProvider.__init__
    def offline_init(self,key,model='gpt-6-luna',transport=None,*,reasoning_effort='max'):
        original_init(self,key,model,transport=httpx.MockTransport(handler),reasoning_effort=reasoning_effort)
    monkeypatch.setattr(OpenAIProvider,'__init__',offline_init)
    monkeypatch.setattr('app.providers.read_configuration',lambda:{'OPENAI_API_KEY':'fake-offline-key-123'})
    response=TestClient(create_app(NoStorage())).post('/api/itineraries/refine',json=before)
    assert response.status_code==502
    assert response.json()['error']['code']=='AI_SCHEMA_REJECTED'
    assert len(calls)==1 and calls[0]['model']=='gpt-6-luna'
    assert request.model_dump()==before


@pytest.mark.parametrize('provider',['groq','gemini'])
def test_refinement_rejects_removed_providers(provider):
    from app.recommendations import RecommendationError
    with pytest.raises(RecommendationError):
        create_provider(configuration=lambda:{'AI_PROVIDER':provider,'OPENAI_API_KEY':'fake-offline-key-123'},for_refinement=True)
