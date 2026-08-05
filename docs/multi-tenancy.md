# Multi-Tenancy

Every user is a tenant. The system guarantees that User A cannot read, retrieve,
or modify any of User B's documents, chunks, conversations, messages, or files.

Multi-tenancy is treated as a **security boundary** enforced at four independent
layers. Defense in depth: every layer must fail closed on its own.

## 1. The four enforcement layers

| Layer | Mechanism | Protects |
|---|---|---|
| API | JWT validation + `user_id = current_user` on every query; owner check per resource | Direct API abuse |
| Database | Postgres **Row Level Security** on all tenant tables | Any mis-issued query, SQL mistakes, or future code paths |
| Vector retrieval | Search query filters `document_id IN (docs of this conversation)`; docs are user-scoped | Cross-user vector leakage via retrieval endpoint |
| Storage | File path prefix `{user_id}/…` + per-user storage policies + short-lived signed URLs | Direct file access |

## 2. RLS design

RLS is enabled on `profiles`, `documents`, `conversations`, `conversation_documents`,
`messages`. `document_chunks` is protected through a subquery on `documents` (chunks
have no `user_id` column — avoids denormalizing the tenant key).

```sql
alter table documents enable row level security;
alter table conversations enable row level security;
alter table conversation_documents enable row level security;
alter table messages enable row level security;
alter table document_chunks enable row level security;

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
```

### How it works with Supabase

- Supabase Auth sets the `request.jwt.claims` / `auth.uid()` for queries made with the
  user's JWT. RLS then runs automatically for any SQL executed with a user token.
- **Critical rule:** the backend (FastAPI) connects with a **non-`postgres` role** that
  does **not** bypass RLS. If the service-role key were used for runtime queries, RLS
  would be skipped — that key is only for migrations/admin paths, never runtime reads.

### Belt-and-suspenders

RLS alone is invisible in a code review. The application **also** scopes every ORM
query with `user_id = current_user` (or a join through `conversation_id` → user). This
makes tenant isolation auditable in the code and covers paths where the DB role might
not carry the JWT (e.g. the worker).

## 3. Tenant isolation in the worker

The DB-backed worker processes rows selected with `user_id`-agnostic claims, but it
only touches a single row that was already inserted by the authenticated API call,
and it writes chunks under the same `document_id`. It must never serve reads to users;
it never reads storage via user tokens (uses a service credential with a
`{user_id}/…` path enforced by storage policies).

## 4. Storage isolation

- Object key format: `{user_id}/docs/{document_id}.pdf` — user id in the path **and**
  in the policy.
- Supabase Storage policies: `read/select` only when `storage.foldername(name)[1] = auth.uid()::text`.
- The API returns short-lived signed URLs (5–10 min) for download/preview; the raw
  object is never exposed with a public URL.

## 5. Threat scenarios → control mapping

| Attack | Controls |
|---|---|
| User A enumerates `GET /documents/{id}` with B's id | API owner check (404/403) + RLS |
| User A passes B's `document_id` in `conversation_documents` | API validates each id belongs to current user + RLS check constraint |
| User A crafts a vector-search request with B's doc ids | Retrieval filters documents by `conversation_id` which is user-owned |
| User A guesses B's storage path | Storage policies reject cross-user paths |
| User A calls the worker endpoints | Worker has no public endpoints; API-only surface |
| Service-role key leak | Runtime code never uses it; it lives only in CI/migrations secrets |

## 6. Tests that must pass (written early)

See [testing.md](testing.md) — a dedicated integration test matrix asserts every one
of these scenarios as 403/404/empty with two real users.
