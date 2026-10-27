from copy import deepcopy
from dataclasses import replace
from datetime import date,datetime,timezone,timedelta
from uuid import uuid4
import pytest
from app.adaptive_revision import RevisionRequest,prepare_revision,RevisionContract,RevisionCandidate,canonical_hash
from app.adaptive_planning import SectionSpec,SectionContract,AdaptiveError,cents
from test_adaptive_planning import section_wire
from test_itineraries import generated


def uid():return str(uuid4())
NOW=datetime(2026,10,27,tzinfo=timezone.utc)

@pytest.fixture
def base(payload,generated):
    preferences={**payload,'budget':10000};owner=uid();planid=uid();rows=[];spent=0;previous=None;strategy=None
    for offset in (0,3):
        start=(date.fromisoformat(preferences['startDate'])+timedelta(days=offset)).isoformat()
        spec=SectionSpec.from_manifest(preferences,next_date=start,spent_cents=spent,previous_boundary=previous,journey_strategy=strategy)
        checkpoint=SectionContract(spec).decode(section_wire(preferences,generated,spec))
        row=dict(id=uid(),plan_id=planid,user_id=owner,status='succeeded',version=4,sequence=len(rows)+1,
            start_date=spec.start.isoformat(),end_date=spec.end.isoformat(),input_boundary={'location':spec.start_location},
            budget_limit_cents=spec.remaining_cents,final_section=spec.final,departure_city=preferences['departureCity'],checkpoint=checkpoint)
        rows.append(row);spent+=checkpoint['spentCents'];strategy=checkpoint['journeyStrategy']
        last=checkpoint['itinerary']['days'][-1]['activities'][-1];h,m=map(int,last['startTime'].split(':'));end=h*60+m+last['durationMinutes']
        previous={'location':checkpoint['endLocation'],'lastActivityEnd':f'{end//60:02}:{end%60:02}'}
    plan=dict(id=planid,user_id=owner,status='completed',version=20,preferences=preferences,journey_strategy=strategy,
        completed_days=6,spent_cents=spent,total_budget_cents=cents(preferences['budget']),expires_at=(NOW+timedelta(hours=24)).isoformat(),next_date=None,active_section=None)
    return owner,plan,rows


def context(base,offset=1,instruction='Replace the museum with a quiet garden.'):
    owner,plan,rows=base
    target=(date.fromisoformat(plan['preferences']['startDate'])+timedelta(days=offset)).isoformat()
    request={'requestId':uid(),'targetDate':target,'instruction':instruction}
    return prepare_revision(owner,plan,iter(rows),request,now=NOW)


def wire(ctx,generated):
    value=section_wire(ctx.spec.original.model_dump(mode='json'),generated,ctx.spec)
    value['endLocation']=ctx.expected_end_location
    day=value['proposal']['days'][0]
    for activity in day['requiredMainActivities'].values():
        if activity:activity['title']='Revised '+activity['title']
    return value


def test_one_day_candidate_keeps_base_and_all_unselected_days_identical(base,generated):
    before=deepcopy(base);ctx=context(base);contract=RevisionContract(ctx)
    result=contract.decode(wire(ctx,generated))
    assert isinstance(result,RevisionCandidate) and result.accepted is False and result.status=='candidate'
    assert base==before
    old=ctx.target_section['checkpoint']['itinerary']['days'];new=result.checkpoint['itinerary']['days']
    for old_day,new_day in zip(old,new):
        if old_day['date']!=ctx.request.target_date:assert old_day==new_day and canonical_hash(old_day)==canonical_hash(new_day)
    assert result.total_spent_cents==ctx.locked_cost_cents+sum(cents(v) for v in new[1]['costs'].values())
    assert ctx.spec.remaining_cents==ctx.total_budget_cents-ctx.locked_cost_cents
    assert 'quiet garden' in contract.user_context and 'quiet garden' not in contract.instructions
    assert 'quiet garden' not in repr(ctx)


@pytest.mark.parametrize('offset',[0,2,3,5])
def test_target_first_last_and_section_boundaries(base,generated,offset):
    ctx=context(base,offset);candidate=RevisionContract(ctx).decode(wire(ctx,generated))
    assert candidate.target_date==ctx.request.target_date
    assert candidate.checkpoint['startLocation']==ctx.target_section['checkpoint']['startLocation']
    assert candidate.checkpoint['endLocation']==ctx.target_section['checkpoint']['endLocation']


