-- REVIEW ONLY. NOT APPLIED. Requires explicit DB + 24-hour temporary retention approval.
-- Queue data is separate from saved itineraries. Never auto-save to travel history.
-- Service-role only mutation; verified-owner route checks are still mandatory.
begin;
create table public.planning_jobs (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  request_id uuid not null,
  input_hash text not null check (input_hash ~ '^[a-f0-9]{64}$'),
  preferences jsonb not null,
  status text not null check (status in ('queued','submitting','running','succeeded','failed','submission_unknown','cancelled','expired')),
  provider_response_id text,
  result jsonb,
  evidence jsonb,
  error_code text,
  version integer not null default 1,
  lease_token uuid,
  lease_until timestamptz,
  worker_id uuid,
  cancel_requested boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null,
  unique(user_id,request_id),
  check (expires_at > created_at and expires_at <= created_at + interval '24 hours'),
  check ((status='succeeded') = (result is not null)),
  check (octet_length(preferences::text) <= 16384),
  check (result is null or octet_length(result::text) <= 131072),
  check (evidence is null or (status='succeeded' and octet_length(evidence::text)<=262144))
);
create index planning_jobs_pending on public.planning_jobs(status,created_at);
alter table public.planning_jobs enable row level security;
-- Raw queue rows contain provider IDs and leases: no browser table access.
revoke all on public.planning_jobs from anon, authenticated;
grant select,insert,update,delete on public.planning_jobs to service_role;

-- Atomic quotas include queued jobs and terminal tombstones; duplicate requests
-- remain readable without consuming another allowance. These are conservative
-- admission caps, not a guarantee of provider billing after ambiguous submission.
create function public.enqueue_planning_job(request_row jsonb) returns setof public.planning_jobs
language plpgsql security invoker set search_path=public as $$
declare existing public.planning_jobs; owner_id uuid; operation_id uuid;
begin
  owner_id := (request_row->>'user_id')::uuid;
  operation_id := (request_row->>'request_id')::uuid;
  perform pg_advisory_xact_lock(708432112);
  select * into existing from planning_jobs where user_id=owner_id and request_id=operation_id;
  if found then return next existing; return; end if;
  if (select count(*) from planning_jobs)>=1000
    or (select count(*) from planning_jobs where status in ('queued','submitting','running','submission_unknown'))>=100
    or (select count(*) from planning_jobs where user_id=owner_id and status in ('queued','submitting','running','submission_unknown'))>=2
    or (select count(*) from planning_jobs where user_id=owner_id and created_at>now()-interval '24 hours')>=12 then
      raise exception 'Planning admission limit reached';
  end if;
  return query insert into planning_jobs(id,user_id,request_id,input_hash,preferences,status,created_at,expires_at)
    values ((request_row->>'id')::uuid,owner_id,operation_id,request_row->>'input_hash',
      request_row->'preferences','queued',now(),now()+interval '24 hours') returning *;
end $$;
revoke all on function public.enqueue_planning_job(jsonb) from public,anon,authenticated;
grant execute on function public.enqueue_planning_job(jsonb) to service_role;

create function public.claim_planning_job(worker uuid) returns setof public.planning_jobs
language plpgsql security invoker set search_path=public as $$
declare selected public.planning_jobs;
begin
  -- Serialize global admission across workers; connection-local limits are not enough.
  perform pg_advisory_xact_lock(708432112);
  update planning_jobs set status='expired', result=null, evidence=null, error_code='JOB_EXPIRED',
    version=version+1, lease_token=null, lease_until=null, updated_at=now()
    where expires_at<=now() and status not in ('expired','cancelled');
  -- A crashed worker may have reached OpenAI before persisting the response ID.
  -- An expired submission lease is NEVER permission to issue a new paid request.
  update planning_jobs set status='submission_unknown', error_code='JOB_SUBMISSION_UNCONFIRMED',
    version=version+1, lease_token=null, lease_until=null, updated_at=now()
    where status='submitting' and lease_until<=now();
  if (select count(*) from planning_jobs where lease_until>now() and status in ('queued','submitting','running'))>=2 then return; end if;
  select * into selected from planning_jobs
    where status in ('queued','running') and expires_at>now()
      and (status='running' or (select count(*) from planning_jobs where status in ('submitting','running','submission_unknown')
        or (status in ('cancelled','expired') and created_at>now()-interval '10 minutes'))<2)
      and (lease_until is null or lease_until<=now())
    order by (status='running') desc,created_at,id for update skip locked limit 1;
  if not found then return; end if;
  return query update planning_jobs set worker_id=worker,lease_token=gen_random_uuid(),
    lease_until=now()+interval '60 seconds',version=version+1,updated_at=now()
    where id=selected.id returning *;
