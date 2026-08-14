-- Pin + archive conversations (docs/chat.md §7, docs/database.md §2).

alter table conversations add column pinned      boolean     not null default false;
alter table conversations add column archived_at timestamptz;

-- Default list orders pinned first then updated_at desc, archived excluded.
create index conversations_user_pinned_updated_idx
    on conversations (user_id, pinned desc, updated_at desc)
    where deleted_at is null and archived_at is null;
