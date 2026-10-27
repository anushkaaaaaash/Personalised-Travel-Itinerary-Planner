-- REVIEW ONLY. Separate retention/scheduler approval required. Not auto-run.
-- Requires already-approved pg_cron; never installs extensions or changes roles.
begin;
do $$ declare existing record; begin
 if not exists(select 1 from pg_extension where extname='pg_cron') then
  raise exception 'Approved pg_cron setup is required';
 end if;
 if to_regprocedure('public.adaptive_purge_expired()') is null then
  raise exception 'Reviewed adaptive migration005 is required';
 end if;
 select * into existing from cron.job where jobname='adaptive-section-retention';
 if found then
  if existing.command<>'select public.adaptive_purge_expired();' or existing.schedule<>'* * * * *' or not existing.active then
   raise exception 'Conflicting adaptive cleanup schedule requires review';
  end if;
 else
  perform cron.schedule('adaptive-section-retention','* * * * *','select public.adaptive_purge_expired();');
 end if;
end $$;
-- Establish the heartbeat by executing only the approved expiry predicate.
select public.adaptive_purge_expired();
commit;
