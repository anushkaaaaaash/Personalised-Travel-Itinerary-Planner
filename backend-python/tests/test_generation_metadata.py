"""Regression for the real one-call provider failure: required vibe omitted.

Only the observed missing-property shape is reconstructed, not a captured itinerary.
"""
from copy import deepcopy
import pytest
from app.groq import strict_schema
from app.itineraries import ItineraryPayload
from app.refinement_contract import check_shape
from app.warning_contract import WarningContract
from app.recommendations import RecommendationError
from test_itineraries import generated
from test_warning_contract import proposal, run_provider
from app.generation_contract import SCHEDULE_NOTICE

def test_real_missing_vibe_shape_no_longer_requires_model_echo(payload, generated):
    data=proposal(generated);data.pop('vibe')
    old=strict_schema(WarningContract(ItineraryPayload.model_json_schema()).schema)
    with pytest.raises(ValueError):check_shape(data,old,old)
    contract=WarningContract(ItineraryPayload.model_json_schema(),generation=True)
    current=strict_schema(contract.schema)
    check_shape(data,current,current)
    result,calls=run_provider(payload,data)
    assert result.vibe is None and result.status=='planned'
    assert len(result.days)==len(data['days'])
    assert result.warnings==[data['warnings']['verificationWarning'],*data['warnings']['additionalWarnings'],SCHEDULE_NOTICE]
    wire=calls[0]['response_format']['json_schema']['schema']
    assert 'vibe' not in wire['properties'] and 'vibe' not in wire['required']
    assert 'Echo supplied vibe or null.' not in calls[0]['messages'][0]['content']

@pytest.mark.parametrize('vibe',['relaxed','budget',False,0,{},[]])
def test_generation_metadata_never_masks_conflicting_provider_vibe(generated,vibe):
    data=proposal(generated);data['vibe']=vibe
    with pytest.raises(RecommendationError):WarningContract(ItineraryPayload.model_json_schema(),generation=True).decode(data)

def test_generation_metadata_does_not_change_refinement_or_public_schema(generated):
    public=ItineraryPayload.model_json_schema();original=deepcopy(public)
    WarningContract(public,generation=True)
    assert public==original
    refinement=WarningContract(public)
    assert 'vibe' in strict_schema(refinement.schema)['required']
    data=proposal(generated);data['vibe']='relaxed'
    assert refinement.decode(data)['vibe']=='relaxed'

def test_missing_vibe_does_not_bypass_other_required_fields(payload,generated):
    data=proposal(generated);data.pop('vibe');data.pop('explanation')
    with pytest.raises(RecommendationError):run_provider(payload,data)

def test_infeasible_generation_also_derives_only_unset_vibe(payload,generated):
    data=proposal(generated);data.pop('vibe');data.update(status='infeasible',days=[])
    result,_=run_provider(payload,data)
    assert result.status=='infeasible' and result.vibe is None and result.days==[]

@pytest.mark.parametrize('violation',['timeline','budget'])
def test_missing_vibe_preserves_semantic_rejection(payload,generated,violation):
    data=proposal(generated);data.pop('vibe')
    if violation=='timeline':data['days'][0]['activities'][1]['startTime']='09:15'
    else:data['days'][0]['costs']['meals']=999999
    with pytest.raises(RecommendationError):run_provider(payload,data)
