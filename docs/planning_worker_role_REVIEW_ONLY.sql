-- Separate approved scoped worker role; starts NOLOGIN until secret provisioning. NO PASSWORD/secret appears in this file.
-- Apply only after queue migration, privilege audit and final review. Do not run
-- if this role already exists: inspect its ownership/membership/privileges first.
begin;
create role planning_queue_worker nologin nosuperuser nocreatedb nocreaterole
  noinherit noreplication nobypassrls connection limit 4 password null;
do $$ begin
  execute format('grant connect on database %I to planning_queue_worker',current_database());
end $$;
grant usage on schema public to planning_queue_worker;
grant select,insert,update,delete on public.planning_jobs to planning_queue_worker;
grant select,update on public.planning_job_runtime to planning_queue_worker;
create policy planning_worker_queue_access on public.planning_jobs
  for all to planning_queue_worker using(true) with check(true);
create policy planning_worker_runtime_read on public.planning_job_runtime
  for select to planning_queue_worker using(true);
create policy planning_worker_runtime_update on public.planning_job_runtime
  for update to planning_queue_worker using(true) with check(singleton=true);
grant execute on function public.enqueue_planning_job(jsonb) to planning_queue_worker;
grant execute on function public.claim_planning_job(uuid) to planning_queue_worker;
grant execute on function public.transition_planning_job(uuid,uuid,integer,text,text,jsonb,text,jsonb) to planning_queue_worker;
grant execute on function public.cancel_planning_job(uuid,uuid) to planning_queue_worker;
grant execute on function public.planning_queue_health() to planning_queue_worker;
grant execute on function public.purge_expired_planning_jobs() to planning_queue_worker;
commit;
-- Parent enables LOGIN and provisions a generated password separately through approved secret
-- control, never through this file, source history, logs or chat output.
