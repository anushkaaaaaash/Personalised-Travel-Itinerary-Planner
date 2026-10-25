"""Synthetic-fixture encoder only; never used to repair real provider responses."""
from copy import deepcopy
from app.generation_contract import GenerationContract
from app.models import TripPreferences

def private_proposal(public,preferences):
    contract=GenerationContract(TripPreferences.model_validate(preferences))
    result={'status':public['status'],'explanation':public.get('explanation',''),
        'warnings':public.get('warnings'), 'days':[]}
    if public['status']=='infeasible':
        return result
    for i,day in enumerate(public['days']):
        value={k:deepcopy(day[k]) for k in (*contract.narratives,'interestTags','costs')}
        entries=[];value['date']=day['date']
        value['dayStart']=day['activities'][0]['startTime'];h,m=map(int,value['dayStart'].split(':'));end=h*60+m
        for j,activity in enumerate(day['activities']):
            assert activity.get('fixedTime') is False, 'Encoder accepts only synthetic non-fixed fixtures'
            entry=deepcopy(activity);h,m=map(int,entry.pop('startTime').split(':'))
            entry.pop('fixedTime',None);entry['gapBeforeMinutes']=h*60+m-end
            end=h*60+m+entry['durationMinutes'];entries.append(entry)
        value['activities']=entries;result['days'].append(value)
    return result
