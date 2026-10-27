import asyncio
from dataclasses import asdict
import json
import httpx
import pytest
from app.adaptive_research import BackgroundResearchClient, PublicResearchQuery, build_public_query, build_research_request, parse_research_response
from app.openai_background import BackgroundActivation, BackgroundError
Q=PublicResearchQuery('Kyoto, Japan','2028-01-01','2028-06-01')
URL='https://www.city.kyoto.lg.jp/example'
def envelope(status='completed'):
    return {'object':'response','id':'resp_fake','status':status,'output':[] if status!='completed' else [
        {'type':'web_search_call','id':'ws_fake','status':'completed','action':{'type':'search','query':'Kyoto hours','sources':[{'type':'url','url':URL}]}},
        {'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Hours need checking. Weather remains unknown.','annotations':[{'type':'url_citation','url':URL,'title':'City guidance','start_index':0,'end_index':20}]}]}]}
def test_public_fields_only_fixed_high_wire():
    prefs={**asdict(Q),'notes':'PRIVATE','dietaryNeeds':'PRIVATE','mobilityConcerns':'PRIVATE','departureCity':'PRIVATE','access_token':'PRIVATE'}
    body=build_research_request(build_public_query(prefs,venue_labels=['Public museum']))
    assert 'PRIVATE' not in json.dumps(body)
    assert body['reasoning']=={'effort':'high'} and body['background'] is True and body['store'] is False
    assert body['max_tool_calls']==4 and build_research_request(Q,phase='refresh')['max_tool_calls']==2
    assert body['max_output_tokens']==16384 and body['service_tier']=='default'
@pytest.mark.parametrize('bad',['','   ','x\ny','x@y','https://example.com','x'*121])
def test_unsafe_label(bad):
    with pytest.raises(BackgroundError):build_public_query({**asdict(Q),'destination':bad})
@pytest.mark.parametrize('kwargs',[{'venue_labels':['a']*4},{'route_labels':'abc'},{'venue_labels':iter(['a'])}])
def test_bounded_labels(kwargs):
    with pytest.raises(BackgroundError):build_public_query(asdict(Q),**kwargs)
def test_actual_sources_citations_and_unknown_applicability():
    r=parse_research_response(envelope(),query=Q).result
    assert r.tool_calls==1 and r.applicability=='unknown'
    assert r.evidence_status=='model_observations_and_inference_unverified'
    assert r.sources[0].consulted and r.sources[0].cited and r.citations[0].start==0
    assert not hasattr(r,'trusted_records')
def test_citation_without_consulted_source_rejected():
    e=envelope();e['output'][1]['content'][0]['annotations'][0]['url']='https://example.com/cited'
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)
@pytest.mark.parametrize('mutation',[
 lambda e:e.update(status='invented'),lambda e:e['output'][0].update(status='in_progress'),
 lambda e:e['output'][0]['action'].update(type='tool'),
 lambda e:e['output'][0]['action']['sources'][0].update(url='javascript:alert(1)'),
 lambda e:e['output'][0]['action']['sources'][0].update(url='http://127.0.0.1/x'),
 lambda e:e['output'][1]['content'][0]['annotations'][0].update(start_index=True),
 lambda e:e['output'][1]['content'][0]['annotations'][0].update(end_index=100000),
 lambda e:e['output'][1]['content'][0]['annotations'][0].update(title='bad\x00text'),
 lambda e:e['output'].pop(0),lambda e:e['output'][1]['content'][0].update(text='x'*24001)])
def test_invalid_results(mutation):
    e=envelope();mutation(e)
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)
def test_open_find_count():
    e=envelope()
    for kind in ['open_page','find_in_page']:e['output'].insert(0,{'type':'web_search_call','status':'completed','action':{'type':kind,'url':URL}})
    assert parse_research_response(e,query=Q).result.tool_calls==3
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q,phase='refresh')
def client(handler):return BackgroundResearchClient('dummy_key_12345',activation=BackgroundActivation(True,True),cost_approved=True,transport=httpx.MockTransport(handler))
def test_default_gates():
    async def run():
        for approved,activation in [(False,BackgroundActivation(True,True)),(True,BackgroundActivation())]:
            c=BackgroundResearchClient('dummy_key_12345',activation=activation,cost_approved=approved,transport=httpx.MockTransport(lambda r:pytest.fail('network')))
            with pytest.raises(BackgroundError):await c.create(Q)
    asyncio.run(run())
