# Contextly — Technical Blueprint

This directory is the implementation blueprint for **Contextly**, a multi-tenant AI
document platform with RAG chat. It is derived from `idea.md` and consolidates every
architectural decision agreed on before implementation code is written.

## Locked decisions (MVP)

| Topic | Decision |
|---|---|
| Auth | Supabase Auth (JWT, hosted) |
| Postgres + vectors | Supabase hosted Postgres **or** self-hosted with `pgvector` (driven by `DATABASE_URL`) |
| File storage | Supabase Storage via a `StorageProvider` interface (swap to S3/B2 later) |
| Backend | FastAPI (Python) — Python for RAG/document processing |
| Frontend | Next.js + TypeScript + Tailwind |
| Async processing | DB-backed worker (polling + lease/heartbeat). **No Redis/Celery/RabbitMQ** |
| Embedding model | Locked early; default NVIDIA `nv-embedqa-e5-v5` (1024 dims, hosted API — `bge-m3` retired there). Vector dims must match the model |
| Vector index | pgvector HNSW, L2 distance, `vector(1024)` |
| Chunking defaults | ~500 tokens, ~50 token overlap (≈1200/120 chars), page-aware |
| Retrieval defaults | Top-K 6, cosine/L2, no hard score threshold initially, scores logged |
| Chat | Persistent conversations + multi-document selection + **streaming** from MVP |
| Document scope | PDF only, 10 MB max, page numbers captured |
| Sources | Persisted per assistant message (document id, filename, page, chunk, score) |
| AI abstraction | `AIProvider` (`embed`, `generate`, `stream`) — NVIDIA now, OpenRouter later |
| Deployment | $0 tiers first (Vercel + Render + Supabase). VPS optional later |
| Out of MVP | Document reprocessing, hybrid search, reranking, query rewriting, Redis/Celery, async eval dashboards |

## Document map

| Doc | Covers |
|---|---|
| [architecture.md](architecture.md) | High-level system, Mermaid diagram, data flow, component responsibilities |
| [database.md](database.md) | Postgres schema, ERD, indexes, pgvector design |
| [multi-tenancy.md](multi-tenancy.md) | RLS strategy, four enforcement layers |
| [ingestion.md](ingestion.md) | Document pipeline, state machine, DB-backed worker |
| [rag.md](rag.md) | Retrieval pipeline, context construction, source attribution |
| [chat.md](chat.md) | Conversation model, document selection, streaming |
| [api.md](api.md) | Full REST API specification |
| [ai-providers.md](ai-providers.md) | `AIProvider` / `StorageProvider` abstractions |
| [security.md](security.md) | Auth, uploads, RAG security, API security |
| [deployment.md](deployment.md) | $0 deployment, env vars, migrations, CI/CD |
| [deployment-walkthrough.md](deployment-walkthrough.md) | Beginner path: get every account/credential and run the deployment |
| [local-dev.md](local-dev.md) | Docker Compose, repo structure, first-run commands |
| [frontend-design.md](frontend-design.md) | UI design system → Tailwind tokens, components, page layouts |
| [observability.md](observability.md) | Structured logging, metrics, tracing |
| [testing.md](testing.md) | Test strategy + RAG evaluation dataset |
| [mvp-scope.md](mvp-scope.md) | Strict MVP definition |
| [roadmap.md](roadmap.md) | Incremental phases 0–12 with definitions of done |
| [tradeoffs.md](tradeoffs.md) | Trade-offs, risks, future scaling strategy |

## Golden rules

1. Security is a boundary, not an app-layer filter. RLS + session-scoped queries + signed storage URLs, all three.
2. Every phase ends in a working, testable increment.
3. Nothing is hard-coupled to any external vendor past one thin module.
4. MVP ships only what is in [mvp-scope.md](mvp-scope.md); everything else is explicitly deferred.

## Design source material

- [`../designs/design-system.md`](../designs/design-system.md) — raw token spec (colors, typography, spacing, elevation) authored externally; reference only.
- [`../designs/prototypes/chat.html`](../designs/prototypes/chat.html) + `dashboard.html` — interactive single-file UI references.
- [frontend-design.md](frontend-design.md) — the implementable distillation of the above for Next.js/Tailwind.