@pytest.mark.parametrize('bad',[None,{}, {'requestId':'bad','targetDate':'2026-01-01','instruction':'x'},
    {'requestId':uid(),'targetDate':'2026-01-01','instruction':' '},
    {'requestId':uid(),'targetDate':'2026-01-01','instruction':'x'*2001},
    {'requestId':uid(),'targetDate':'2026-01-01','instruction':'bad\x00text'}])
def test_invalid_request_never_enters_revision(bad):
    with pytest.raises(AdaptiveError,match='REVISION_REQUEST_INVALID'):RevisionRequest.parse(bad)


@pytest.mark.parametrize('mutation',['owner','incomplete','expired','wrong_count','wrong_cost','gap','wrong_strategy','wrong_row_owner','wrong_row_id','wrong_order','oversize'])
def test_invalid_base_is_rejected_before_model(base,mutation):
    owner,plan,rows=deepcopy(base)
    if mutation=='owner':owner=uid()
    if mutation=='incomplete':plan['status']='paused'
    if mutation=='expired':plan['expires_at']=NOW.isoformat()
    if mutation=='wrong_count':plan['completed_days']=5
    if mutation=='wrong_cost':plan['spent_cents']+=1
    if mutation=='gap':rows.pop(0)
    if mutation=='wrong_strategy':rows[0]['checkpoint']['journeyStrategy']['summary']='Changed'
    if mutation=='wrong_row_owner':rows[0]['user_id']=uid()
    if mutation=='wrong_row_id':rows[0]['id']='bad'
    if mutation=='wrong_order':rows.reverse()
    if mutation=='oversize':rows[0]['checkpoint']['itinerary']['explanation']='x'*140000
    with pytest.raises(AdaptiveError):context((owner,plan,rows))


def test_outgoing_rest_boundary_is_enforced(base,generated):
    ctx=context(base);ctx=replace(ctx,next_day_first_minute=0)
    value=wire(ctx,generated)
    # Normal synthetic day ends15:00: nine hours rest passes. Force the following
    # immutable day boundary to an impossible preceding-day-relative value via
    # selected day20:00 schedule (last activity ends22:00).
    day=value['proposal']['days'][0];day['dayStart']='18:00'
    for item in [*day['requiredMainActivities'].values(),*day['activities']]:
        if item:item['gapBeforeMinutes']=0
    with pytest.raises(AdaptiveError,match='REVISION_REST_CONFLICT'):RevisionContract(ctx).decode(value)


def test_incoming_rest_budget_route_and_locked_duplicates_reject(base,generated):
    ctx=context(base)
    value=wire(ctx,generated);value['endLocation']='Other city'
    with pytest.raises(AdaptiveError):RevisionContract(ctx).decode(value)
    value=wire(ctx,generated);day=value['proposal']['days'][0];day['costs']['activities']=100000
    with pytest.raises(AdaptiveError):RevisionContract(ctx).decode(value)
    value=wire(ctx,generated);next(iter(value['proposal']['days'][0]['requiredMainActivities'].values()))['title']=next(iter(ctx.locked_main_titles))
    with pytest.raises(AdaptiveError):RevisionContract(ctx).decode(value)
    incoming=replace(ctx,spec=replace(ctx.spec,previous_end='24:00'))
    value=wire(incoming,generated);value['proposal']['days'][0]['dayStart']='00:00'
    for item in [*value['proposal']['days'][0]['requiredMainActivities'].values(),*value['proposal']['days'][0]['activities']]:
        if item:item['gapBeforeMinutes']=0
    with pytest.raises(AdaptiveError,match='SECTION_REST_CONFLICT'):RevisionContract(incoming).decode(value)


def test_mutated_context_and_widened_model_scope_rejected(base,generated):
    ctx=context(base);value=wire(ctx,generated);value['proposal']['days'].append(deepcopy(value['proposal']['days'][0]))
    with pytest.raises(AdaptiveError):RevisionContract(ctx).decode(value)
    ctx.target_section['checkpoint']['itinerary']['days'][0]['morning']='Changed after snapshot'
    with pytest.raises(AdaptiveError,match='REVISION_BASE_CHANGED'):RevisionContract(ctx).decode(wire(ctx,generated))


