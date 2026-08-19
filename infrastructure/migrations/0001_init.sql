-- Phase 1: full application schema per docs/database.md §2, RLS per
-- docs/multi-tenancy.md §2, runtime role per contracts/database.md §3.
-- Applies cleanly on self-hosted Postgres AND Supabase-hosted (Phase 11):
-- the auth shim uses IF NOT EXISTS / CREATE OR REPLACE so the real Supabase
-- auth schema is never touched.

-- 1. pgvector extension (safe to create repeatedly; idempotent)
create extension if not exists vector;

-- 2. Local auth shim. Local dev runs plain pgvector/pgvector:pg16 with no
--    Supabase auth schema, yet profiles references auth.users(id) and the RLS
--    policies call auth.uid(). The shim mirrors Supabase's current cloud
--    implementation (coalesce over request.jwt.claim.sub and the Postgres 14+
--    fallback request.jwt.claims) so the same SQL works everywhere.
--    On Supabase the real auth schema already exists and is owned by
--    supabase_auth_admin — creating tables there is forbidden even for the
--    postgres role — so the shim is skipped when the schema is present.
do $shim$
begin
    if not exists (select 1 from pg_catalog.pg_namespace where nspname = 'auth') then
        create schema auth;

        create table auth.users (
            id uuid primary key
        );

        create or replace function auth.uid() returns uuid
            language sql
            stable
        as $func$
            select coalesce(
                nullif(current_setting('request.jwt.claim.sub', true), ''),
                (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
            )::uuid
        $func$;
    end if;
end $shim$;

-- 3. Document status enum
create type document_status as enum ('uploaded', 'processing', 'ready', 'failed', 'deleted');

-- 4. Tables (docs/database.md §2, DDL authoritative)

-- 1:1 with auth.users (Supabase) or app users
create table profiles (
    id         uuid primary key references auth.users(id) on delete cascade,
    email      text not null,
    full_name  text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table documents (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references profiles(id) on delete cascade,
    filename        text not null,
    storage_path    text not null,          -- e.g. {user_id}/docs/{document_id}.pdf
    file_size_bytes bigint not null check (file_size_bytes > 0),
    mime_type       text not null default 'application/pdf',
    status          document_status not null default 'uploaded',
    status_error    text,                   -- last failure reason (for status='failed')
    total_chunks    int,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    deleted_at      timestamptz             -- soft delete
);

create table document_chunks (
    id          uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    chunk_index int  not null,
    content     text not null,
    page_number int,                          -- null if parser can't detect pages
    token_count int,
    embedding   vector(1024),                 -- MUST match embedding model dims (nvidia/bge-m3)
    metadata    jsonb not null default '{}'::jsonb,
    unique (document_id, chunk_index)
);

create table conversations (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references profiles(id) on delete cascade,
    title      text not null default 'New conversation',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

-- A conversation only queries chunks of these documents.
create table conversation_documents (
    conversation_id uuid not null references conversations(id) on delete cascade,
    document_id     uuid not null references documents(id) on delete cascade,
    added_at        timestamptz not null default now(),
    primary key (conversation_id, document_id)
);

create table messages (
    id              uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    role            text not null check (role in ('user', 'assistant')),
    content         text not null,
    sources         jsonb,        -- assistant only; see docs/database.md §5
    input_tokens    int,
    output_tokens   int,
    retrieval_ms    int,
    llm_ms          int,
    created_at      timestamptz not null default now()
);

-- 5. Indexes (docs/database.md §2; all FK columns indexed per best practice)

create index documents_user_idx on documents (user_id);
create index documents_user_status_idx on documents (user_id, status) where deleted_at is null;

-- HNSW index (m=16, ef_construction=64, L2) — builds fine on the empty table.
create index chunks_embedding_hnsw
    on document_chunks using hnsw (embedding vector_l2_ops)
    with (m = 16, ef_construction = 64);

create index chunks_document_idx on document_chunks (document_id);
create index conversations_user_updated_idx on conversations (user_id, updated_at desc) where deleted_at is null;
create index conversation_documents_document_idx on conversation_documents (document_id);
create index messages_conversation_created_idx on messages (conversation_id, created_at);

-- 6. Row Level Security (docs/multi-tenancy.md §2, verbatim policy set)
--    FORCE RLS so even the table owner (non-superuser) is subject to policies.

alter table documents enable row level security;
alter table conversations enable row level security;
alter table conversation_documents enable row level security;
alter table messages enable row level security;
alter table document_chunks enable row level security;
alter table profiles enable row level security;

alter table documents force row level security;
alter table conversations force row level security;
alter table conversation_documents force row level security;
alter table messages force row level security;
alter table document_chunks force row level security;
alter table profiles force row level security;

create policy documents_user_isolation on documents
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy conversations_user_isolation on conversations
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy conv_docs_user_isolation on conversation_documents
  using (conversation_id in (
    select id from conversations where user_id = auth.uid()
  ))
  with check (conversation_id in (
    select id from conversations where user_id = auth.uid()
  ));

create policy messages_user_isolation on messages
  using (conversation_id in (
    select id from conversations where user_id = auth.uid()
  ));

-- chunks inherit their document's tenant through a subquery
create policy chunks_user_isolation on document_chunks
  using (document_id in (
    select id from documents where user_id = auth.uid()
  ));

-- profiles: a user may read/write only their own profile row
create policy profiles_user_isolation on profiles
  using (id = auth.uid())
  with check (id = auth.uid());

-- 7. Runtime role (docs/multi-tenancy.md §2: non-superuser, no RLS bypass).
--    The migrations runner and health probe keep the admin connection; the app
--    runtime queries use this role so RLS actually enforces tenant isolation.

create role contextly_app with login nosuperuser nocreatedb nocreaterole nobypassrls;

do $$
begin
    execute format('grant connect on database %I to contextly_app', current_database());
end $$;

grant usage on schema public to contextly_app;
grant select, insert, update, delete on all tables in schema public to contextly_app;
alter default privileges in schema public grant select, insert, update, delete on tables to contextly_app;

-- Least privilege: no PUBLIC schema-write access (Supabase-compatible hardening).
revoke create on schema public from public;
