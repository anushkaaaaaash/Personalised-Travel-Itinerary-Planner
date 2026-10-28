-- PROPOSAL ONLY. Explicit schema approval and local tests required before applying.
-- Never expose adaptive_archive in PostgREST's exposed schemas. User JWT required.
-- Dedicated NOLOGIN/NOBYPASSRLS function owner cannot bypass FORCE RLS.
-- Completed archives have no working-plan TTL or FK. Staging expires after24h.
begin;
create role adaptive_archive_rpc nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
create schema adaptive_archive;
revoke all on schema adaptive_archive from public,anon,authenticated;
grant usage on schema adaptive_archive,auth,public to adaptive_archive_rpc;
grant execute on function auth.uid() to adaptive_archive_rpc;
create table adaptive_archive.manifests (
 id uuid primary key default gen_random_uuid(), owner uuid not null references auth.users(id) on delete cascade,
 request_id uuid not null,title text not null check(length(btrim(title)) between 1 and 120 and title !~ '[[:cntrl:]]'),
 manifest jsonb not null,manifest_hash text not null check(manifest_hash ~ '^[a-f0-9]{64}$'),
 status text not null default 'staging' check(status in ('staging','complete')),version integer not null default 1 check(version=1),
 reserved_bytes bigint not null check(reserved_bytes between 1 and 16777216),created_at timestamptz not null default now(),completed_at timestamptz,
 staging_expires_at timestamptz not null default now()+interval '24 hours',unique(owner,request_id),unique(owner,id)
);
create table adaptive_archive.sections (
 owner uuid not null,archive_id uuid not null,sequence integer not null check(sequence between 1 and 1024),
 data jsonb not null,hash text not null check(hash ~ '^[a-f0-9]{64}$'),bytes integer not null check(bytes between 1 and 262144),
 primary key(owner,archive_id,sequence),foreign key(owner,archive_id) references adaptive_archive.manifests(owner,id) on delete cascade
);
create table adaptive_archive.sources (
 owner uuid not null,archive_id uuid not null,hash text not null check(hash ~ '^[a-f0-9]{64}$'),data jsonb not null,
 bytes integer not null check(bytes between 1 and 131072),primary key(owner,archive_id,hash),
 foreign key(owner,archive_id) references adaptive_archive.manifests(owner,id) on delete cascade
);
create index archive_owner_created on adaptive_archive.manifests(owner,created_at desc,id);
alter table adaptive_archive.manifests enable row level security;
alter table adaptive_archive.manifests force row level security;
alter table adaptive_archive.sections enable row level security;
alter table adaptive_archive.sections force row level security;
alter table adaptive_archive.sources enable row level security;
alter table adaptive_archive.sources force row level security;
create policy owned_manifest on adaptive_archive.manifests to adaptive_archive_rpc using(owner=(select auth.uid())) with check(owner=(select auth.uid()));
create policy owned_sections on adaptive_archive.sections to adaptive_archive_rpc using(owner=(select auth.uid())) with check(owner=(select auth.uid()));
create policy owned_sources on adaptive_archive.sources to adaptive_archive_rpc using(owner=(select auth.uid())) with check(owner=(select auth.uid()));
revoke all on all tables in schema adaptive_archive from public,anon,authenticated;
grant select,insert,update,delete on adaptive_archive.manifests to adaptive_archive_rpc;
grant select,insert,delete on adaptive_archive.sections,adaptive_archive.sources to adaptive_archive_rpc;
create function adaptive_archive.exact_keys(value jsonb,keys text[]) returns boolean
language sql immutable security invoker set search_path='' as $$
 select case when jsonb_typeof(value)='object' then
 not exists(select 1 from jsonb_each(value) e where e.value='null'::jsonb) and
 (select array_agg(k order by k) from jsonb_object_keys(value) k)=(select array_agg(k order by k) from unnest(keys) k) else false end
