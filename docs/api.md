# API Specification

Base path: `/api/v1` (FastAPI). All responses JSON unless noted (streaming is one SSE
endpoint). Auth: `Authorization: Bearer <JWT>` (Supabase). Auth failures → `401`.

Conventions:
- Tenant/ownership failures return `404` (not `403`) for resources — prevents
  enumeration of other users' ids. `403` is reserved for "authenticated but not allowed".
- Request body validation errors → `422` with field details.
- Error shape: `{"detail": "human message"}` (FastAPI default) with a stable
  `X-Request-Id` header for correlation.

## 1. Authentication

Supabase handles credentials. Frontend calls Supabase Auth directly (client-side flows);
the backend only validates JWTs. The backend exposes GET/PATCH `/auth/me` for the profile.

| Method | URL | Auth | Body | Response | Errors |
|---|---|---|---|---|---|
| POST | `/auth/register`* | none | uses Supabase `signUp` | n/a | delegated to Supabase |
| POST | `/auth/login`* | none | uses Supabase `signIn` | n/a | delegated |
| GET | `/auth/me` | JWT | – | `200 {profile}` | 401 |
| PATCH | `/auth/me` | JWT | `{"full_name": string?}` | `200 {profile}` | 401, 422 |
| POST | `/auth/logout`* | JWT | – | 204 | – |

\* forwarded/proxied by the frontend server to Supabase; not part of FastAPI in MVP.

## 2. Documents

| Method | URL | Body | Response | Errors |
|---|---|---|---|---|
| POST | `/documents` | `multipart/form-data`: `file` | `201 {document}` | 400 (not pdf), 409 (duplicate name), 413 (too large), 401 |
| POST | `/documents?replace=true` | `multipart/form-data`: `file` | `201 {document}` | 400, 413, 401 |
| GET | `/documents` | – | `200 [{document}]` (status filter optional `?status=`) | 401 |
| GET | `/documents/{id}` | – | `200 {document, processing: {...}}` | 404 |
| DELETE | `/documents/{id}` | – | `204` | 404 |
| POST | `/documents/{id}/cancel` | – | `204` | 409 (not queued/processing), 404 |
| PATCH | `/documents/{id}/reprocess` | – | `200 {document}` (status reset to `uploaded`) | 400 (not failed/cancelled), 404 |

Document object:
```json
{
  "id": "uuid",
  "filename": "refund-policy.pdf",
  "status": "ready",
  "file_size_bytes": 123456,
  "total_chunks": 42,
  "status_error": null,
  "created_at": "…", "updated_at": "…"
}
```
Upload response includes `status: "uploaded"`; client polls `GET /documents` (or a
short-lived `WS/EventSource`) until `ready | failed`.

**Multipart rules:** content-type must be `application/pdf`; extension `.pdf`;
size ≤ 10 MB (checked pre-upload and enforced again by the storage policy);
filename sanitized (strip path + control chars). Storage path is server-generated
(`{user_id}/docs/{document_id}.pdf`) — client filename is never used as a path.

**Cancellation:** `POST /documents/{id}/cancel` stops a queued (`uploaded`) or
in-flight (`processing`) document: status → `cancelled`, lease cleared. The
worker polls the status between pipeline stages and aborts the run as soon as
it is no longer `processing` — no further embedding requests are made and
nothing persists (docs/ingestion.md §1). A `cancelled` row holds no chunks, is
excluded from the duplicate check, and can be re-processed (see below).
Non-cancellable states → `409`; the 404 rules are unchanged (docs/security.md
§2).

**Reprocessing:** `PATCH /documents/{id}/reprocess` re-queues a **failed or
cancelled** document: status → `uploaded`, `retry_count`/`status_error`/
`total_chunks` cleared, chunks purged (same transaction) and the existing
worker picks it up (docs/ingestion.md §7). Other states → `400`; the 404
rules are unchanged (docs/security.md §2).

