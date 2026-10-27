-- Approved scope 2026-10-27: private planning job expiry, not existing saved trips.
-- Parent applies only AFTER additive queue migration and final review.
-- Verify no pre-existing job named purge-planning-jobs before running: pg_cron
-- schedule by existing name updates that job, so do not silently overwrite one.
begin;
create extension if not exists pg_cron;
select cron.schedule('purge-planning-jobs','* * * * *','select public.purge_expired_planning_jobs();');
commit;