end $$;

create function public.transition_planning_job(job uuid,lease uuid,expected_version integer,
  next_status text,response_id text default null,output jsonb default null,failure_code text default null,evidence_payload jsonb default null)
returns setof public.planning_jobs language plpgsql security invoker set search_path=public as $$
begin
  return query update planning_jobs set status=next_status,
    provider_response_id=coalesce(response_id,provider_response_id), result=output,evidence=evidence_payload,
    error_code=failure_code,version=version+1,updated_at=now(),
    lease_until=case when next_status='submitting' then now()+interval '60 seconds' else null end,
    lease_token=case when next_status='submitting' then lease_token else null end
    where id=job and lease_token=lease and version=expected_version and lease_until>now()
      and expires_at>now() and not cancel_requested
      and ((status='queued' and next_status in ('submitting','failed','cancelled'))
        or (status='submitting' and next_status in ('running','failed','submission_unknown','cancelled'))
        or (status='running' and next_status in ('running','succeeded','failed','cancelled','expired')))
      and (next_status!='running' or coalesce(response_id,provider_response_id) is not null)
      and ((next_status='succeeded')=(output is not null))
    returning *;
end $$;

create function public.cancel_planning_job(owner uuid,job uuid) returns setof public.planning_jobs
language plpgsql security invoker set search_path=public as $$
begin
  -- Terminal result is invalidated immediately; cancelling provider computation is
  -- best effort and may still incur cost. Worker must separately cancel known ID.
  update planning_jobs set status='cancelled',cancel_requested=true,result=null,evidence=null,
    version=version+1,updated_at=now(),lease_token=null,lease_until=null
    where id=job and user_id=owner and status in ('queued','submitting','running');
  return query select * from planning_jobs where id=job and user_id=owner;
end $$;
revoke all on function public.claim_planning_job(uuid) from public,anon,authenticated;
revoke all on function public.transition_planning_job(uuid,uuid,integer,text,text,jsonb,text,jsonb) from public,anon,authenticated;
revoke all on function public.cancel_planning_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.claim_planning_job(uuid) to service_role;
grant execute on function public.transition_planning_job(uuid,uuid,integer,text,text,jsonb,text,jsonb) to service_role;
grant execute on function public.cancel_planning_job(uuid,uuid) to service_role;
-- Required approved maintenance: DELETE WHERE expires_at<=now(). Do not activate
-- without a verified purge schedule, retention disclosures and recovery runbook.
-- Additional queue health and cleanup functions in the same atomic migration.
create table public.planning_job_runtime (
  singleton boolean primary key default true check(singleton),
  last_purge_at timestamptz
);
insert into public.planning_job_runtime(singleton) values(true);
alter table public.planning_job_runtime enable row level security;
revoke all on public.planning_job_runtime from anon,authenticated;
grant select,update on public.planning_job_runtime to service_role;
create function public.purge_expired_planning_jobs() returns integer
language plpgsql security invoker set search_path=public as $$
declare removed integer;
begin
  delete from public.planning_jobs where expires_at<=now();
  get diagnostics removed = row_count;
  update public.planning_job_runtime set last_purge_at=now() where singleton=true;
  return removed;
end $$;
create function public.planning_queue_health() returns table(schema_version integer,rpc_version integer,cron_installed boolean,cleanup_fresh boolean)
language sql security invoker set search_path=public as $$
  select 1,1,exists(select 1 from pg_catalog.pg_extension where extname='pg_cron'),
    coalesce((select last_purge_at>now()-interval '3 minutes' from public.planning_job_runtime where singleton=true),false)
  where to_regclass('public.planning_jobs') is not null
    and to_regprocedure('public.enqueue_planning_job(jsonb)') is not null
    and to_regprocedure('public.claim_planning_job(uuid)') is not null
    and to_regprocedure('public.transition_planning_job(uuid,uuid,integer,text,text,jsonb,text,jsonb)') is not null
    and to_regprocedure('public.cancel_planning_job(uuid,uuid)') is not null;
$$;
revoke all on function public.purge_expired_planning_jobs() from public,anon,authenticated;
revoke all on function public.planning_queue_health() from public,anon,authenticated;
grant execute on function public.purge_expired_planning_jobs() to service_role;
grant execute on function public.planning_queue_health() to service_role;
-- Separate approval needed: install pg_cron, then schedule exactly:
-- select cron.schedule('purge-planning-jobs','* * * * *','select public.purge_expired_planning_jobs();');
-- Verify cron.job active, cron.job_run_details succeeded, and synthetic expired row
-- gone before setting PLANNING_CLEANUP_VERIFIED=true. No cron install runs here.
commit;