**Duplicate handling:** uploading a filename already held by an active
(non-deleted, non-superseded, non-cancelled) document → `409` with the
existing row's id in the `X-Existing-Document-Id` header. `POST
/documents?replace=true` instead supersedes that old document (status
`superseded`, row kept in the docs table) and processes the new upload
normally; a replace with no duplicate is a plain upload. The partial unique
index (user_id, filename) closes parallel-upload races — the loser gets the
same `409`.

Replace is **reversible** (docs/ingestion.md §7): the old document's chunks
stay in place and its previous status is remembered (`superseded_from`) while
the replacement processes. If the replacement reaches `ready`, the old version
is finalized as `superseded` (chunks purged); if it becomes `failed` or is
deleted first, the old document is restored to its previous status and remains
fully usable — the failed replacement row itself leaves the active set.

## 3. Conversations

| Method | URL | Body | Response | Errors |
|---|---|---|---|---|
| POST | `/conversations` | `{ "title"?, "document_ids": [uuid] }` | `201 {conversation}` | 404 (bad or unowned doc id — deliberately ambiguous, anti-enumeration), 401 |
| GET | `/conversations` | `?archived=true` lists archived only; `?q=…` searches instead (see below; paged by `offset`/`limit`) | `200 [{conversation}]` (pinned first, then `updated_at` desc; archived excluded by default) | 401, 422 (`q` > 200 chars, `offset` < 0, `limit` outside 1–50) |
| GET | `/conversations/{id}` | – | `200 {conversation, documents: [document]}` | 404 |
| PATCH | `/conversations/{id}` | `{ "title"?, "document_ids"?: [uuid], "pinned"?: bool, "archived"?: bool }` | `200 {conversation}` | 404, 422 |
| DELETE | `/conversations/{id}` | – | `204` | 404 |

PATCH semantics: full replace of `document_ids` when present (empty array = clear
selection); `title`/`pinned`/`archived` are set when present and left unchanged
when absent. `pinned` orders the conversation first in lists; `archived` hides
it from the default list (restorable via `archived: false`).

Conversation object:
```json
{
  "id": "uuid", "title": "Job applications",
  "pinned": false, "archived": false,
  "message_count": 3,
  "created_at": "…", "updated_at": "…"
}
```

`message_count` is the number of messages in the conversation. The sidebar
filters conversations with no chat history out of the recents list (a chat
appears there once its first message is sent).

Search (`?q=`): the sidebar "Search chats" feature. Case-insensitive match
over the caller's conversation **titles** and **message content** (user and
assistant), including archived conversations. Results are ranked — exact
title match, then partial title match, then message-content match, newest
`updated_at` first within each tier (id as final tiebreaker) — paged by
`offset`/`limit` (`limit` 1–50, `offset` ≥ 0; the frontend fetches 5 at a
time and appends while scrolling), and each result is the conversation
object plus a `preview` field: a short ellipsized snippet of the newest
matching message (null for title-only matches). Blank `q` falls back to the
normal list; `offset`/`limit` and `?archived=true` are ignored while `q` is
absent. Search never reads documents, UI labels, or other tenants' data.

## 4. Messages

| Method | URL | Body | Response | Errors |
|---|---|---|---|---|
| GET | `/conversations/{id}/messages` | – | `200 [message]` (oldest first, `?limit&cursor=`) | 404, 401 |
| POST | `/conversations/{id}/messages` | `{ "content": "…" }` | SSE stream | 404, 400 (no docs selected / empty), 413 (question too long), 401 |

Message object:
```json
{
  "id": "uuid", "role": "assistant",
  "content": "According to your documents, the refund period is 30 days [1].",
  "sources": [
    {"filename": "refund-policy.pdf", "page_number": 4,
     "document_id": "…", "chunk_index": 12, "similarity": 0.83}
  ],
  "input_tokens": 210, "output_tokens": 84,
  "retrieval_ms": 34, "llm_ms": 1280, "created_at": "…"
}
```

### SSE protocol (message send)

```
POST /conversations/{id}/messages  →  200 text/event-stream
event: meta   data: {"message_id": "…"}        # id to associate final write
event: delta  data: {"text": "partial"}
event: delta  data: {"text": "more…"}
event: done   data: {"id": "…", "sources": [...], "llm_ms": …}
event: error  data: {"message": "…"}           # terminal on provider failure
```

### Idempotency
Client sends `Idempotency-Key: <uuid>` on POST; backend dedupes the user message by
`(conversation_id, key)` and resumes/returns the same message id — safe retries on network drops.

## 5. Files (read/preview)

| Method | URL | Response | Notes |
|---|---|---|---|
| GET | `/documents/{id}/download-url` | `200 {url, expires_at}` | short-lived signed storage URL (5 min) |
| GET | `/documents/{id}/download` | `200 application/pdf` | authenticated byte stream (`Content-Disposition: inline`) |

A download URL is issued only for an owned, non-deleted document regardless of
processing status (mirrors `GET /documents/{id}`); a foreign/missing id returns
404 and the storage provider is never asked to sign. `expires_at` is the short
TTL (`STORAGE_SIGNED_URL_TTL_SECONDS`, validated 1‑3600s); expiry is **enforced
by the storage backend** (Supabase token `exp`). The `local` provider is
dev/CI-only and serves no expiry semantics (see `docs/security.md` §7).

Explicitly, there is **no** static file-serving endpoint; signed URLs only.

## 6. General error codes

| Code | Meaning |
|---|---|
| 401 | missing/invalid/expired JWT |
| 404 | resource not found or not owned (deliberately ambiguous) |
| 400 | business rule violation (wrong type, no docs selected) |
| 409 | duplicate filename on upload (`X-Existing-Document-Id` header) |
| 413 | upload too large |
| 422 | validation failure (schema, question too long) |
| 429 | rate limited (see [security.md](security.md)) |
| 500 | internal (structured-logged with request id) |
| 502/503 | upstream AI/storage failure |

## 7. Versioning & docs

All routes namespaced under `/api/v1`. FastAPI auto-serves OpenAPI at `/docs` in dev;
disabled in prod unless flagged.