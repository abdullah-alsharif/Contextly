-- Phase 14 (specs/016-user-action-logs, FR-001): emit a 'restored' action-log
-- event whenever a superseded document returns to the active set.
--
-- restore_superseded is redefined to record the event for the restored row
-- (the insert runs in the same transaction and under the caller's RLS claim —
-- the API's get_current_user session or the worker's _switch_to_owner session).
-- The failed-replacement branch of documents_replace_resolution is refactored
-- to go through restore_superseded so both restore paths share the semantics
-- and the event (and so a chunks-purged 'ready' restore re-queues as 'uploaded'
-- on the failure path too, matching the soft-delete path).

create or replace function restore_superseded(
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
    if found then
        insert into action_logs (user_id, action_type, document_id, filename)
        select d.user_id, 'restored', d.id, d.filename
        from documents d
        where d.id = superseded_row;
    end if;
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
            perform restore_superseded(new.replaces_document_id, new.id);
        end if;
    elsif tg_op = 'DELETE' and old.replaces_document_id is not null then
        perform restore_superseded(old.replaces_document_id, old.id);
    end if;
    return null;
end;
$$;
