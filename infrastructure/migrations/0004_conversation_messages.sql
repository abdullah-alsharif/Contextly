-- Phase 7 chat: assistant status marker + idempotency support (docs/chat.md §1,
-- §4-6, docs/api.md §4; specs/008-chat-conversations/data-model.md).
--
-- status: 'done' for completed messages; 'error' marks a partial assistant
--         message persisted after a mid-stream provider failure (docs/chat.md
--         §6, docs/rag.md §7) so the UI can offer a retry.
-- idempotency_key: client-supplied Idempotency-Key on user messages; the
--         partial unique index is the concurrency-safe dedupe arbiter
--         (INSERT ... ON CONFLICT DO NOTHING RETURNING id).

alter table messages
    add column status text not null default 'done'
        check (status in ('done', 'error'));

alter table messages
    add column idempotency_key text;

create unique index messages_idempotency_idx on messages
    (conversation_id, idempotency_key) where idempotency_key is not null;
