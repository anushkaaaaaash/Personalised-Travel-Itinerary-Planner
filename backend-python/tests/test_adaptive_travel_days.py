"""Only original arrival/return transport days may ease adaptive pace."""
from copy import deepcopy
from datetime import date,timedelta
import pytest
from app.adaptive_planning import SectionSpec,SectionContract,AdaptiveError
from app.itineraries import validate_itinerary
from app.models import TripPreferences
from app.generation_contract import GenerationContract
from app.recommendations import RecommendationError
from app.section_repository import validate_checkpoint
from test_adaptive_planning import section_wire
from test_itineraries import generated


def travel_fixture(payload,generated,offset,pace='fast',duration=120):
    original={**payload,'travelPace':pace,'budget':100000,'endDate':(date.fromisoformat(payload['startDate'])+timedelta(days=8)).isoformat()}
    day=(date.fromisoformat(original['startDate'])+timedelta(days=offset)).isoformat()
    strategy={'summary':'Stay in destination through the final date (descriptive shorthand).','stays':[{'startDate':original['startDate'],'endDate':original['endDate'],'location':original['destination']}]}
    spec=SectionSpec.from_manifest(original,next_date=day,section_days=1,previous_boundary={'location':original['destination'],'lastActivityEnd':'20:00'} if offset else None,journey_strategy=strategy if offset else None)
    # Reuse valid synthetic prose/costs, then explicitly propose transport-only.
    template_spec=SectionSpec.from_manifest({**original,'travelPace':'balanced'},next_date=day,section_days=1,previous_boundary={'location':original['destination'],'lastActivityEnd':'20:00'} if offset else None,journey_strategy=strategy if offset else None)
    wire=section_wire({**original,'travelPace':'balanced'},generated,template_spec)
    transfer=deepcopy(wire['proposal']['days'][0]['activities'][0]);transfer.update(kind='transfer',durationMinutes=duration,sequence=1,gapBeforeMinutes=0)
    wire['proposal']['days'][0]['requiredMainActivities']={f'main_{i+1}':None for i in range({'relaxed':1,'balanced':2,'fast':3}[pace])}
    wire['proposal']['days'][0]['activities']=[transfer]
    return spec,wire


@pytest.mark.parametrize('offset',[0,8])
@pytest.mark.parametrize('pace',['relaxed','balanced','fast'])
def test_original_transport_days_allow_zero_without_altering_strategy(payload,generated,offset,pace):
    spec,wire=travel_fixture(payload,generated,offset,pace)
    result=SectionContract(spec).decode(wire)
    assert result['itinerary']['days'][0]['mainActivityCount']==0
    assert result['journeyStrategy']==wire['journeyStrategy']
    section={'start_date':spec.start.isoformat(),'end_date':spec.end.isoformat(),'input_boundary':{'location':spec.start_location},'final_section':spec.final,'departure_city':spec.original.departureCity,'budget_limit_cents':spec.remaining_cents}
    assert validate_checkpoint(result,section)==result
    with pytest.raises(RecommendationError):
        public={k:v for k,v in result['itinerary'].items() if k not in {'provider','model','estimatedTotalGroupCost','remainingBudget','refinementSummary'}}
        validate_itinerary(public,spec.preferences,'openai','gpt-6-luna')


@pytest.mark.parametrize('offset,duration',[(2,120),(3,240),(8,119),(0,60)])
def test_chunk_edges_or_insubstantial_transfers_do_not_relax_pace(payload,generated,offset,duration):
    spec,wire=travel_fixture(payload,generated,offset,duration=duration)
    with pytest.raises(AdaptiveError):SectionContract(spec).decode(wire)


def test_ordinary_generation_schema_still_requires_nonnull_main(payload):
    normal=GenerationContract(TripPreferences.model_validate(payload))
    slots=normal.schema['$defs']['GenerationDay']['properties']['requiredMainActivities']['properties']
    assert all('anyOf' not in slot for slot in slots.values())
    assert 'Travel-only or rest-only days do not satisfy' in normal.instructions

def test_nine_day_fast_trip_persists_final_transport_day(tmp_path,payload):
    import asyncio,json
    from uuid import uuid4
    from app.adaptive_sqlite import AdaptiveSQLiteGateway
    from app.section_repository import SectionCheckpointRepository
    from app.adaptive_worker import AdaptivePlanningWorker
    from test_adaptive_integration import FakeProvider,OWNER
    prefs={**payload,'startDate':'2028-01-01','endDate':'2028-01-09','budget':5000,'travelPace':'fast'}
    gateway=AdaptiveSQLiteGateway(tmp_path/'travel.sqlite',enabled=True,initialize=True)
    repo=SectionCheckpointRepository(gateway,enabled=True)
    class Provider(FakeProvider):
        async def create(self,*args):
            response=await super().create(*args)
            output=json.loads(self.outputs[response.response_id])
            for day in output['proposal']['days']:
                if day['date']==prefs['endDate']:
                    day['requiredMainActivities']={'main_1':None,'main_2':None,'main_3':None}
                    day['activities'][0].update(durationMinutes=120,sequence=1)
                else:
                    third=deepcopy(day['requiredMainActivities']['main_2']);third.update(id='a4',sequence=4,title='Third distinct visit '+day['date'])
                    day['requiredMainActivities']['main_3']=third
            self.outputs[response.response_id]=json.dumps(output)
            return response
    async def scenario():
        plan=await repo.create_plan(OWNER,str(uuid4()),prefs)
        provider=Provider(repo,prefs);worker=AdaptivePlanningWorker(repo,provider,enabled=True)
        for _ in range(6):await worker.tick()
        complete=await repo.get_plan(OWNER,plan['id'])
        assert complete['status']=='completed' and complete['completed_days']==9 and provider.calls==3
        rows=await repo.list_sections(OWNER,plan['id'])
        assert [d['mainActivityCount'] for row in rows for d in row['checkpoint']['itinerary']['days']]==[3]*8+[0]
        assert rows[-1]['checkpoint']['endLocation']==prefs['departureCity']
    asyncio.run(scenario())
