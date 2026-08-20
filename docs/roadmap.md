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
- Desktop sidebar collapsible to a 64px icon rail with tooltips (persisted) —
  see docs/frontend-design.md "Sidebar".
- Sidebar rebuilt to the ChatGPT-style information architecture: logo header
  with search + collapse toggle, Documents row + filled "New Conversation"
  CTA, inline Pinned/Recents/Archived sections, account (Settings/Log out
  popover) fixed at the bottom, hovering the rail (or clicking its
  whitespace) expands it via the logo-area toggle,
  medium screens start collapsed — see docs/frontend-design.md "Sidebar".

## Phase 13 — Chat multi-turn context
- **Objective:** referential follow-ups resolve via retrieval-query rewrite; the
  generation prompt carries a bounded history window; all knobs config-driven.
- **Components:** `services/chat_context.py` (window fetch/truncate, LLM
  question rewrite with raw-question fallback, prompt builder), `chat_*`
  settings, FR-010 request logging, `eval/datasets/conversational.json` +
  `eval/run_eval.py --dataset conversational`.
- **Spec:** `specs/014-chat-multi-turn-context/`; details in [chat.md](chat.md) §4
  and [security.md](security.md) §4.
- **DoD:** 10-test multi-turn integration matrix green; regression suite green;
  conversational fixtures clear recall@6 ≥ 0.85 (advisory gate); report committed;
  docs updated. Zero API/schema change.

## Phase 14 — User action log
- **Objective:** every user-facing document action and pipeline outcome lands in a
  write-once `action_logs` row; the Logs page shows the history with
  action/date filters and per-entry diagnostics (failure reason + stack trace).
- **Components:** migration 0010 (`action_logs` + RLS, `clock_timestamp()`
  ordering) + 0011 (`restored` event), `services/action_logs.py`
  (`record_event`), capture points in `services/documents.py` +
  `services/pipeline.py`, `api/logs.py` (`GET /api/v1/logs` with
  `action_type`/`from`/`to` filters + paging), `app/(app)/logs` page +
  `components/log-table.tsx` (chips, date range, one-at-a-time details),
  sidebar Activity Log entry.
- **Spec:** `specs/016-user-action-logs/`; details in [database.md](database.md)
  §2.5, [api.md](api.md) §6, and [multi-tenancy.md](multi-tenancy.md) §2.
- **DoD:** recording + RLS + API + filters tests green (425-test suite); frontend
  gates (`tsc`, `eslint`, `build`) green; docs amended (FR-015); quickstart
  verified.

## Dependency graph

```
0 → 1 → 2 → 3 → 4 → 6 → 7 → 8
         │         ↕         ↓
         └→ 5 ──────→ 9/10 → 11 → 12 → 13 → 14
```
Legend: ⚂ parallelizable, ⚡ preloadable expertise.
