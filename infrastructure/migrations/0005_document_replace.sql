-- Phase 12: replace-on-duplicate uploads (docs/ingestion.md §5, §7).
--
-- Re-uploading an existing filename with replace=true marks the previous
-- document 'superseded': its row stays in the docs table ("Outdated") but is
-- excluded from retrieval/context/worker claims while the name becomes free.
--
--   * documents_active_filename_idx — at most one active row per
--     (user_id, filename): the API's duplicate check (409) is enforced against
--     parallel-upload races. Deleted and superseded rows don't count as
--     active, so a name is reusable once its holder is replaced or removed.
--   * superseded_from — pre-replace status of the old row; replaces_document_id
--     links a replacement back to the row it superseded.
--   * documents_replace_resolution trigger — resolves the outcome atomically
--     with the worker's finalize/fail transaction or the API's delete:
--       replacement 'ready'  -> old finalized as 'superseded' (chunks purged)
--       replacement 'failed' -> failed row leaves the active set first (its
--         status becomes 'superseded', superseded_from 'failed'), then the old
--         version is restored to superseded_from with its chunks intact
--       replacement deleted (soft or hard) before resolving -> old restored
--     The function body is idempotent against its own re-fires (deactivation
--     and restore updates hit no branch), so it cannot recurse.
--
-- A value added to an enum becomes usable only after the transaction commits
-- (Postgres rule), so the index predicate below names the pre-existing
-- statuses instead of comparing against 'superseded'.
alter type document_status add value 'superseded';

create unique index documents_active_filename_idx
    on documents (user_id, filename)
    where deleted_at is null and status in ('uploaded', 'processing', 'ready', 'failed');

alter table documents
    add column superseded_from document_status,
    add column replaces_document_id uuid references documents(id);

create index documents_replaces_idx on documents (replaces_document_id);

create function documents_replace_resolution() returns trigger
language plpgsql
set search_path = public
as $$
begin
    if tg_op = 'UPDATE' and new.status = 'ready' then
        if new.replaces_document_id is not null then
            -- finalize: old stays 'superseded' forever, chunks purged
            update documents
                set status = 'superseded',
                    superseded_from = null,
                    total_chunks = null,
                    lease_until = null,
                    updated_at = now()
                where id = new.replaces_document_id
                  and deleted_at is null
                  and superseded_from is not null;
            delete from document_chunks
                where document_id = new.replaces_document_id;
        end if;
    elsif tg_op = 'UPDATE' and new.status = 'failed' then
        if new.replaces_document_id is not null then
            -- the failed replacement leaves the active set first (the active
            -- filename index allows one active row per name), then the old
            -- version is restored with its status and chunks intact
            update documents
                set status = 'superseded',
                    superseded_from = 'failed',
                    updated_at = now()
                where id = new.id
                  and deleted_at is null
                  and status = 'failed';
            delete from document_chunks
                where document_id = new.id;
            update documents
                set status = superseded_from,
                    superseded_from = null,
                    updated_at = now()
                where id = new.replaces_document_id
                  and deleted_at is null
                  and status = 'superseded'
                  and superseded_from is not null;
        end if;
    elsif tg_op = 'UPDATE' and new.deleted_at is not null then
        -- soft delete of an unresolved replacement undoes the replace
        update documents
            set status = superseded_from,
                superseded_from = null,
                updated_at = now()
            where id = new.replaces_document_id
              and deleted_at is null
              and status = 'superseded'
              and superseded_from is not null;
    elsif tg_op = 'DELETE' and old.replaces_document_id is not null then
        -- hard delete of an unresolved replacement undoes the replace
        update documents
            set status = superseded_from,
                superseded_from = null,
                updated_at = now()
            where id = old.replaces_document_id
              and deleted_at is null
              and status = 'superseded'
              and superseded_from is not null;
    end if;
    return null;
end;
$$;

create trigger documents_replace_resolution_trigger
    after update or delete on documents
    for each row execute function documents_replace_resolution();