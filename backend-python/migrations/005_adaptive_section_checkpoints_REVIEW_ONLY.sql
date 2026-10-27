-- REVIEW ONLY, DISABLED. No production application/role/cron activation is implied.
-- Separate reviewed gateway mappings, scoped worker RLS policies/grants and purge
-- schedule are prerequisites. No existing table/function is changed.
begin;
create table public.adaptive_plans (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 request_id uuid not null, input_hash text not null check(input_hash ~ '^[a-f0-9]{64}$'),
 preferences jsonb not null check(jsonb_typeof(preferences)='object' and octet_length(preferences::text)<=16384),
 start_date date not null, end_date date not null, next_date date,
 total_budget_cents bigint not null check(total_budget_cents>0 and total_budget_cents<=9007199254740991), spent_cents bigint not null default 0 check(spent_cents>=0),
 completed_days integer not null default 0 check(completed_days>=0),
 storage_limit_bytes bigint not null default 16777216 check(storage_limit_bytes>0),
 storage_used_bytes bigint not null default 49152 check(storage_used_bytes>=0 and storage_used_bytes<=storage_limit_bytes),
 previous_boundary jsonb not null, journey_strategy jsonb check(journey_strategy is null or octet_length(journey_strategy::text)<=16384), status text not null default 'active' check(status in ('active','paused','completed','cancelled')),
 pause_reason text, storage_pause_scope text check(storage_pause_scope in ('plan','global')),
 global_storage_limit_bytes bigint not null default 67108864 check(global_storage_limit_bytes=67108864), active_section uuid, remaining_creates integer not null check(remaining_creates between 0 and 12),
 initial_run_allowance integer not null check(initial_run_allowance between 1 and 12),
 version bigint not null default 1, created_at timestamptz not null default now(), expires_at timestamptz not null default now()+interval '24 hours',
 unique(user_id,request_id), unique(id,user_id), check(end_date>=start_date), check(spent_cents<=total_budget_cents),
 check(next_date is null or next_date between start_date and end_date), check(expires_at>created_at and expires_at<=created_at+interval '24 hours')
);
create table public.adaptive_sections (
 id uuid primary key default gen_random_uuid(), plan_id uuid not null, user_id uuid not null, request_id uuid not null,
 sequence integer not null check(sequence>0), requested_days integer not null check(requested_days between 1 and 3),
 retry_of uuid references public.adaptive_sections(id) on delete cascade, start_date date not null, end_date date not null,
 budget_limit_cents bigint not null check(budget_limit_cents>=0), input_boundary jsonb not null,
 final_section boolean not null, departure_city text not null,
 status text not null default 'queued' check(status in ('queued','submitting','running','succeeded','failed','submission_unknown','cancelled')),
 version bigint not null default 1, lease_token uuid, lease_until timestamptz, worker_id uuid, submitted_at timestamptz,
 provider_response_id text check(provider_response_id is null or provider_response_id ~ '^resp_[A-Za-z0-9_-]{1,192}$'),
 reserved_checkpoint_bytes bigint not null default 131072 check(reserved_checkpoint_bytes in (0,131072)),
 error_code text check(error_code is null or error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'), failure_details jsonb check(failure_details is null or octet_length(failure_details::text)<=8192), checkpoint jsonb, created_at timestamptz not null default now(),
 foreign key(plan_id,user_id) references public.adaptive_plans(id,user_id) on delete cascade,
 unique(plan_id,request_id), unique(plan_id,sequence), check(end_date>=start_date and end_date-start_date<3),
 check((status='succeeded')=(checkpoint is not null)), check(checkpoint is null or octet_length(checkpoint::text)<=131072)
);
create table public.adaptive_run_requests (
 plan_id uuid not null references public.adaptive_plans(id) on delete cascade, request_id uuid not null,
 run_allowance integer not null check(run_allowance between 1 and 12), primary key(plan_id,request_id)
);
create table public.adaptive_checkpoint_runtime(singleton boolean primary key default true check(singleton),last_purge_at timestamptz);
insert into public.adaptive_checkpoint_runtime(singleton) values(true);
create index adaptive_section_pending on public.adaptive_sections(status,created_at);
create index adaptive_plan_owner on public.adaptive_plans(user_id,id);
alter table public.adaptive_plans enable row level security;
alter table public.adaptive_sections enable row level security;
alter table public.adaptive_run_requests enable row level security;
alter table public.adaptive_checkpoint_runtime enable row level security;
revoke all on public.adaptive_plans,public.adaptive_sections,public.adaptive_run_requests,public.adaptive_checkpoint_runtime from anon,authenticated;
grant select,insert,update,delete on public.adaptive_plans,public.adaptive_sections,public.adaptive_run_requests,public.adaptive_checkpoint_runtime to service_role;

create function public.adaptive_create_plan(owner uuid,request_id uuid,preferences jsonb,input_hash text,budget_cents bigint,run_allowance integer)
returns setof public.adaptive_plans language plpgsql security invoker set search_path=public as $$
declare existing adaptive_plans;
begin
 perform pg_advisory_xact_lock(708432115);
 select * into existing from adaptive_plans p where p.user_id=owner and p.request_id=adaptive_create_plan.request_id;
 if found then
  if existing.input_hash<>adaptive_create_plan.input_hash or existing.initial_run_allowance<>run_allowance then raise exception 'Adaptive request conflict'; end if;
  return next existing; return;
 end if;
 -- Explicit queue/storage resources, not a calendar-duration cap.
 if (select count(*) from adaptive_plans where user_id=owner and status in ('active','paused') and expires_at>now())>=1
   or (select count(*) from adaptive_plans where status in ('active','paused') and expires_at>now())>=50 then
   raise exception 'Adaptive active-plan resource limit reached';
 end if;
 if (select coalesce(sum(storage_used_bytes),0) from adaptive_plans)+(select coalesce(sum(reserved_checkpoint_bytes),0) from adaptive_sections)+49152>67108864 then
  raise exception 'Adaptive global storage allowance reached';
 end if;
 if run_allowance not between 1 and 12 or jsonb_typeof(preferences)<>'object'
   or budget_cents<>((preferences->>'budget')::numeric*100) then raise exception 'Adaptive preferences invalid'; end if;
 return query insert into adaptive_plans(user_id,request_id,input_hash,preferences,start_date,end_date,next_date,total_budget_cents,previous_boundary,remaining_creates,initial_run_allowance)
 values(owner,request_id,input_hash,preferences,(preferences->>'startDate')::date,(preferences->>'endDate')::date,
   (preferences->>'startDate')::date,budget_cents,jsonb_build_object('location',preferences->>'departureCity','lastActivityEnd',null),run_allowance,run_allowance) returning *;
end $$;
create function public.adaptive_get_plan(owner uuid,plan uuid) returns setof public.adaptive_plans
language sql security invoker set search_path=public as $$ select * from adaptive_plans where user_id=owner and id=plan $$;
create function public.adaptive_find_request(owner uuid,request_id uuid) returns setof public.adaptive_plans
language sql security invoker set search_path=public as $$ select * from adaptive_plans p where p.user_id=owner and p.request_id=adaptive_find_request.request_id $$;
create function public.adaptive_get_section(owner uuid,section uuid) returns setof public.adaptive_sections
language sql security invoker set search_path=public as $$ select * from adaptive_sections where user_id=owner and id=section $$;
create function public.adaptive_list_sections(owner uuid,plan uuid,after_sequence integer,page_size integer)
returns setof public.adaptive_sections language plpgsql security invoker set search_path=public as $$
begin
 if page_size not between 1 and 3 or after_sequence<0 then raise exception 'Adaptive page bound invalid'; end if;
 return query select * from adaptive_sections s where s.user_id=owner and s.plan_id=plan and s.sequence>after_sequence order by s.sequence limit page_size;
end $$;
create function public.adaptive_recent_checkpoints(owner uuid,plan uuid) returns setof public.adaptive_sections
language sql security invoker set search_path=public as $$
 select * from adaptive_sections s where s.user_id=owner and s.plan_id=plan and s.status='succeeded' order by s.sequence desc limit 3
$$;
create function public.adaptive_next_section(owner uuid,plan uuid,request_id uuid,section_days integer)
returns setof public.adaptive_sections language plpgsql security invoker set search_path=public as $$
declare p adaptive_plans; prior adaptive_sections; created adaptive_sections;
begin
 perform pg_advisory_xact_lock(708432115);
 select * into p from adaptive_plans where id=plan and user_id=owner for update;
 if not found then return; end if;
 select * into prior from adaptive_sections s where s.plan_id=plan and s.request_id=adaptive_next_section.request_id;
 if found then if prior.requested_days<>section_days then raise exception 'Section request conflict'; end if; return next prior; return; end if;
 if section_days not between 1 and 3 then raise exception 'Adaptive section resource bound invalid'; end if;
 if p.status<>'active' or p.expires_at<=now() or p.active_section is not null or p.remaining_creates=0 or p.next_date is null then return; end if;
 if p.storage_used_bytes+16384+131072>p.storage_limit_bytes then
  update adaptive_plans set status='paused',pause_reason='STORAGE_LIMIT',storage_pause_scope='plan',version=version+1 where id=plan;
  return;
 end if;
 -- This is an application allocation, not a claim about hosted disk quota.
 -- Include still-retained expired rows until the separate purge removes them.
 if (select coalesce(sum(storage_used_bytes),0) from adaptive_plans)+(select coalesce(sum(reserved_checkpoint_bytes),0) from adaptive_sections)+16384+131072>67108864 then
  update adaptive_plans set status='paused',pause_reason='STORAGE_LIMIT',storage_pause_scope='global',version=version+1 where id=plan;
  return;
 end if;
 insert into adaptive_sections(plan_id,user_id,request_id,sequence,requested_days,start_date,end_date,budget_limit_cents,input_boundary,final_section,departure_city)
 values(plan,owner,request_id,(select coalesce(max(s.sequence),0)+1 from adaptive_sections s where s.plan_id=plan),section_days,
 p.next_date,least(p.end_date,p.next_date+section_days-1),p.total_budget_cents-p.spent_cents,p.previous_boundary,
 least(p.end_date,p.next_date+section_days-1)=p.end_date,p.preferences->>'departureCity') returning * into created;
 update adaptive_plans set active_section=created.id,storage_used_bytes=storage_used_bytes+16384,version=version+1 where id=plan;
 return next created;
end $$;
create function public.adaptive_claim_section(owner uuid,section uuid,worker uuid)
returns setof public.adaptive_sections language plpgsql security invoker set search_path=public as $$
declare p adaptive_plans; s adaptive_sections;
begin
 perform pg_advisory_xact_lock(708432116);
 select * into p from adaptive_plans where id=(select plan_id from adaptive_sections where id=section and user_id=owner) and user_id=owner for update;
 if not found or p.status<>'active' or p.expires_at<=now() then return; end if;
 select * into s from adaptive_sections where id=section and user_id=owner for update;
 if s.status='submitting' and (s.lease_until is null or s.lease_until<=now()) then
  update adaptive_sections set status='submission_unknown',reserved_checkpoint_bytes=0,error_code='SUBMISSION_UNKNOWN',lease_token=null,lease_until=null,version=version+1 where id=section;
  update adaptive_plans set status='paused',pause_reason='SUBMISSION_UNKNOWN',version=version+1 where id=p.id;
  return;
 end if;
 if s.status not in ('queued','running') or (s.lease_until is not null and s.lease_until>now()) then return; end if;
 if s.status='queued' and (select count(*) from adaptive_sections where status in ('submitting','running')
   or (status='queued' and lease_until>now())
   or (status in ('submission_unknown','cancelled','failed') and submitted_at>now()-interval '10 minutes'))>=2 then return; end if;
 return query update adaptive_sections set lease_token=gen_random_uuid(),lease_until=now()+interval '60 seconds',worker_id=worker,version=version+1 where id=section returning *;
end $$;
create function public.adaptive_claim_next(worker uuid) returns setof public.adaptive_sections
language plpgsql security invoker set search_path=public as $$
declare candidate adaptive_sections; ready adaptive_plans;
begin
 perform pg_advisory_xact_lock(708432116);
 -- Recover a process exit after accepting a checkpoint but before scheduling
 -- the next section. Deterministic per-frontier identity prevents duplicate work.
 for ready in select * from adaptive_plans where status='active' and expires_at>now()
  and active_section is null and next_date is not null and remaining_creates>0 order by created_at limit 3
 loop
  perform adaptive_next_section(ready.user_id,ready.id,md5(ready.id::text||':'||ready.next_date::text)::uuid,3);
 end loop;
 for candidate in select s.* from adaptive_sections s join adaptive_plans p on p.id=s.plan_id
  where p.status='active' and p.expires_at>now() and s.status in ('queued','running','submitting')
  and (s.lease_until is null or s.lease_until<=now()) order by (s.status='running') desc,s.created_at limit 3
 loop
  return query select * from adaptive_claim_section(candidate.user_id,candidate.id,worker);
  if found then return; end if;
 end loop;
end $$;

create function public.adaptive_transition_section(owner uuid,section uuid,lease uuid,expected_version bigint,next_status text,response_id text,failure_code text,checkpoint jsonb,failure_details jsonb default null)
returns setof public.adaptive_sections language plpgsql security invoker set search_path=public as $$
declare p adaptive_plans; s adaptive_sections; spent bigint; day_count integer; exact_dates boolean; last_entry jsonb; end_minute integer; boundary jsonb; strategy jsonb; stay jsonb; strategy_cursor date; end_location text;
begin
 select * into p from adaptive_plans where id=(select plan_id from adaptive_sections where id=section and user_id=owner) and user_id=owner for update;
 if not found or p.status<>'active' or p.expires_at<=now() then return; end if;
 select * into s from adaptive_sections where id=section and user_id=owner for update;
 if p.active_section is distinct from s.id or s.version is distinct from expected_version or s.lease_token is distinct from lease
  or s.lease_until is null or s.lease_until<=now() or lease is null then return; end if;
 if not ((s.status='queued' and next_status in ('submitting','failed')) or
   (s.status='submitting' and next_status in ('running','failed','submission_unknown')) or
   (s.status='running' and next_status in ('running','succeeded','failed'))) then return; end if;
 if next_status='submitting' and p.remaining_creates=0 then return; end if;
 if next_status='running' and coalesce(response_id,s.provider_response_id) is null then raise exception 'Provider identity required'; end if;
 if s.provider_response_id is not null and response_id is not null and response_id<>s.provider_response_id then raise exception 'Provider identity conflict'; end if;
 if (next_status='succeeded')<>(checkpoint is not null) then raise exception 'Checkpoint state mismatch'; end if;
 if failure_details is not null then
  if next_status<>'failed' or failure_code is distinct from 'SECTION_CONSTRAINT_CONFLICT'
   or jsonb_typeof(failure_details) is distinct from 'object' or octet_length(failure_details::text)>8192
   or not(failure_details ?& array['applicability','explanation','recommendations'])
   or (failure_details-array['applicability','explanation','recommendations'])<>'{}'::jsonb
   or failure_details->>'applicability' is distinct from 'proposed'
   or jsonb_typeof(failure_details->'explanation') is distinct from 'string' or length(failure_details->>'explanation') not between 1 and 500
   or jsonb_typeof(failure_details->'recommendations') is distinct from 'array'
   or jsonb_array_length(failure_details->'recommendations') not between 1 and 3 then raise exception 'Failure details invalid'; end if;
  if exists(select 1 from jsonb_array_elements(failure_details->'recommendations') r where jsonb_typeof(r)<>'object'
   or not(r ?& array['field','reason','suggestion']) or (r-array['field','reason','suggestion'])<>'{}'::jsonb
   or jsonb_typeof(r->'field') is distinct from 'string' or length(r->>'field') not between 1 and 500
   or jsonb_typeof(r->'reason') is distinct from 'string' or length(r->>'reason') not between 1 and 500
   or jsonb_typeof(r->'suggestion') is distinct from 'string' or length(r->>'suggestion') not between 1 and 500) then raise exception 'Failure recommendation invalid'; end if;
 end if;
 if next_status='succeeded' then
  if octet_length(checkpoint::text)>131072 or jsonb_typeof(checkpoint) is distinct from 'object'
   or not (checkpoint ?& array['itinerary','startLocation','endLocation','spentCents','provenance','journeyStrategy'])
   or jsonb_typeof(checkpoint->'provenance') is distinct from 'object'
   or jsonb_typeof(checkpoint->'spentCents') is distinct from 'number'
   or (checkpoint->>'spentCents')::numeric<>trunc((checkpoint->>'spentCents')::numeric)
   or jsonb_typeof(checkpoint->'itinerary'->'days') is distinct from 'array'
   or checkpoint->'itinerary'->>'status' is distinct from 'planned'
   or (checkpoint - array['itinerary','startLocation','endLocation','spentCents','provenance','journeyStrategy'])<>'{}'::jsonb
   or checkpoint->>'startLocation' is distinct from s.input_boundary->>'location'
   or length(checkpoint->>'endLocation') not between 1 and 200 or checkpoint->>'endLocation'<>btrim(checkpoint->>'endLocation')
   or (s.final_section and checkpoint->>'endLocation'<>s.departure_city)
   or checkpoint->'provenance'->>'provider' is distinct from 'openai' or checkpoint->'provenance'->>'model' is distinct from 'gpt-6-luna'
   or checkpoint->'provenance'->>'validationVersion' is distinct from 'adaptive-section-v1'
   or ((checkpoint->'provenance') - array['provider','model','validationVersion'])<>'{}'::jsonb then raise exception 'Checkpoint invalid'; end if;
  strategy=checkpoint->'journeyStrategy';
  if jsonb_typeof(strategy) is distinct from 'object' or octet_length(strategy::text)>16384
   or not(strategy ?& array['summary','stays']) or (strategy-array['summary','stays'])<>'{}'::jsonb
   or jsonb_typeof(strategy->'summary') is distinct from 'string' or length(strategy->>'summary') not between 1 and 1500
   or jsonb_typeof(strategy->'stays') is distinct from 'array' or jsonb_array_length(strategy->'stays') not between 1 and 12 then raise exception 'Journey strategy invalid'; end if;
  if p.journey_strategy is not null and p.journey_strategy<>strategy then raise exception 'Journey strategy immutable'; end if;
  strategy_cursor=p.start_date;
  for stay in select value from jsonb_array_elements(strategy->'stays') loop
   if jsonb_typeof(stay) is distinct from 'object' or not(stay ?& array['startDate','endDate','location'])
    or (stay-array['startDate','endDate','location'])<>'{}'::jsonb
    or (stay->>'startDate')::date is distinct from strategy_cursor or (stay->>'endDate')::date<(stay->>'startDate')::date
    or jsonb_typeof(stay->'location') is distinct from 'string' or length(stay->>'location') not between 1 and 200
    or stay->>'location'<>btrim(stay->>'location') then raise exception 'Journey strategy coverage invalid'; end if;
   if s.end_date between (stay->>'startDate')::date and (stay->>'endDate')::date then end_location=stay->>'location'; end if;
   strategy_cursor=(stay->>'endDate')::date+1;
  end loop;
  if strategy_cursor is distinct from p.end_date+1 then raise exception 'Journey strategy full coverage invalid'; end if;
  if not s.final_section and checkpoint->>'endLocation' is distinct from end_location then raise exception 'Journey strategy boundary mismatch'; end if;
  if exists(select 1 from jsonb_array_elements(checkpoint->'itinerary'->'days') day_new,
   lateral jsonb_array_elements(day_new->'activities') activity_new
   where activity_new->>'kind'='main' and exists(
    select 1 from adaptive_sections previous,lateral jsonb_array_elements(previous.checkpoint->'itinerary'->'days') day_old,
     lateral jsonb_array_elements(day_old->'activities') activity_old
    where previous.plan_id=p.id and previous.status='succeeded' and activity_old->>'kind'='main'
     and lower(btrim(activity_old->>'title'))=lower(btrim(activity_new->>'title')))) then raise exception 'Repeated principal activity'; end if;
  select count(*),bool_and(coalesce((d.value->>'date')::date=s.start_date+(d.ordinality::integer-1),false)) into day_count,exact_dates
   from jsonb_array_elements(checkpoint->'itinerary'->'days') with ordinality d(value,ordinality);
  if day_count<>s.end_date-s.start_date+1 or exact_dates is not true then raise exception 'Checkpoint coverage invalid'; end if;
  if exists(select 1 from jsonb_array_elements(checkpoint->'itinerary'->'days') d where
   jsonb_typeof(d->'costs') is distinct from 'object' or not((d->'costs') ?& array['accommodation','meals','localTransport','activities','departureTravel'])
   or ((d->'costs')-array['accommodation','meals','localTransport','activities','departureTravel'])<>'{}'::jsonb) then raise exception 'Checkpoint cost categories invalid'; end if;
  if exists(select 1 from jsonb_array_elements(checkpoint->'itinerary'->'days') d,lateral jsonb_each(d->'costs') c
   where jsonb_typeof(c.value) is distinct from 'number') then raise exception 'Checkpoint cost type invalid'; end if;
  select sum((c.value#>>'{}')::numeric*100)::bigint into spent from jsonb_array_elements(checkpoint->'itinerary'->'days') d,
   lateral jsonb_each(d->'costs') c;
  if exists(select 1 from jsonb_array_elements(checkpoint->'itinerary'->'days') d,lateral jsonb_each(d->'costs') c
   where (c.value#>>'{}')::numeric<0 or trunc((c.value#>>'{}')::numeric*100)<>(c.value#>>'{}')::numeric*100)
   or spent is null or spent>s.budget_limit_cents or spent<>((checkpoint->>'spentCents')::bigint) then raise exception 'Checkpoint cost invalid'; end if;
  last_entry=(checkpoint->'itinerary'->'days'->-1->'activities'->-1);
  end_minute=split_part(last_entry->>'startTime',':',1)::integer*60+split_part(last_entry->>'startTime',':',2)::integer+(last_entry->>'durationMinutes')::integer;
  if end_minute is null or end_minute not between 0 and 1440 then raise exception 'Checkpoint boundary invalid'; end if;
  boundary=jsonb_build_object('location',checkpoint->>'endLocation','lastActivityEnd',lpad((end_minute/60)::text,2,'0')||':'||lpad((end_minute%60)::text,2,'0'));
  if p.storage_used_bytes+octet_length(checkpoint::text)>p.storage_limit_bytes then raise exception 'Checkpoint storage reservation invalid'; end if;
  update adaptive_plans set spent_cents=spent_cents+spent,completed_days=completed_days+day_count,
   storage_used_bytes=storage_used_bytes+octet_length(checkpoint::text),journey_strategy=coalesce(journey_strategy,strategy),
   next_date=case when s.final_section then null else s.end_date+1 end,previous_boundary=boundary,active_section=null,
   status=case when s.final_section then 'completed' when remaining_creates=0 then 'paused' else 'active' end,
   pause_reason=case when not s.final_section and remaining_creates=0 then 'RESOURCE_ALLOWANCE_REACHED' else null end,version=version+1 where id=p.id;
 elsif next_status='submitting' then
  update adaptive_plans set remaining_creates=remaining_creates-1,version=version+1 where id=p.id;
 elsif next_status in ('failed','submission_unknown') then
  update adaptive_plans set status='paused',pause_reason=case when next_status='failed' then 'SECTION_FAILED' else 'SUBMISSION_UNKNOWN' end,version=version+1 where id=p.id;
 end if;
 return query update adaptive_sections set status=next_status,provider_response_id=coalesce(response_id,provider_response_id),
  reserved_checkpoint_bytes=case when next_status in ('succeeded','failed','submission_unknown') then 0 else reserved_checkpoint_bytes end,
  error_code=failure_code,failure_details=adaptive_transition_section.failure_details,checkpoint=adaptive_transition_section.checkpoint,version=version+1,
  submitted_at=case when next_status='submitting' then now() else submitted_at end,
  lease_token=case when next_status='submitting' then lease_token else null end,
  lease_until=case when next_status='submitting' then now()+interval '60 seconds' else null end where id=section returning *;
end $$;
create function public.adaptive_retry_section(owner uuid,section uuid,request_id uuid,section_days integer)
returns setof public.adaptive_sections language plpgsql security invoker set search_path=public as $$
declare p adaptive_plans; s adaptive_sections; existing adaptive_sections; created adaptive_sections;
begin
 perform pg_advisory_xact_lock(708432115);
 select * into p from adaptive_plans where id=(select plan_id from adaptive_sections where id=section and user_id=owner) and user_id=owner for update;
 if not found then return; end if;
 select * into existing from adaptive_sections x where x.plan_id=p.id and x.request_id=adaptive_retry_section.request_id;
 if found then if existing.retry_of is distinct from section or existing.requested_days<>section_days then raise exception 'Retry request conflict'; end if; return next existing; return; end if;
 select * into s from adaptive_sections where id=section and user_id=owner;
 if s.status<>'failed' or p.active_section<>s.id or p.status not in ('active','paused') or p.remaining_creates=0 or p.expires_at<=now() then return; end if;
 update adaptive_plans set status='active',pause_reason=null,active_section=null,version=version+1 where id=p.id;
 select * into created from adaptive_next_section(owner,p.id,request_id,section_days);
 if found then
  update adaptive_sections set retry_of=section where id=created.id returning * into created;
  return next created;
 end if;
end $$;
create function public.adaptive_continue_run(owner uuid,plan uuid,request_id uuid,run_allowance integer)
returns setof public.adaptive_plans language plpgsql security invoker set search_path=public as $$
declare p adaptive_plans; prior integer; needed bigint;
begin
 -- Same lock order as admission: global allocation first, then owner plan.
 perform pg_advisory_xact_lock(708432115);
 select * into p from adaptive_plans where id=plan and user_id=owner for update;
 if not found then return; end if;
 select r.run_allowance into prior from adaptive_run_requests r where r.plan_id=plan and r.request_id=adaptive_continue_run.request_id;
 if found then if prior<>run_allowance then raise exception 'Run request conflict'; end if; return next p; return; end if;
 if run_allowance not between 1 and 12 then raise exception 'Run allowance invalid'; end if;
 if p.status<>'paused' or p.expires_at<=now() then return; end if;
 if p.pause_reason='SECTION_FAILED' and exists (
  select 1 from adaptive_sections where id=p.active_section and user_id=owner
   and error_code in ('SECTION_CONSTRAINT_CONFLICT','SECTION_BUDGET_EXHAUSTED')
 ) then return; end if;
 if not (p.pause_reason='STORAGE_LIMIT' and p.storage_pause_scope='global')
  and not (p.pause_reason in ('RESOURCE_ALLOWANCE_REACHED','SECTION_FAILED') and p.remaining_creates=0) then return; end if;
 -- Charge every durable control/idempotency row. Shared-storage probes must
 -- also fit the next attempt, otherwise they are strictly read-like no-ops:
 -- no row, version change, allowance, or permanently consumed request ID.
 needed:=512;
 if p.pause_reason='STORAGE_LIMIT' then needed:=needed+16384+131072; end if;
 if p.storage_used_bytes+needed>p.storage_limit_bytes then
  return query update adaptive_plans set pause_reason='STORAGE_LIMIT',storage_pause_scope='plan',version=version+1 where id=plan returning *;
  return;
 end if;
 if (select coalesce(sum(storage_used_bytes),0) from adaptive_plans)
  +(select coalesce(sum(reserved_checkpoint_bytes),0) from adaptive_sections)+needed>67108864 then
  -- Preserve the original continuation intent (especially exhausted runs).
  return next p;
  return;
 end if;
 insert into adaptive_run_requests values(plan,request_id,run_allowance);
 return query update adaptive_plans set
  remaining_creates=case when p.pause_reason='STORAGE_LIMIT' and p.remaining_creates>0 then p.remaining_creates else run_allowance end,
  storage_used_bytes=storage_used_bytes+512,status='active',pause_reason=null,storage_pause_scope=null,version=version+1 where id=plan returning *;
end $$;
create function public.adaptive_cancel_plan(owner uuid,plan uuid) returns setof public.adaptive_plans
language plpgsql security invoker set search_path=public as $$
begin
 perform 1 from adaptive_plans where id=plan and user_id=owner for update;
 if not found then return; end if;
 update adaptive_sections set status='cancelled',reserved_checkpoint_bytes=0,lease_token=null,lease_until=null,version=version+1 where plan_id=plan and user_id=owner and status in ('queued','submitting','running','submission_unknown','failed');
 return query update adaptive_plans set status='cancelled',pause_reason=null,version=version+1 where id=plan and user_id=owner and status<>'completed' returning *;
end $$;
create function public.adaptive_purge_expired() returns bigint language plpgsql security invoker set search_path=public as $$
declare removed bigint;
begin
 delete from adaptive_plans where expires_at<=now(); get diagnostics removed=row_count;
 update adaptive_checkpoint_runtime set last_purge_at=now() where singleton=true; return removed;
end $$;
create function public.adaptive_checkpoint_health() returns table(schema_version integer,rpc_version integer,cleanup_fresh boolean)
language sql security invoker set search_path=public as $$
 select 1,1,coalesce((select last_purge_at>now()-interval '3 minutes' from adaptive_checkpoint_runtime where singleton=true),false)
 where to_regclass('public.adaptive_plans') is not null and to_regclass('public.adaptive_sections') is not null
  and to_regclass('public.adaptive_run_requests') is not null
  and to_regprocedure('public.adaptive_create_plan(uuid,uuid,jsonb,text,bigint,integer)') is not null
  and to_regprocedure('public.adaptive_claim_next(uuid)') is not null
  and to_regprocedure('public.adaptive_recent_checkpoints(uuid,uuid)') is not null
  and to_regprocedure('public.adaptive_transition_section(uuid,uuid,uuid,bigint,text,text,text,jsonb,jsonb)') is not null
  and to_regprocedure('public.adaptive_purge_expired()') is not null
$$;
-- Exact signatures only. Dedicated role setup must separately add narrow RLS
-- policies and grants; existing planning_queue_worker audit intentionally rejects
-- these new tables/RPCs until its whitelist is separately reviewed.
do $$ declare f record; begin
 for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='public' and p.proname in ('adaptive_create_plan','adaptive_get_plan','adaptive_find_request','adaptive_get_section','adaptive_list_sections','adaptive_recent_checkpoints','adaptive_next_section',
 'adaptive_claim_section','adaptive_claim_next','adaptive_transition_section','adaptive_retry_section','adaptive_continue_run','adaptive_cancel_plan','adaptive_purge_expired','adaptive_checkpoint_health') loop
 execute format('revoke all on function %s from public,anon,authenticated',f.signature);
 execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
commit;
