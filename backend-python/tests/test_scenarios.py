"""Deterministic prompt-contract scenarios, not evidence of live model quality."""
import copy
from datetime import date,timedelta
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.itineraries import ItineraryService

@pytest.mark.parametrize('travelers,pace,style,interests',[(1,'balanced','budget',['culture']),(2,'relaxed','luxury',['nature']),(5,'fast','budget',['adventure','culture'])])
def test_prompt_and_timeline_scenarios(travelers,pace,style,interests):
    preferences=dict(destination='Goa',departureCity='Mumbai',startDate='2028-12-11',endDate='2028-12-12',travelers=travelers,budget=5000,currency='INR',interests=interests,dietaryNeeds='vegetarian',mobilityConcerns='Avoid stairs',travelPace=pace,travelStyle=style)
    count={'relaxed':1,'balanced':2,'fast':3}[pace]
    days=[dict(date=(date(2028,12,11)+timedelta(days=i)).isoformat(),morning='Museum',afternoon='Nature walk',evening='Rest',dining='Check menus',dietaryNotes='Verify vegetarian options',mobilityNotes='Verify access',transitAndRest='Allow travel and breaks',mainActivityCount=count,interestTags=interests,
        activities=[dict(id=f'a{n}',title='Synthetic activity',startTime=f'{9+n*2:02d}:00',durationMinutes=60,notes='Verify schedule',latitude=None,longitude=None,fixedTime=False,kind='main') for n in range(count)],costs=dict(accommodation=100,meals=20,localTransport=10,activities=10,departureTravel=20)) for i in range(2)]
    class Provider:
        name,model='Synthetic','scenario';calls=0
        async def generate(self,messages,schema):
            self.calls+=1;text=str(messages)
            for value in ['Goa','Mumbai','vegetarian','Avoid stairs',pace,style]:assert value in text
            return dict(status='planned',destination='Goa',currency='INR',travelStyle=style,travelPace=pace,explanation='Synthetic contract fixture',warnings=['Verify all estimates.'],days=copy.deepcopy(days))
    provider=Provider();client=TestClient(create_app(itinerary_service=ItineraryService(provider)))
    result=client.post('/api/itineraries/generate',json=preferences)
    assert result.status_code==200,result.text
    assert [d['mainActivityCount'] for d in result.json()['days']]==[count,count]
    assert result.json()['saved'] is False and provider.calls==1
