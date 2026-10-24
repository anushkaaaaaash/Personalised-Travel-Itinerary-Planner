import copy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.groq import GroqProvider
from app.providers import create_provider
from test_itineraries import generated, NoStorage
from test_recommendations import recommendations
from test_private_refinement import request_for, proposal_for


@pytest.mark.parametrize('scope',['whole','day','uncapped'])
def test_normal_endpoint_routes_refinement_only_to_120b(monkeypatch,payload,generated,recommendations,scope):
    calls=[]
    request=request_for(payload,generated,cap=None if scope=='uncapped' else 2,
        target=generated['days'][1]['date'] if scope=='day' else None)
    public=copy.deepcopy(generated); public['vibe']='relaxed'
    response_body=proposal_for(request) if scope=='whole' else public
    outputs=[response_body,generated,recommendations]
    def handler(req):
        body=json.loads(req.content); calls.append(body)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(outputs[len(calls)-1])}}]})
    original_init=GroqProvider.__init__
    def offline_init(self,key,model='openai/gpt-oss-20b',transport=None):
        original_init(self,key,model,transport=httpx.MockTransport(handler))
    monkeypatch.setattr(GroqProvider,'__init__',offline_init)
    monkeypatch.setattr('app.providers.read_configuration',lambda:{'GROQ_API_KEY':'fake-offline-key-123','GROQ_MODEL':'openai/gpt-oss-20b'})
    client=TestClient(create_app(NoStorage()))
    before=request.previous.model_dump()
    response=client.post('/api/itineraries/refine',json=request.model_dump())
    assert response.status_code==200,response.text
    assert response.json()['model']=='openai/gpt-oss-120b'
    if scope=='day':
        assert response.json()['days'][0]==before['days'][0]
    assert client.post('/api/itineraries/generate',json=payload).status_code==200
    assert client.post('/api/recommendations',json=payload).status_code==200
    assert [call['model'] for call in calls]==['openai/gpt-oss-120b','openai/gpt-oss-20b','openai/gpt-oss-20b']
    assert all(c['max_completion_tokens']==4096 and c['response_format']['json_schema']['strict'] is True for c in calls)
    assert request.previous.model_dump()==before


def test_refinement_error_does_not_retry_or_mutate_previous(monkeypatch,payload,generated):
    request=request_for(payload,generated); before=request.model_dump(); calls=[]
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(400,json={'error':{'code':'json_validate_failed','message':'schema.days expected object'}})
    original_init=GroqProvider.__init__
    def offline_init(self,key,model='openai/gpt-oss-20b',transport=None):
        original_init(self,key,model,transport=httpx.MockTransport(handler))
    monkeypatch.setattr(GroqProvider,'__init__',offline_init)
    monkeypatch.setattr('app.providers.read_configuration',lambda:{'GROQ_API_KEY':'fake-offline-key-123'})
    response=TestClient(create_app(NoStorage())).post('/api/itineraries/refine',json=before)
    assert response.status_code==502
    assert response.json()['error']['code']=='AI_PROVIDER_FAILED'
    assert len(calls)==1 and calls[0]['model']=='openai/gpt-oss-120b'
    assert request.model_dump()==before


def test_gemini_selection_unchanged_for_refinement():
    provider=create_provider(configuration=lambda:{'AI_PROVIDER':'gemini','GEMINI_API_KEY':'fake-offline-key-123'},for_refinement=True)
    assert provider.name=='Google Gemini'