def test_create_retrieve_cancel_once():
    calls=[]
    def handler(request):
        calls.append(request);return httpx.Response(200,json=envelope('queued') if len(calls)==1 else envelope())
    async def run():
        c=client(handler);r=await c.create(Q);assert r.response_id=='resp_fake'
        assert (await c.retrieve(r.response_id,query=Q)).result.sources[0].cited
        assert (await c.cancel(r.response_id)).result is None
    asyncio.run(run());assert len(calls)==3
    assert calls[1].url.params['include[]']=='web_search_call.action.sources'
    assert json.loads(calls[0].content)==build_research_request(Q)
@pytest.mark.parametrize('status,ambiguous',[(400,False),(401,False),(429,False),(500,True),(302,True)])
def test_http_no_retry_no_raw_error(status,ambiguous):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,text='SECRET RAW BODY',headers={'Location':'https://evil.example/'})
    async def run():
        with pytest.raises(BackgroundError) as caught:await client(handler).create(Q)
        assert caught.value.ambiguous_create is ambiguous and 'SECRET' not in str(caught.value)
    asyncio.run(run());assert len(calls)==1
def test_timeout_and_invalid_success_ambiguous():
    for timeout in [False,True]:
        calls=[]
        def handler(request):
            calls.append(request)
            if timeout:raise httpx.ReadTimeout('SECRET')
            return httpx.Response(200,text='invalid',headers={'content-type':'application/json'})
        async def run():
            with pytest.raises(BackgroundError) as caught:await client(handler).create(Q)
            assert caught.value.ambiguous_create and 'SECRET' not in str(caught.value)
        asyncio.run(run());assert len(calls)==1

def test_persistence_pack_binding_and_bounds():
    from app.adaptive_research import serialize_research_result,validate_research_pack,public_query_from_dict
    pack=serialize_research_result(parse_research_response(envelope(),query=Q).result)
    assert validate_research_pack(pack,query=public_query_from_dict(pack['query']))==pack
    for mutate in [lambda p:p.update(applicability='verified'),lambda p:p.update(extra='bad'),lambda p:p['query'].update(destination='Osaka'),lambda p:p.update(tool_calls=True),lambda p:p['sources'][0].update(cited=False),lambda p:p['citations'][0].update(title='invented'),lambda p:p.update(checked_at='2028-01-01'),lambda p:p.update(text='界'*24000)]:
        bad=json.loads(json.dumps(pack));mutate(bad)
        with pytest.raises(BackgroundError):validate_research_pack(bad,query=Q)

@pytest.mark.parametrize('kind',['missing_citation','http_source','multiple_text'])
def test_grounding_minimum(kind):
    e=envelope()
    if kind=='missing_citation':e['output'][1]['content'][0]['annotations']=[]
    elif kind=='http_source':e['output'][0]['action']['sources'][0]['url']='http://example.com/'
    else:e['output'][1]['content'].append({'type':'output_text','text':'second','annotations':[]})
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)

def test_checked_and_expiry_are_receipt_freshness_not_publisher_time():
    from datetime import datetime,timedelta,timezone
    from app.adaptive_research import serialize_research_result,validate_research_pack
    now=datetime(2026,10,27,tzinfo=timezone.utc)
    result=parse_research_response(envelope(),query=Q,checked_at=now).result
    pack=serialize_research_result(result,now=now)
    assert validate_research_pack(pack,query=Q,now=now+timedelta(hours=23))==pack
    for clock in [now-timedelta(seconds=1),now+timedelta(hours=24)]:
        with pytest.raises(BackgroundError):validate_research_pack(pack,query=Q,now=clock)
    pack['expires_at']=(now+timedelta(hours=25)).isoformat()
    with pytest.raises(BackgroundError):validate_research_pack(pack,query=Q,now=now)

@pytest.mark.parametrize('url',[
 'https://printer.local/','https://printer.ｌｏｃａｌ/','https://team.internal/','https://sub.localhost/',
 'https://demo.test/','https://demo.invalid/','https://host.home.arpa/',
 'https://HOST.LOCAL./','https://127.1/','https://2130706433/',
 'https://%31%32%37.0.0.1/','https://[::1]/','https://host.example/',
 'https://public.example.com:8443/','https://host.lan/'])
def test_private_reserved_source_hosts_rejected(url):
    e=envelope();e['output'][0]['action']['sources'][0]['url']=url
    e['output'][1]['content'][0]['annotations'][0]['url']=url
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)

