# Development Roadmap

Every phase ends in a **working increment** that runs locally. Phases build on each
other; definitions of done are explicit. Parallelizable tracks are marked ⚡.

## Phase 0 — Project setup
- **Objective:** repo scaffold; green local dev loop; CI skeleton.
- **Components:** monorepo layout, `docker-compose.yml`, FastAPI hello-world + `/healthz`,
  Next.js App Router shell, migrations runner, `.env.example`, `Makefile`.
- **Files:** everything in `infrastructure/`, `backend/app/main.py`, `frontend/app/page.tsx`.
- **DoD:** `make up` → both services up; `/healthz` green; CI runs ruff/tsc on push.

## Phase 1 — Database (migrations + schema)
- **Objective:** all tables from [database.md](database.md), vanilla SQL.
- **Files:** `infrastructure/migrations/0001_*.sql`, engine/session in `backend/app/db/`.
- **DoD:** `make migrate` applies cleanly; RLS enabled with policies; `document_chunks`
  has `vector(1024)` column.

## Phase 2 — Authentication
- **Objective:** JWT-based auth with configurable dev mode.
- **Components:** `get_current_user` dependency, `DevAuthenticator` + Supabase JWT
  verifier, `/auth/me`, `profiles` bootstrap upsert.
- **Depends on:** Phase 1. **Tests:** auth unit + API 401/403 set.
- **DoD:** request with valid dev/user JWT resolves a profile; invalid/expired → 401.

## Phase 3 — Document upload + storage ⚂
- **Objective:** POST/GET/DELETE documents; storage abstractions wired.
- **Components:** `StorageProvider` (+Supabase/local), upload validation, documents
  service + router, ownership checks.
- **Files:** `providers/storage/*`, `api/documents.py`, `services/documents.py`.
- **Depends on:** 2.
- **DoD:** upload → row with status `uploaded` + object at `{user_id}/docs/{id}.pdf`;
  delete removes file + row; 400/413/404 paths tested.

## Phase 4 — Document processing (PDF → chunks) ⚂
- **Objective:** DB-backed worker: parse → chunk → persist chunks (no embeddings yet).
- **Components:** worker loop with lease + retry, `pypdf` parsing, chunker, `ready`/`failed`.
- **Depends on:** 1, 3.
- **Tests:** pipeline unit + worker integration + failure/retry matrix.
- **DoD:** PDF → `ready` with page-aware chunks; corrupt PDF → `failed` + `status_error`.

## Phase 5 — Embeddings + pgvector ⚂ (can parallelize with 4)
- **Objective:** `AIProvider.embed`, HNSW index, chunk rows filled with vectors.
- **Components:** `AIProvider` interface + NVIDIA/OpenRouter/Fake, embed-on-ingest step,
  `CREATE INDEX … hnsw`.
- **Depends on:** 1, 4 (schema only).
- **DoD:** chunks carry matching-dim vectors; index exists; provider switch via env.

## Phase 6 — Basic RAG (engine only) ⚡
- **Objective:** retrieval + context builder (no chat/LLM UI yet).
- **Components:** `services/retrieval.py` (filters, top-K), prompt/context builder,
  `POST /rag/query` debug endpoint (dev only).
- **Depends on:** 5.
- **Tests:** retrieval relevance, empty retrieval, tenant filter.
- **DoD:** query returns top-K chunks with filename+page+score, scoped to user + conversation docs.

## Phase 7 — Chat + streaming
- **Objective:** conversations, message send via SSE streaming, history, selection.
- **Components:** `api/conversations.py`, `api/messages.py`, streaming generate,
  sources snapshot on save, idempotency key.
- **Depends on:** 6.
- **DoD:** browser gets token deltas; `done` persists assistant message with `sources`.

## Phase 8 — Frontend build-out
- **Objective:** all pages [api.md]; chat UI with streaming, citations, empty/loading states.
- **Components:** `frontend/app/(app)/*`, `components/chat.tsx`, `components/upload.tsx`,
  `lib/api-client.ts`.
- **Depends on:** 7.
- **DoD:** manual happy path end-to-end on real embeddings; Playwright smoke green.

## Phase 9 — Security hardening ⚡
- **Objective:** the 10-test multi-tenancy matrix + rate limiting + file hardening.
- **Components:** `tests/security/*`, rate-limit dependency, magic-byte check, signed URLs.
- **Depends on:** 3 (matrix needs uploads), parallelizable with 6–8.
- **DoD:** matrix 10/10 in CI; uploads guard rails tested.

## Phase 10 — RAG evaluation ⚡ (can start once Phase 5 lands)
- **Objective:** `eval/` dataset + harness; measurable retrieval quality.
- **Components:** `eval/datasets/`, `eval/documents/`, `run_eval.py` (recall@6/MRR + judge).
- **Depends on:** 5 (retrieval), 7 (full pipeline) for answer metrics.
- **DoD:** recall@6 ≥ 0.85 on fixtures; report committed; thresholds in CI.

## Phase 11 — Deployment
- **Objective:** $0 stack live with secrets + CORS + health checks.
- **Components:** Vercel project, `render.yaml`, env matrix, `readme` ops notes.
- **Depends on:** 8.
- **DoD:** a real user (eval account) can use the demo in a browser on prod domains.

## Phase 12 — Polish + post-MVP eval rounds
- Fine-tune chunk size/top-K/ef_search from eval results; document trade-offs; write the
  portfolio README + architecture summary with the Mermaid diagrams from `docs/`.
- Search chats popup rebuilt to the compact ChatGPT reference overlay (borderless
  16px query header, Clear/divider/X, ~70px rows with relative dates,
  5-at-a-time infinite scroll) — see docs/frontend-design.md "Search popup".

## Dependency graph

```
0 → 1 → 2 → 3 → 4 → 6 → 7 → 8
         │         ↕         ↓
         └→ 5 ──────→ 9/10 → 11 → 12
```
Legend: ⚂ parallelizable, ⚡ preloadable expertise.