from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from app.adaptive_research import PublicResearchQuery
from app.adaptive_archive_sources import project_archive_sources,validate_archive_sources
from app.planning_repository import JobRepositoryError


def fixture():
    owner,plan,job=str(uuid4()),str(uuid4()),str(uuid4());received=datetime.now(timezone.utc)-timedelta(days=2)
    query=asdict(PublicResearchQuery('Paris','2028-01-01','2028-01-02'))
    pack={'query':query,'checked_at':received.isoformat(),'expires_at':(received+timedelta(hours=24)).isoformat(),
        'tool_calls':1,'text':'Museum opening hours vary.','sources':[{'url':'https://example.org/museum','title':'Museum','consulted':True,'cited':True}],
        'citations':[{'start':0,'end':6,'url':'https://example.org/museum','title':'Museum'}],
        'applicability':'unknown','evidence_status':'model_observations_and_inference_unverified'}
    section={'user_id':owner,'plan_id':plan,'status':'succeeded','research_source_id':job}
    row={'id':job,'user_id':owner,'plan_id':plan,'status':'succeeded','phase':'initial','query':query,'sourcepack':pack,'provider_response_id':'private'}
    return owner,section,row


def test_expired_notes_stay_historical_without_private_fields():
    o,s,r=fixture();notes=project_archive_sources(o,s,r)
    assert notes['evidenceStatus']=='historical_unverified' and notes['receivedAt']==r['sourcepack']['checked_at']
    assert set(notes)=={'receivedAt','expiresAt','text','sources','citations','applicability','evidenceStatus'}
    assert 'query' not in str(notes) and 'private' not in str(notes)
    notes['sources'][0]['title']='changed';assert r['sourcepack']['sources'][0]['title']=='Museum'


def test_no_link_means_no_latest_substitution():
    o,s,r=fixture();s['research_source_id']=None;assert project_archive_sources(o,s,r) is None


@pytest.mark.parametrize('kind',['owner','plan','id','status','section_status','query','future','naive','expiry','url','span','missing','extra','refresh_cap'])
def test_invalid_historical_projection_fails_closed(kind):
    o,s,r=fixture();p=r['sourcepack']
    if kind=='owner':r['user_id']=str(uuid4())
    elif kind=='plan':r['plan_id']=str(uuid4())
    elif kind=='id':r['id']=str(uuid4())
    elif kind=='status':r['status']='running'
    elif kind=='section_status':s['status']='failed'
    elif kind=='query':r['query']={**r['query'],'destination':'London'}
    elif kind=='future':p['checked_at']=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    elif kind=='naive':p['checked_at']='2026-01-01T00:00:00'
    elif kind=='expiry':p['expires_at']=p['checked_at']
    elif kind=='url':p['sources'][0]['url']='http://localhost/private'
    elif kind=='span':p['citations'][0]['end']=10000
    elif kind=='missing':p['citations']=[]
    elif kind=='extra':p['unexpected']='secret'
    else:r['phase']='refresh';p['tool_calls']=3
    with pytest.raises(JobRepositoryError,match='ARCHIVE_SOURCES_INVALID'):project_archive_sources(o,s,r)


@pytest.mark.parametrize('kind',['private','unsafe','title','size','claim','receipt'])
def test_untrusted_archive_notes_revalidated(kind):
    o,s,r=fixture();notes=project_archive_sources(o,s,r)
    if kind=='private':notes['query']='private'
    elif kind=='unsafe':notes['sources'][0]['url']='https://127.0.0.1/'
    elif kind=='title':notes['sources'][0]['title']='bad\x00'
    elif kind=='size':notes['text']='a'*70000
    elif kind=='claim':notes['evidenceStatus']='verified'
    else:notes['receivedAt']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    with pytest.raises(JobRepositoryError):validate_archive_sources(notes)