@pytest.mark.parametrize('topic',['places','hours','transport','bookings','closures'])
def test_closed_trigger_topics_copy_only_original_public_fields(topic):
    from app.adaptive_research import build_trigger_query,public_query_from_dict
    prefs={**asdict(Q),'departureCity':'Singapore','notes':'PRIVATE','mobilityConcerns':'PRIVATE','dietaryNeeds':'PRIVATE','searchQuery':'PRIVATE','venueLabels':['PRIVATE'],'routeLabels':['PRIVATE']}
    q=build_trigger_query(prefs,topic)
    assert q.researchTopic==topic and q.venueLabels==()
    assert q.routeLabels==(('Singapore',) if topic=='transport' else ())
    assert 'PRIVATE' not in json.dumps(build_research_request(q))
    assert public_query_from_dict(asdict(q))==q

@pytest.mark.parametrize('topic',['weather','find my PRIVATE medical clinic','',None,True,{'query':'PRIVATE'}])
def test_trigger_rejects_non_enum(topic):
    from app.adaptive_research import build_trigger_query
    with pytest.raises(BackgroundError):build_trigger_query({**asdict(Q),'departureCity':'Singapore'},topic)

def test_query_topic_binding():
    from app.adaptive_research import serialize_research_result,validate_research_pack
    pack=serialize_research_result(parse_research_response(envelope(),query=Q).result)
    pack['query']['researchTopic']='hours'
    with pytest.raises(BackgroundError):validate_research_pack(pack,query=Q)

@pytest.mark.parametrize('action_type',['open_page','find_in_page'])
def test_actual_open_find_url_counts_as_consulted_not_invented_citation(action_type):
    e=envelope();e['output'][0]['action']={'type':action_type,'url':URL,**({'pattern':'hours'} if action_type=='find_in_page' else {})}
    result=parse_research_response(e,query=Q).result
    assert result.tool_calls==1 and result.sources[0].consulted and result.sources[0].cited
    e['output'][0]['action']['url']='https://example.com/different'
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)

def test_research_final_phase_uses_only_final_text_citation_offsets():
    from copy import deepcopy
    e=envelope();final=e['output'][1];final['phase']='final_answer'
    commentary=deepcopy(final);commentary['phase']='commentary'
    commentary['content']=[{'type':'output_text','text':'Looking up information.','annotations':[]}]
    e['output'].insert(0,commentary)
    result=parse_research_response(e,query=Q).result
    assert result.text.startswith('Hours need') and result.citations[0].start==0

@pytest.mark.parametrize('url',['http://example.com','https://127.0.0.1','https://example.internal','https://example.com:444'])
def test_open_action_source_still_obeys_public_https_guard(url):
    e=envelope();e['output'][0]['action']={'type':'open_page','url':url}
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)

@pytest.mark.parametrize('action',[{'type':'open_page'},{'type':'open_page','url':None}])
def test_optional_open_url_absent_preserves_other_actual_source(action):
    e=envelope();e['output'].insert(1,{'type':'web_search_call','status':'completed','action':action})
    result=parse_research_response(e,query=Q).result
    assert result.tool_calls==2 and result.sources[0].consulted

def test_null_search_sources_needs_other_actual_consultation():
    e=envelope();e['output'][0]['action']['sources']=None
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)
    e['output'].insert(1,{'type':'web_search_call','status':'completed','action':{'type':'open_page','url':URL}})
    assert parse_research_response(e,query=Q).result.tool_calls==2

@pytest.mark.parametrize('url',[None,''])
def test_find_page_url_remains_required(url):
    e=envelope();e['output'].insert(1,{'type':'web_search_call','status':'completed','action':{'type':'find_in_page','url':url,'pattern':'hours'}})
    with pytest.raises(BackgroundError):parse_research_response(e,query=Q)

@pytest.mark.parametrize('mutation,reason',[
 (lambda e:e.update(output='PRIVATE_HOSTILE'), 'research_envelope'),
 (lambda e:e['output'][0].update(status='PRIVATE_HOSTILE'), 'research_calls'),
 (lambda e:e['output'][0]['action']['sources'][0].update(url='https://PRIVATE_HOSTILE.internal'), 'research_sources'),
 (lambda e:e['output'][1]['content'][0]['annotations'][0].update(title='PRIVATE_HOSTILE\x00'), 'citation_title'),
 (lambda e:e['output'][1].update(phase='PRIVATE_HOSTILE'), 'message_phase'),
])
def test_research_stage_diagnostics_are_closed_and_preserve_base_reason(mutation,reason):
    e=envelope();mutation(e)
    c=BackgroundResearchClient('fake-background-test-key',activation=BackgroundActivation(True,True),cost_approved=True,
        transport=httpx.MockTransport(lambda _:httpx.Response(200,json=e)))
    with pytest.raises(BackgroundError) as failure:asyncio.run(c.retrieve('resp_fake',query=Q))
    metadata=failure.value.safe_metadata()
    assert metadata['parse_reason']==reason and metadata['http_status']==200
    assert 'PRIVATE_HOSTILE' not in json.dumps(metadata)

