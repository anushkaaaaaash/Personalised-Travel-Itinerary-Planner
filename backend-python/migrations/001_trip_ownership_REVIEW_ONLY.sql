-- REVIEW ONLY. NOT APPLIED. Requires explicit user approval, backup, and operator review.
-- Existing public.trips rows stay unowned (NULL) and invisible to ordinary users.
-- NEVER assign legacy rows to the next/newly registered user automatically.
-- Review actual schema, existing grants/policies/triggers/views before executing.
-- This script deliberately fails/rolls back if its named policies already exist.
BEGIN;
ALTER TABLE public.trips
    ADD COLUMN user_id uuid NULL REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX trips_user_id_idx ON public.trips(user_id);
ALTER TABLE public.trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trips FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.trips FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.trips TO authenticated;
-- Restrictive guard prevents an existing permissive policy exposing other owners.
CREATE POLICY trips_owner_guard ON public.trips AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));
CREATE POLICY trips_owner_access ON public.trips AS PERMISSIVE
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));
COMMIT;
-- If trips.id uses a sequence, review/grant only the needed sequence USAGE separately.
-- Service-role and database owners can bypass RLS; application owned mode MUST NOT use them.
-- Approved legacy reassignment must be a separate audited explicit row-ID -> user-ID operation.
-- Before setting TRIP_OWNERSHIP_SCHEMA_VERIFIED=true, verify two distinct test users:
-- A cannot read/update/delete B's row, cannot insert with B's user_id, cannot see NULL rows;
-- anon cannot access rows; authenticated new writes/read/history work as their owner.
-- No live DDL, real accounts, or public deployment is authorized by this file.
