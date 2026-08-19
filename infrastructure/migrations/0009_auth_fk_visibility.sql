-- Phase 11 verification (Supabase-hosted): profiles.id references auth.users(id),
-- and the FK check runs as the inserting role — contextly_app therefore needs
-- SELECT on auth.users. The auth schema is locked on Supabase (owned by
-- supabase_auth_admin) but the postgres role may grant on it; local dev's shim
-- grants (0002) are a subset of these, so the file is idempotent everywhere.
grant usage on schema auth to contextly_app;
grant select on auth.users to contextly_app;