# MVP Scope

The MVP is intentionally small. It must be rock solid and demonstrable end-to-end
before any of the deferred items exist.

## 1. In scope (must work end-to-end)

```
Authentication (Supabase, JWT)  + email/password
Document upload (PDF, ≤ 10 MB)
Storage (supabase/local behind StorageProvider)
PDF parsing with page numbers   (pypdf)
Chunking  (~500 tokens, ~50 overlap, page-aware)
Embeddings (locked model: bge-m3, 1024 dims)
pgvector storage + HNSW index
RAG retrieval (top-K 6, per-user + conversation filter)
LLM answer (streaming SSE)
Chat history (persistent conversations + messages)
Source citations (filename + page)
Multi-tenant security (RLS + query scoping + storage isolation)
```

## 2. Deliberately deferred (even though obvious)

| Feature | Why deferred | When to revisit |
|---|---|---|
| Document reprocessing | reuses pipeline; pure UX sugar for MVP | after eval shows chunking is wrong |
| Multiple providers in prod | one `AI_PROVIDER` at a time behind the interface | when NVIDIA free tier weakens |
| Hybrid search / reranking / query rewriting | no evidence of need; adds complexity | when eval recall@K or demo fails |
| Parent–child retrieval | tuning overhead | when answer quality demands smaller chunks |
| Non-PDF types (docx, txt, etc.) | parser surface per type | second milestone |
| Async frontend status push | polling `GET /documents` is fine in MVP | when processing > ~1 min routinely |
| Admin panel / usage dashboards | dashboard exists, no admin | never for portfolio |
| Org/workspace (true multi-tenant) | keep per-user isolation semantics honest | future scaling item |
| SAML/SSO/2FA | security theater for portfolio | – |

## 3. Definition of "done" for the MVP

1. New user signs up, uploads a PDF, sees `ready`, scrolls history, deletes docs.
2. Chat: new conversation → select documents → ask → **streaming** answer with
   `[n]` citations resolving to filename + page.
3. Security: multi-tenancy test matrix (10 scenarios) passes in CI.
4. RAG eval: recall@6 ≥ 0.85 on the fixture dataset; answer correctness reported
   (not yet gating).
5. Deployed to $0 stack; cold-start caveats documented in README.

Anything outside this list is a phase-12+ add-on.