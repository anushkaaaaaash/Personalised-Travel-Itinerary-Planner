from test_revision_sqlite import store,run
from test_revision_http import client
from test_itineraries import generated


def test_expense_http_is_owner_scoped_complete_and_read_only(store,monkeypatch):
    c,e,p=client(store,monkeypatch);url='/api/adaptive-plans/'+p['id']+'/expenses'
    response=c.get(url,headers={'Authorization':'Bearer owner'})
    assert response.status_code==200,response.text
    value=response.json()
    assert value['planId']==p['id'] and value['isComplete'] is True
    assert value['acceptedDays']==p['completed_days'] and value['totalSpentCents']==p['spent_cents']
    assert sum(value['categories'].values())==value['totalSpentCents']
    assert value['suggestedBufferCents']==(value['totalSpentCents']+9)//10
    assert value['scope']=='whole_group'
    assert run(e.repository.get_plan(p['user_id'],p['id']))==p
    assert c.get(url,headers={'Authorization':'Bearer other'}).status_code in (404,409)
