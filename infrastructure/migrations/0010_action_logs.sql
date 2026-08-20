-- User action logs (specs/016-user-action-logs, docs/database.md §2.5)
--
-- Write-once, read-only history of the user's document actions and pipeline
-- outcomes. RLS is the enforced tenant boundary: only a session carrying the
-- owner's claim can insert (API via get_current_user, worker via
-- _switch_to_owner) and only the owner can read (constitution III,
-- docs/multi-tenancy.md §2).

create table action_logs (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references profiles(id) on delete cascade,
    action_type   text not null check (action_type in (
                    'upload', 'replace', 'delete', 'cancel', 'reprocess',
                    'superseded', 'restored',
                    'processing_started', 'processing_succeeded',
                    'processing_failed')),
    document_id   uuid references documents(id) on delete set null,
    filename      text not null,               -- snapshot; survives doc deletion/replacement
    outcome       text not null default 'succeeded' check (outcome in ('succeeded', 'failed')),
    error_message text,                        -- failure reason (mirrors documents.status_error)
    error_trace   text,                        -- captured traceback, truncated server-side (≤ 8 KB)
    metadata      jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default clock_timestamp()  -- statement time: events in one
                                                                  -- transaction keep real order
);

create index action_logs_user_created_idx
    on action_logs (user_id, created_at desc);

alter table action_logs enable row level security;
alter table action_logs force row level security;

create policy action_logs_user_isolation on action_logs
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
