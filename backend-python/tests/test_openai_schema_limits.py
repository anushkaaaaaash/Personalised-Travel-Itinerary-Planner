"""Offline compatibility regression for OpenAI's documented strict schema limits."""
from datetime import date, timedelta
import pytest
from app.generation_contract import GenerationContract
from app.models import TripPreferences
from app.openai import strict_schema
from app.refinement_contract import check_shape


def assert_pure_refs(node):
    """OpenAI strict schemas must not put annotations beside a $ref.

    See openai/openai-python src/openai/lib/_pydantic.py ref handling.
    Keep shared enums referenced rather than inlining and exceeding enum limits.
    """
    if isinstance(node, dict):
        if '$ref' in node:
            assert set(node) == {'$ref'}, f"Reference has sibling keywords: {set(node) - {'$ref'}}"
        for value in node.values():
            assert_pure_refs(value)
    elif isinstance(node, list):
        for value in node:
            assert_pure_refs(value)


def enum_count(node):
    if isinstance(node, dict):
        return len(node.get('enum', [])) + sum(enum_count(value) for key, value in node.items() if key != 'enum')
    if isinstance(node, list):
        return sum(map(enum_count, node))
    return 0


@pytest.mark.parametrize('days',[1,6,14])
@pytest.mark.parametrize('pace',['relaxed','balanced','fast'])
def test_generation_schema_stays_within_total_enum_limit(payload,days,pace):
    payload.update(endDate=(date.fromisoformat(payload['startDate'])+timedelta(days=days-1)).isoformat(),travelPace=pace)
    contract=GenerationContract(TripPreferences.model_validate(payload))
    schema=strict_schema(contract.schema)
    assert_pure_refs(schema)
    assert enum_count(schema)<=1000
    gap=schema['$defs']['ActivityProposal']['properties']['gapBeforeMinutes']
    assert gap['$ref']==schema['$defs']['RequiredMainProposal']['properties']['gapBeforeMinutes']['$ref']
    for value in (0,1,239,240):check_shape(value,gap,schema)
    for value in (-1,241,0.5,True):
        with pytest.raises(ValueError):check_shape(value,gap,schema)
