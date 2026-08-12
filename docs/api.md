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
the backend only validates JWTs. The backend exposes `/auth/me` for the profile.

| Method | URL | Auth | Body | Response | Errors |
|---|---|---|---|---|---|
| POST | `/auth/register`* | none | uses Supabase `signUp` | n/a | delegated to Supabase |
| POST | `/auth/login`* | none | uses Supabase `signIn` | n/a | delegated |
| GET | `/auth/me` | JWT | – | `200 {profile}` | 401 |
| POST | `/auth/logout`* | JWT | – | 204 | – |

\* forwarded/proxied by the frontend server to Supabase; not part of FastAPI in MVP.

## 2. Documents

| Method | URL | Body | Response | Errors |
|---|---|---|---|---|
| POST | `/documents` | `multipart/form-data`: `file` | `201 {document}` | 400 (not pdf), 413 (too large), 401 |
| GET | `/documents` | – | `200 [{document}]` (status filter optional `?status=`) | 401 |
| GET | `/documents/{id}` | – | `200 {document, processing: {...}}` | 404 |
| DELETE | `/documents/{id}` | – | `204` | 404 |
| PATCH | `/documents/{id}/reprocess` | – | `200 {document}` (status reset to `uploaded`) | 400 (not failed), 404 |

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

**Reprocessing:** `PATCH /documents/{id}/reprocess` re-queues a **failed**
document: status → `uploaded`, `retry_count`/`status_error`/`total_chunks`
cleared, chunks purged (same transaction) and the existing worker picks it up
(docs/ingestion.md §7). Non-`failed` documents → `400`; the 404 rules are
unchanged (docs/security.md §2).

## 3. Conversations

| Method | URL | Body | Response | Errors |
|---|---|---|---|---|
| POST | `/conversations` | `{ "title"?, "document_ids": [uuid] }` | `201 {conversation}` | 404 (bad or unowned doc id — deliberately ambiguous, anti-enumeration), 401 |
| GET | `/conversations` | – | `200 [{conversation}]` (by `updated_at` desc) | 401 |
| GET | `/conversations/{id}` | – | `200 {conversation, documents: [document]}` | 404 |
| PATCH | `/conversations/{id}` | `{ "title"?, "document_ids"?: [uuid] }` | `200 {conversation}` | 404, 422 |
| DELETE | `/conversations/{id}` | – | `204` | 404 |

PATCH semantics: full replace of `document_ids` when present (empty array = clear
selection). Partial updates supported for `title`.

Conversation object:
```json
{
  "id": "uuid", "title": "Job applications", "created_at": "…", "updated_at": "…"
}
```

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
| 413 | upload too large |
| 422 | validation failure (schema, question too long) |
| 429 | rate limited (see [security.md](security.md)) |
| 500 | internal (structured-logged with request id) |
| 502/503 | upstream AI/storage failure |

## 7. Versioning & docs

All routes namespaced under `/api/v1`. FastAPI auto-serves OpenAPI at `/docs` in dev;
disabled in prod unless flagged.