def test_infeasible_is_only_proposed_advice_not_replacement(base,generated):
    ctx=context(base);value=wire(ctx,generated);value['proposal'].update(status='infeasible',days=[])
    value['recommendations']=[{'field':'travelPace','reason':'Requested combination needs review.','suggestion':'Consider a different activity while preserving dates.'}]
    result=RevisionContract(ctx).decode(value)
    assert result['status']=='needs_changes' and result['applicability']=='proposed' and result['completed'] is False


def test_storage_scan_bound_applies_without_eager_trip_allocation(base,monkeypatch):
    monkeypatch.setattr('app.adaptive_revision.PLAN_STORAGE_BYTES',50000)
    with pytest.raises(AdaptiveError,match='REVISION_STORAGE_LIMIT'):context(base)


def test_fixed_commitment_cannot_be_silently_removed(base,generated):
    owner,plan,rows=deepcopy(base)
    rows[0]['checkpoint']['itinerary']['days'][1]['activities'][0]['fixedTime']=True
    ctx=context((owner,plan,rows))
    with pytest.raises(AdaptiveError,match='REVISION_FIXED_COMMITMENT_CONFLICT'):RevisionContract(ctx).decode(wire(ctx,generated))


def test_base_boundary_cannot_depart_from_structured_route(base):
    owner,plan,rows=deepcopy(base)
    rows[0]['checkpoint']['endLocation']='Unapproved route'
    rows[1]['checkpoint']['startLocation']='Unapproved route';rows[1]['input_boundary']['location']='Unapproved route'
    with pytest.raises(AdaptiveError,match='REVISION_ROUTE_CONFLICT'):context((owner,plan,rows))


def candidate_dto(candidate):
    return {'checkpoint':deepcopy(candidate.checkpoint),'totalSpentCents':candidate.total_spent_cents,'targetDate':candidate.target_date,
        'sourceDigest':candidate.source_digest,'baseVersion':candidate.base_version,'status':'candidate','accepted':False}


def test_persisted_candidate_revalidated_defensive_copy(base,generated):
    from app.adaptive_revision import validate_revision_candidate
    ctx=context(base);candidate=RevisionContract(ctx).decode(wire(ctx,generated));dto=candidate_dto(candidate)
    checked=validate_revision_candidate(ctx,dto)
    assert checked==candidate and checked.checkpoint is not dto['checkpoint']
    dto['checkpoint']['itinerary']['days'][0]['morning']='Changed later'
    assert checked==candidate


@pytest.mark.parametrize('kind',['extra','accepted','version_bool','version','digest','target','total','untouched','route','provenance','currency','rest','duplicate','cost','warnings','scope'])
def test_persisted_candidate_tampering_rejected(base,generated,kind):
    from app.adaptive_revision import validate_revision_candidate
    ctx=context(base);dto=candidate_dto(RevisionContract(ctx).decode(wire(ctx,generated)))
    cp=dto['checkpoint'];day=cp['itinerary']['days'][1]
    if kind=='extra':dto['verified']=True
    if kind=='accepted':dto['accepted']=True
    if kind=='version_bool':dto['baseVersion']=True
    if kind=='version':dto['baseVersion']+=1
    if kind=='digest':dto['sourceDigest']='wrong'
    if kind=='target':dto['targetDate']=cp['itinerary']['days'][0]['date']
    if kind=='total':dto['totalSpentCents']+=1
    if kind=='untouched':cp['itinerary']['days'][0]['morning']='Other day changed'
    if kind=='route':cp['endLocation']='Wrong'
    if kind=='provenance':cp['provenance']['verified']=True
    if kind=='currency':cp['itinerary']['currency']='USD'
    if kind=='rest':
        day['activities'][-1].update(startTime='23:00',durationMinutes=60)
        ctx=replace(ctx,next_day_first_minute=300)
    if kind=='duplicate':next(a for a in day['activities'] if a['kind']=='main')['title']=next(iter(ctx.locked_main_titles))
    if kind=='cost':day['costs']['activities']=10000000
    if kind=='warnings':cp['itinerary']['warnings']=['Removed original warning']
    if kind=='scope':cp['itinerary']['days'].pop()
    with pytest.raises(AdaptiveError):validate_revision_candidate(ctx,dto)
