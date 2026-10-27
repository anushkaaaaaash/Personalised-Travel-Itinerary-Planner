-- REVIEW ONLY. Explicit owner cancellation may abandon an uncertain submission.
-- This is additive: do not rewrite already-applied migration 003.
-- No provider request is retried, and no claim is made that upstream work stopped.
-- The existing claim RPC reserves cancelled jobs for 10 minutes from created_at;
-- this migration does not relax that conservative provider-capacity reservation.
begin;
do $$
begin
  if to_regprocedure('public.cancel_planning_job(uuid,uuid)') is null then
    raise exception 'Migration 003 cancel RPC is required before migration 004';
  end if;
end $$;
create or replace function public.cancel_planning_job(owner uuid,job uuid)
returns setof public.planning_jobs
language plpgsql security invoker set search_path=public as $$
begin
  update planning_jobs set status='cancelled',cancel_requested=true,result=null,evidence=null,
    version=version+1,updated_at=now(),lease_token=null,lease_until=null
    where id=job and user_id=owner
      and status in ('queued','submitting','running','submission_unknown');
  -- Keep identity/hash tombstone: replaying this request returns cancelled,
  -- never another enqueue/create. Unknown provider identity stays unknown.
  return query select * from planning_jobs where id=job and user_id=owner;
end $$;
-- CREATE OR REPLACE preserves the existing function's ownership and EXECUTE ACL;
-- intentionally no broad grants, new roles, RLS changes or data deletion here.
commit;
