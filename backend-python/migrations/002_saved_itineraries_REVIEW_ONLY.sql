-- REVIEW BEFORE APPLYING to another project. Not automatically executed.
-- Manually applied and verified in the configured QA project; see ../ACTIVITY_5_1.md.
-- Creates NEW storage; does not alter public.trips. Do not rerun if objects exist.
begin;
create table public.saved_itineraries (
  id uuid primary key,
  user_id uuid not null references auth.users(id),
  title text not null check (char_length(btrim(title)) between 1 and 120),
  preferences jsonb not null check (jsonb_typeof(preferences) = 'object'),
  itinerary jsonb not null check (jsonb_typeof(itinerary) = 'object'),
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint saved_itinerary_size check
    (octet_length(preferences::text) + octet_length(itinerary::text) <= 131072)
);
create index saved_itineraries_owner_updated on public.saved_itineraries(user_id, updated_at desc, id);
alter table public.saved_itineraries enable row level security;
alter table public.saved_itineraries force row level security;
revoke all on public.saved_itineraries from anon, authenticated;
grant select, insert, update, delete on public.saved_itineraries to authenticated;
grant all on public.saved_itineraries to service_role;
create policy saved_itineraries_select on public.saved_itineraries for select to authenticated
  using ((select auth.uid()) = user_id);
create policy saved_itineraries_insert on public.saved_itineraries for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy saved_itineraries_update on public.saved_itineraries for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy saved_itineraries_delete on public.saved_itineraries for delete to authenticated
  using ((select auth.uid()) = user_id);
create function public.guard_saved_itinerary_version() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    if new.version <> 1 then raise exception 'Invalid initial version'; end if;
    new.created_at := now();
  else
    if new.id <> old.id or new.user_id <> old.user_id or new.created_at <> old.created_at
      or new.version <> old.version + 1 then
      raise exception 'Invalid saved itinerary revision';
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;
revoke all on function public.guard_saved_itinerary_version() from public;
create trigger saved_itineraries_version before insert or update on public.saved_itineraries
  for each row execute function public.guard_saved_itinerary_version();
commit;
