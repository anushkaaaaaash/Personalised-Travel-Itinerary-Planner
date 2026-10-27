-- REVIEW ONLY. Apply only after approving adaptive005 + exact gateway/audit scope.
-- Does not create a LOGIN/password or alter existing role flags/auth behavior.
begin;
do $$ declare r record; begin
 select * into r from pg_roles where rolname='planning_queue_worker';
 if not found or r.rolsuper or r.rolcreatedb or r.rolcreaterole or r.rolreplication or r.rolbypassrls
  or exists(select 1 from pg_auth_members where member=r.oid) then
  raise exception 'Pre-existing isolated planning queue role is required';
 end if;
 if to_regclass('public.adaptive_plans') is null or to_regclass('public.adaptive_sections') is null then
  raise exception 'Reviewed adaptive migration005 is required';
 end if;
end $$;
grant select,insert,update,delete on public.adaptive_plans,public.adaptive_sections,public.adaptive_run_requests to planning_queue_worker;
grant select,update on public.adaptive_checkpoint_runtime to planning_queue_worker;
-- Trusted server-only queue role, never an authenticated/anon browser policy.
create policy adaptive_plans_worker on public.adaptive_plans for all to planning_queue_worker using(true) with check(true);
create policy adaptive_sections_worker on public.adaptive_sections for all to planning_queue_worker using(true) with check(true);
create policy adaptive_runs_worker on public.adaptive_run_requests for all to planning_queue_worker using(true) with check(true);
create policy adaptive_runtime_worker on public.adaptive_checkpoint_runtime for all to planning_queue_worker using(true) with check(true);
grant execute on function public.adaptive_create_plan(uuid,uuid,jsonb,text,bigint,integer) to planning_queue_worker;
grant execute on function public.adaptive_get_plan(uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_find_request(uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_get_section(uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_list_sections(uuid,uuid,integer,integer) to planning_queue_worker;
grant execute on function public.adaptive_recent_checkpoints(uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_next_section(uuid,uuid,uuid,integer) to planning_queue_worker;
grant execute on function public.adaptive_claim_section(uuid,uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_claim_next(uuid) to planning_queue_worker;
grant execute on function public.adaptive_transition_section(uuid,uuid,uuid,bigint,text,text,text,jsonb,jsonb) to planning_queue_worker;
grant execute on function public.adaptive_retry_section(uuid,uuid,uuid,integer) to planning_queue_worker;
grant execute on function public.adaptive_continue_run(uuid,uuid,uuid,integer) to planning_queue_worker;
grant execute on function public.adaptive_cancel_plan(uuid,uuid) to planning_queue_worker;
grant execute on function public.adaptive_checkpoint_health() to planning_queue_worker;
-- Cleanup belongs to the separately approved scheduler identity, not a new
-- arbitrary browser-triggerable endpoint; no purge EXECUTE grant added here.
commit;