@pytest.mark.parametrize('consulted,cited',[
 ('https://example.com/page?x=1#part','https://EXAMPLE.COM/page?x=1#part'),
 ('https://example.com/page','https://example.com:443/page'),
 ('https://bücher.de/page','https://xn--bcher-kva.de/page'),
])
def test_equivalent_authority_matches_actual_consulted_url(consulted,cited):
    e=envelope();e['output'][0]['action']['sources'][0]['url']=consulted
    e['output'][1]['content'][0]['annotations'][0]['url']=cited
    result=parse_research_response(e,query=Q).result
    assert result.sources[0].url==consulted and result.citations[0].url==consulted
    assert result.text==e['output'][1]['content'][0]['text']

@pytest.mark.parametrize('other',['https://example.com/other?x=1#part','https://example.com/page?x=2#part','https://example.com/page?x=1#other','https://other.example.com/page?x=1#part','https://example.com./page?x=1#part'])
def test_resource_path_query_fragment_and_host_not_guessed(other):
    e=envelope();e['output'][0]['action']['sources'][0]['url']='https://example.com/page?x=1#part'
    e['output'][1]['content'][0]['annotations'][0]['url']=other
    with pytest.raises(BackgroundError) as failure:parse_research_response(e,query=Q,expected_id='resp_fake')
    assert failure.value.parse_reason=='citation_unconsulted' and failure.value.confirmed_terminal is True

@pytest.mark.parametrize('title,expected',[('  Public\n page\t title  ','Public page title'),('x'*301,'www.city.kyoto.lg.jp')])
def test_display_title_normalization_does_not_change_claim_or_provenance(title,expected):
    e=envelope();e['output'][1]['content'][0]['annotations'][0]['title']=title
    result=parse_research_response(e,query=Q).result
    assert result.citations[0].title==expected and result.sources[0].title==expected
    assert result.citations[0].url==URL and result.text==e['output'][1]['content'][0]['text']

def test_repeated_source_titles_have_one_consistent_display_label():
    e=envelope();a=e['output'][1]['content'][0]['annotations'];a.append({**a[0],'title':'Alternate valid label'})
    result=parse_research_response(e,query=Q).result
    assert len(result.citations)==2 and {c.title for c in result.citations}=={'City guidance'}

def test_confirmed_terminal_requires_bound_completed_identity_and_survives_http():
    e=envelope();e['output'][1]['content'][0]['annotations']=[]
    for expected,confirmed in [(None,False),('resp_fake',True),('resp_other',False)]:
        with pytest.raises(BackgroundError) as failure:parse_research_response(e,query=Q,expected_id=expected)
        assert failure.value.confirmed_terminal is confirmed
    c=BackgroundResearchClient('fake-background-test-key',activation=BackgroundActivation(True,True),cost_approved=True,
        transport=httpx.MockTransport(lambda _:httpx.Response(200,json=e)))
    with pytest.raises(BackgroundError) as failure:asyncio.run(c.retrieve('resp_fake',query=Q))
    assert failure.value.confirmed_terminal is True and failure.value.safe_metadata()['parse_reason']=='citation_missing'
    e['status']='in_progress'
    assert asyncio.run(c.retrieve('resp_fake',query=Q)).status=='in_progress'

@pytest.mark.parametrize('mutation,reason',[
 (lambda a:a.update(type='file_citation'),'citation_shape'),
 (lambda a:a.update(end_index=100000),'citation_span'),
 (lambda a:a.update(title='bad\x00'),'citation_title'),
 (lambda a:a.update(url='https://localhost/private'),'citation_url'),
 (lambda a:a.update(url='https://example.com/other'),'citation_unconsulted'),
])
def test_precise_citation_failure_is_terminal_only_after_valid_completed_envelope(mutation,reason):
    e=envelope();mutation(e['output'][1]['content'][0]['annotations'][0])
    with pytest.raises(BackgroundError) as failure:parse_research_response(e,query=Q,expected_id='resp_fake')
    assert failure.value.parse_reason==reason and failure.value.confirmed_terminal is True

def test_practical_research_prompt_retains_public_only_high_bounded_policy():
    request=build_research_request(Q)
    text=request['input'][0]['content']
    assert 'named real attraction and dining candidates' in text and 'public-route options' in text
    assert 'not a booking or confirmed personal suitability' in text
    assert request['reasoning']=={'effort':'high'} and request['max_tool_calls']==4
