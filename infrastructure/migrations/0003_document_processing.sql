-- Phase 4: document processing worker. Lease/retry columns on documents and the
-- single-winner claim function per docs/ingestion.md §3, docs/multi-tenancy.md §2/§3,
-- specs/005-document-processing-pipeline (contracts/worker.md §2, data-model.md).
--
-- worker_claim_next is the ONLY RLS-bypassing surface: SECURITY DEFINER, owned by
-- the migration (superuser) role, `set search_path = public`, and EXECUTE granted
-- to the NOBYPASSRLS runtime role contextly_app only. It returns only the row
-- identity fields needed to download and process a document -- never content.

alter table documents
    add column lease_until timestamptz,     -- worker lease deadline; null = not leased
    add column retry_count int not null default 0;  -- transient-failure attempts so far

-- Supports the claim predicate: eligible = uploaded, or processing with an
-- expired lease, never deleted.
create index documents_claim_idx
    on documents (status, lease_until)
    where deleted_at is null;

create function worker_claim_next(lease_seconds int)
returns table (
    id uuid, user_id uuid, storage_path text, filename text, retry_count int
)
language sql
security definer
set search_path = public
as $$
    update documents d
    set status = 'processing',
        lease_until = now() + make_interval(secs => lease_seconds),
        updated_at = now()
    where d.id = (
        select id from documents
        where (status = 'uploaded' or (status = 'processing' and lease_until < now()))
          and (lease_until is null or lease_until < now())
          and deleted_at is null
        order by created_at
        limit 1
        for update skip locked
    )
    returning d.id, d.user_id, d.storage_path, d.filename, d.retry_count;
$$;

-- Least privilege: the claim function is callable by the runtime role only.
revoke execute on function worker_claim_next(int) from public;
grant execute on function worker_claim_next(int) to contextly_app;
