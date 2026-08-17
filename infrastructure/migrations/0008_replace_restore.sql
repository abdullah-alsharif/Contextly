-- Phase 12: deleting a replacement restores the superseded version even
-- after finalize (docs/ingestion.md §7): chunks intact -> previous status
-- restored; purged at finalize -> re-queued as 'uploaded' for the worker.
-- Restore only fires while no newer active version holds the filename (the
-- deleted row itself is excluded: within the delete statement its pre-delete
-- version is still visible to the trigger snapshot) and the superseded row
-- was not itself deleted. The soft-delete branch must run before the status
-- branches, or deleting a 'ready'/'failed' replacement would be swallowed.

drop function if exists restore_superseded(uuid, uuid);

create function restore_superseded(
    superseded_row uuid,
    exclude_row uuid
) returns void
language plpgsql
set search_path = public
as $$
begin
    update documents d
        set status = case
                when d.superseded_from = 'ready'
                 and not exists (
                     select 1 from document_chunks c where c.document_id = d.id
                 )
                then 'uploaded'  -- chunks purged at finalize: re-queue
                else d.superseded_from
            end,
            superseded_from = null,
            retry_count = 0,
            status_error = null,
            lease_until = null,
            updated_at = now()
        where d.id = superseded_row
          and d.deleted_at is null
          and d.status = 'superseded'
          and d.superseded_from is not null
          and not exists (
              select 1 from documents newer
              where newer.user_id = d.user_id
                and newer.filename = d.filename
                and newer.id <> d.id
                and newer.id <> exclude_row
                and newer.deleted_at is null
                and newer.status in ('uploaded', 'processing', 'ready', 'failed')
          );
end;
$$;

create or replace function documents_replace_resolution() returns trigger
language plpgsql
set search_path = public
as $$
begin
    if tg_op = 'UPDATE' and new.deleted_at is not null then
        perform restore_superseded(new.replaces_document_id, new.id);
    elsif tg_op = 'UPDATE' and new.status = 'ready' then
        if new.replaces_document_id is not null then
            -- finalize: old stays superseded (restore ticket kept), chunks purged
            update documents
                set status = 'superseded',
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
            -- the failed row leaves the active set first, then the old one is restored
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
    elsif tg_op = 'DELETE' and old.replaces_document_id is not null then
        perform restore_superseded(old.replaces_document_id, old.id);
    end if;
    return null;
end;
$$;