$$;
create function adaptive_archive.prefix(m adaptive_archive.manifests) returns jsonb
language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('id',m.id,'owner',m.owner,'requestId',m.request_id,'title',m.title,'version',m.version,'manifest',m.manifest,
 'createdAt',m.created_at,'updatedAt',coalesce(m.completed_at,m.created_at),'stagingExpiresAt',m.staging_expires_at,
 'status',case when m.status='staging' and (m.staging_expires_at<=now() or (m.manifest->>'sourceExpiresAt')::timestamptz<=now()) then 'expired' else m.status end,
 'savedSections',count(s.sequence),'lastSourceSequence',coalesce(max((s.data->>'sourceSequence')::integer),0),
 'coveredDays',coalesce(sum(jsonb_array_length(s.data->'checkpoint'->'itinerary'->'days')),0),
 'spentCents',coalesce(sum((s.data->'checkpoint'->>'spentCents')::bigint),0),
 'endLocation',coalesce((select z.data->'checkpoint'->>'endLocation' from adaptive_archive.sections z where z.owner=m.owner and z.archive_id=m.id order by z.sequence desc limit 1),m.manifest->'preferences'->>'departureCity'))
 from adaptive_archive.sections s where s.owner=m.owner and s.archive_id=m.id
$$;
create function adaptive_archive.guard_complete() returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if tg_table_name='manifests' then
  if old.status='complete' or new.id<>old.id or new.owner<>old.owner or new.request_id<>old.request_id or new.manifest<>old.manifest or new.manifest_hash<>old.manifest_hash or new.title<>old.title or new.reserved_bytes<>old.reserved_bytes or new.created_at<>old.created_at or new.staging_expires_at<>old.staging_expires_at then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
 elsif tg_op='DELETE' then
  if exists(select 1 from adaptive_archive.manifests m where m.owner=old.owner and m.id=old.archive_id and m.status='complete') then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
  return old;
 else
  if exists(select 1 from adaptive_archive.manifests m where m.owner=new.owner and m.id=new.archive_id and m.status='complete') then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
 end if;
 return new;
