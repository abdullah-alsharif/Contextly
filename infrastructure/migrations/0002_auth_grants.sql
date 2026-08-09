-- Phase 2: auth grants. No schema change — grants only.
-- Specs/003-jwt-authentication (data-model.md "Migration", research.md §5).
--
-- profiles.id references auth.users(id). In local dev the Phase 1 auth shim
-- (auth.users with a single `id` column) is empty, so profile provisioning must
-- insert the shim row first. On Supabase-hosted the real auth.users is managed by
-- Supabase Auth (user rows already exist) — the grant is skipped there to preserve
-- least privilege on the real auth schema.

do $$
begin
    if exists (
        -- The local shim has exactly one column (id); the real Supabase
        -- auth.users table has many more, so this stays true only in dev.
        select 1
        from information_schema.columns
        where table_schema = 'auth' and table_name = 'users'
        group by table_schema, table_name
        having count(*) = 1
    ) then
        grant usage on schema auth to contextly_app;
        grant insert, select on auth.users to contextly_app;
    end if;
end $$;