end $$;
create trigger immutable_manifest before update on adaptive_archive.manifests for each row execute function adaptive_archive.guard_complete();
create trigger immutable_section before insert on adaptive_archive.sections for each row execute function adaptive_archive.guard_complete();
create trigger immutable_section_delete before delete on adaptive_archive.sections for each row execute function adaptive_archive.guard_complete();
create trigger immutable_source_delete before delete on adaptive_archive.sources for each row execute function adaptive_archive.guard_complete();
create trigger immutable_source before insert on adaptive_archive.sources for each row execute function adaptive_archive.guard_complete();
create function public.adaptive_saved_archive(operation text,payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 u uuid:=auth.uid();m adaptive_archive.manifests;value jsonb;item jsonb;olddata jsonb;
 canonical text;hash text;manifest jsonb;n integer;cursor integer;offset_n integer;
 used bigint;bytes_n bigint;count_n integer;expected_date date;next_date date;
 rolling bytea:=''::bytea;section_row record;items jsonb;source_items jsonb;prefix jsonb;request uuid;saved uuid;
begin
 if u is null then raise exception 'SAVED_ADAPTIVE_FORBIDDEN'; end if;
 if operation not in ('begin','lookup','get','list','append_sections','append_sources','finalize','delete','cleanup') then raise exception 'SAVED_ADAPTIVE_INVALID_OPERATION'; end if;
 if jsonb_typeof(payload)<>'object' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
 perform pg_advisory_xact_lock(hashtextextended(u::text,73941));
 if operation='begin' then
  if not adaptive_archive.exact_keys(payload,array['requestId','title','canonical','hash','sourceCanonical']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  request:=(payload->>'requestId')::uuid;canonical:=payload->>'canonical';hash:=payload->>'hash';
  if octet_length(canonical)>32768 or encode(sha256(convert_to(canonical,'UTF8')),'hex')<>hash then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  manifest:=canonical::jsonb;
  if octet_length(payload->>'sourceCanonical')>32768 or (payload->>'sourceCanonical')::jsonb<>manifest-'sourceDigest' or encode(sha256(convert_to(payload->>'sourceCanonical','UTF8')),'hex')<>manifest->>'sourceDigest' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  if not adaptive_archive.exact_keys(manifest,array['format','sourcePlanId','sourceVersion','sourceExpiresAt','preferences','journeyStrategy','totalDays','sectionCount','sourceCount','spentCents','totalBudgetCents','currency','contentBytes','sectionsDigest','sourceDigest']) or manifest->>'format'<>'adaptive-sections-v1' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  select * into m from adaptive_archive.manifests where owner=u and request_id=request for update;
  if found then
   if m.manifest_hash<>hash or m.title<>payload->>'title' then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
   return adaptive_archive.prefix(m);
  end if;
  if (manifest->>'sourceExpiresAt')::timestamptz<=now() then raise exception 'SAVED_ADAPTIVE_SOURCE_EXPIRED'; end if;
  if manifest->>'sectionsDigest' !~ '^[a-f0-9]{64}$' or manifest->>'sourceDigest' !~ '^[a-f0-9]{64}$' or
   manifest->>'sectionCount' !~ '^[0-9]+$' or (manifest->>'sectionCount')::integer not between 1 and 1024 or
   manifest->>'sourceCount' !~ '^[0-9]+$' or (manifest->>'sourceCount')::integer not between 0 and 1024 or
   manifest->>'totalDays' !~ '^[0-9]+$' or (manifest->>'totalDays')::integer<1 or
   manifest->>'spentCents' !~ '^[0-9]+$' or manifest->>'totalBudgetCents' !~ '^[0-9]+$' or
   (manifest->>'spentCents')::bigint>(manifest->>'totalBudgetCents')::bigint or manifest->>'contentBytes' !~ '^[0-9]+$' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  perform (manifest->>'sourcePlanId')::uuid;
  bytes_n:=(manifest->>'contentBytes')::bigint+octet_length(canonical);
  if bytes_n not between 1 and 16777216 then raise exception 'SAVED_ADAPTIVE_TOO_LARGE'; end if;
  select coalesce(sum(reserved_bytes),0) into used from adaptive_archive.manifests where owner=u;
  if used+bytes_n>67108864 then raise exception 'SAVED_ADAPTIVE_QUOTA_EXCEEDED'; end if;
  insert into adaptive_archive.manifests(owner,request_id,title,manifest,manifest_hash,reserved_bytes) values(u,request,payload->>'title',manifest,hash,bytes_n) returning * into m;
  return adaptive_archive.prefix(m);
 elsif operation='lookup' then
  if not adaptive_archive.exact_keys(payload,array['requestId']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  select * into m from adaptive_archive.manifests where owner=u and request_id=(payload->>'requestId')::uuid;
  if not found then return 'null'::jsonb; end if;
  return adaptive_archive.prefix(m);
 elsif operation='list' then
  if not adaptive_archive.exact_keys(payload,array['offset']) or payload->>'offset' !~ '^[0-9]+$' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  offset_n:=(payload->>'offset')::integer;
  if offset_n>10000 then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  select coalesce(jsonb_agg(x.data),'[]') into items from (select adaptive_archive.prefix(manifests) data from adaptive_archive.manifests where owner=u and status='complete' order by created_at desc,id desc limit 21 offset offset_n) x;
  return jsonb_build_object('items',case when jsonb_array_length(items)>20 then items-20 else items end,'hasMore',jsonb_array_length(items)>20,'offset',offset_n);
 elsif operation='cleanup' then
  if payload<>'{}'::jsonb then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  delete from adaptive_archive.manifests where owner=u and id in (select expired.id from adaptive_archive.manifests expired where expired.owner=u and expired.status='staging' and (expired.staging_expires_at<=now() or (expired.manifest->>'sourceExpiresAt')::timestamptz<=now()) order by expired.created_at,expired.id limit 100);
  get diagnostics count_n=row_count;return jsonb_build_object('removed',count_n);
 end if;
 saved:=(payload->>'id')::uuid;
 select * into m from adaptive_archive.manifests where owner=u and id=saved for update;
 if not found then raise exception 'SAVED_ADAPTIVE_NOT_FOUND'; end if;
 if operation='get' then
  if not adaptive_archive.exact_keys(payload,array['id','afterSequence']) or payload->>'afterSequence' !~ '^[0-9]+$' or m.status<>'complete' then raise exception 'SAVED_ADAPTIVE_NOT_FOUND'; end if;
  cursor:=(payload->>'afterSequence')::integer;
  select coalesce(jsonb_agg(x.data order by x.sequence),'[]') into items from (select data||jsonb_build_object('hash',sections.hash) data,sequence from adaptive_archive.sections where owner=u and archive_id=saved and sequence>cursor order by sequence limit 3) x;
  select coalesce(jsonb_agg(jsonb_build_object('hash',s.hash,'data',s.data)),'[]') into source_items from adaptive_archive.sources s where s.owner=u and s.archive_id=saved and s.hash in (select jsonb_array_elements_text(x->'sourceHashes') from jsonb_array_elements(items) x);
  n:=case when jsonb_array_length(items)>0 then (items->(jsonb_array_length(items)-1)->>'sequence')::integer else cursor end;
  return adaptive_archive.prefix(m)||jsonb_build_object('format','adaptive-sections-v1','persisted',true,'sections',items,'sources',source_items,'nextCursor',case when n<(m.manifest->>'sectionCount')::integer then n else null end);
 elsif operation='delete' then
  if not adaptive_archive.exact_keys(payload,array['id','version']) or payload->>'version'<>'1' then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
  delete from adaptive_archive.manifests where owner=u and id=saved;
  return jsonb_build_object('id',saved,'owner',u,'version',1,'deleted',true);
 end if;
 if operation='finalize' and m.status='complete' then
  if not adaptive_archive.exact_keys(payload,array['id']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  return adaptive_archive.prefix(m);
 end if;
 if m.status<>'staging' then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
 if m.staging_expires_at<=now() or (m.manifest->>'sourceExpiresAt')::timestamptz<=now() then raise exception 'SAVED_ADAPTIVE_SOURCE_EXPIRED'; end if;
 if operation in ('append_sections','append_sources') then
  if not adaptive_archive.exact_keys(payload,array['id','items']) or jsonb_typeof(payload->'items')<>'array' or jsonb_array_length(payload->'items') not between 1 and 3 then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  for item in select * from jsonb_array_elements(payload->'items') loop
   if not adaptive_archive.exact_keys(item,array['canonical','hash']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
   canonical:=item->>'canonical';hash:=item->>'hash';bytes_n:=octet_length(canonical);
   if bytes_n>262144 or hash !~ '^[a-f0-9]{64}$' or encode(sha256(convert_to(canonical,'UTF8')),'hex')<>hash then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
   value:=canonical::jsonb;
   if operation='append_sources' then
    if not adaptive_archive.exact_keys(value,array['receivedAt','expiresAt','text','sources','citations','applicability','evidenceStatus']) or
     value->>'applicability' is distinct from 'unknown' or value->>'evidenceStatus' is distinct from 'historical_unverified' or
     jsonb_typeof(value->'text') is distinct from 'string' or jsonb_typeof(value->'receivedAt') is distinct from 'string' or jsonb_typeof(value->'expiresAt') is distinct from 'string' or
     jsonb_typeof(value->'sources') is distinct from 'array' or jsonb_typeof(value->'citations') is distinct from 'array' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
    if bytes_n>131072 then raise exception 'SAVED_ADAPTIVE_TOO_LARGE'; end if;
    select data into olddata from adaptive_archive.sources where owner=u and archive_id=saved and sources.hash=item->>'hash';
    if found then
     if olddata<>value then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
    else insert into adaptive_archive.sources values(u,saved,hash,value,bytes_n);end if;
   else
    if not adaptive_archive.exact_keys(value,array['sequence','sourceSequence','startDate','endDate','checkpoint','sourceHashes','sourceAssociation']) or value->>'sequence' !~ '^[0-9]+$' or value->>'sourceSequence' !~ '^[0-9]+$' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
    n:=(value->>'sequence')::integer;
    select data into olddata from adaptive_archive.sections where owner=u and archive_id=saved and sequence=n;
    if found then
     if olddata<>value then raise exception 'SAVED_ADAPTIVE_CONFLICT'; end if;
    else
     prefix:=adaptive_archive.prefix(m);
     if n<>(prefix->>'savedSections')::integer+1 or n>(m.manifest->>'sectionCount')::integer or (value->>'sourceSequence')::integer<=(prefix->>'lastSourceSequence')::integer or jsonb_typeof(value->'sourceHashes')<>'array' or jsonb_array_length(value->'sourceHashes')>1 or value->>'sourceAssociation' not in ('none_recorded','linked_historical') or (value->>'sourceAssociation'='linked_historical')<>(jsonb_array_length(value->'sourceHashes')=1) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
     if exists(select 1 from jsonb_array_elements_text(value->'sourceHashes') h where not exists(select 1 from adaptive_archive.sources s where s.owner=u and s.archive_id=saved and s.hash=h)) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
     if not adaptive_archive.exact_keys(value->'checkpoint',array['itinerary','startLocation','endLocation','spentCents','provenance','journeyStrategy']) or
      jsonb_typeof(value->'checkpoint'->'itinerary') is distinct from 'object' or jsonb_typeof(value->'checkpoint'->'itinerary'->'days') is distinct from 'array' or
      jsonb_typeof(value->'checkpoint'->'itinerary'->'currency') is distinct from 'string' or jsonb_typeof(value->'checkpoint'->'startLocation') is distinct from 'string' or
      jsonb_typeof(value->'checkpoint'->'endLocation') is distinct from 'string' or length(value->'checkpoint'->>'startLocation') not between 1 and 200 or
      length(value->'checkpoint'->>'endLocation') not between 1 and 200 or jsonb_typeof(value->'checkpoint'->'spentCents') is distinct from 'number' or
      not adaptive_archive.exact_keys(value->'checkpoint'->'provenance',array['provider','model','validationVersion']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
     if value->'checkpoint'->'journeyStrategy' is distinct from m.manifest->'journeyStrategy' or value->'checkpoint'->'itinerary'->>'currency' is distinct from m.manifest->>'currency' or value->'checkpoint'->>'startLocation' is distinct from prefix->>'endLocation' or value->'checkpoint'->>'spentCents' !~ '^[0-9]+$' or jsonb_array_length(value->'checkpoint'->'itinerary'->'days') not between 1 and 3 then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
     expected_date:=(m.manifest->'preferences'->>'startDate')::date+(prefix->>'coveredDays')::integer;next_date:=expected_date;
     for olddata in select * from jsonb_array_elements(value->'checkpoint'->'itinerary'->'days') loop
      if jsonb_typeof(olddata) is distinct from 'object' or olddata->>'date' is distinct from next_date::text then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT';end if;next_date:=next_date+1;
     end loop;
     if value->>'startDate'<>expected_date::text or value->>'endDate'<>(next_date-1)::text then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
     insert into adaptive_archive.sections values(u,saved,n,value,hash,bytes_n);
    end if;
   end if;
  end loop;
  select coalesce((select sum(bytes) from adaptive_archive.sections where owner=u and archive_id=saved),0)+coalesce((select sum(bytes) from adaptive_archive.sources where owner=u and archive_id=saved),0) into used;
  if used>(m.manifest->>'contentBytes')::bigint or (select count(*) from adaptive_archive.sources where owner=u and archive_id=saved)>(m.manifest->>'sourceCount')::integer then raise exception 'SAVED_ADAPTIVE_TOO_LARGE'; end if;
  return adaptive_archive.prefix(m);
 elsif operation='finalize' then
  if not adaptive_archive.exact_keys(payload,array['id']) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  prefix:=adaptive_archive.prefix(m);
  if exists(select 1 from adaptive_archive.sources src where src.owner=u and src.archive_id=saved and not exists(select 1 from adaptive_archive.sections sec where sec.owner=u and sec.archive_id=saved and sec.data->'sourceHashes' ? src.hash)) then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  select coalesce((select sum(bytes) from adaptive_archive.sections where owner=u and archive_id=saved),0)+coalesce((select sum(bytes) from adaptive_archive.sources where owner=u and archive_id=saved),0) into used;
  for section_row in select s.hash from adaptive_archive.sections s where owner=u and archive_id=saved order by sequence loop rolling:=rolling||decode(section_row.hash,'hex');end loop;
  if prefix->>'savedSections'<>m.manifest->>'sectionCount' or prefix->>'coveredDays'<>m.manifest->>'totalDays' or prefix->>'spentCents'<>m.manifest->>'spentCents' or prefix->>'endLocation'<>m.manifest->'preferences'->>'departureCity' or (m.manifest->'preferences'->>'startDate')::date+(prefix->>'coveredDays')::integer-1<>(m.manifest->'preferences'->>'endDate')::date or used<>(m.manifest->>'contentBytes')::bigint or (select count(*) from adaptive_archive.sources where owner=u and archive_id=saved)<>(m.manifest->>'sourceCount')::integer or encode(sha256(rolling),'hex')<>m.manifest->>'sectionsDigest' then raise exception 'SAVED_ADAPTIVE_INVALID_SNAPSHOT'; end if;
  update adaptive_archive.manifests set status='complete',completed_at=now() where owner=u and id=saved returning * into m;
  return adaptive_archive.prefix(m);
 end if;
 raise exception 'SAVED_ADAPTIVE_INVALID_OPERATION';
end $$;
revoke all on all functions in schema adaptive_archive from public,anon,authenticated;
grant execute on all functions in schema adaptive_archive to adaptive_archive_rpc;
alter function public.adaptive_saved_archive(text,jsonb) owner to adaptive_archive_rpc;
revoke all on function public.adaptive_saved_archive(text,jsonb) from public,anon;
grant execute on function public.adaptive_saved_archive(text,jsonb) to authenticated;
commit;
