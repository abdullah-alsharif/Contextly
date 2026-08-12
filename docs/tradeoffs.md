# Trade-offs, Risks, and Scaling

## 1. Major trade-offs (accepted)

| Decision | What we give up | What we gain |
|---|---|---|
| Supabase for Auth+Storage+DB | Vendor coupling for these three; free-tier pause risk | One platform, battle-tested RLS, zero auth code, fast MVP |
| Next.js **and** FastAPI | Two runtimes, two deploys, cold starts | Python for document processing + RAG; Next for UI |
| DB-backed worker (no queue) | No at-least-once durability across restarts, no priorities | Zero infra, one moving part, fine at portfolio scale |
| HNSW L2, no hybrid search | Recall on exact-keyword queries; no fuzzy fallback | Simple, fast, explainable |
| Chunking by token approximation (char split) | Slightly imprecise boundaries vs. true tokenizers | No tokenizer dependency at ingest time; fine with overlap |
| Top-K fixed 6, no threshold | Some irrelevant chunks enter context | Deterministic behavior; scores logged for future tuning |
| Single embedding model locked (1024 dims) | Model-swap = migration + re-embed | pgvector index stability; no cross-model searches |
| Reprocess only for `failed` docs | `ready` docs can't re-index after a tuning change | Failed-doc recovery without accidental re-embedding of healthy docs |
| $0 deployment | Cold starts, pauses, provider flakiness | Zero cost, truthful demo story |
| Soft delete only for documents | Hard-delete semantics slightly fuzzy | Conversation source snapshots stay consistent |

## 2. Major technical risks (with mitigations)

| Risk | Likelihood | Mitigation |
|---|---|---|
| NVIDIA free endpoints disappear/rate-limit mid-project | High | `AIProvider` env switch to OpenRouter; `FakeProvider` for CI |
| Embedding model changes dims → pgvector index breaks | Medium | Model + dims locked in one config, validated at startup; eval pinned to that model |
| Supabase free tier pauses the project | High | cron `/healthz`; VPS fallback documented; storage/auth behind abstractions |
| RLS misconfiguration silently leaks data | Medium | Runtime role never bypasses RLS; 10-scenario test matrix in CI; belt-and-suspenders query scoping |
| Prompt injection in uploaded docs | Medium | Delimiters + system instruction; documented residual risk |
| RAG answers look bad (retrieval misses) | Medium | Eval harness from Phase 5; chunking/top-K tunable by env |
| Scanned PDFs have no text layer | Certain for some users | Clear `failed` message; README documents PDF requirements |
| Worker claims but crashes mid-embed | Low | Lease + reclaim; retry with backoff |
| Cold-start demo embarrassment | Medium | Documented; cron keep-alive; optional VPS |
| pgvector HNSW build time on big uploads | Low | Build index after load; chunked bulk inserts |

## 3. When each deferred component becomes justified

| Component | Justification threshold | What it fixes |
|---|---|---|
| Real queue (Redis/Celery/… ) | >10k docs/day or multi-worker concurrency needs | Durable retries, priorities, worker fleet management |
| Hybrid search | Eval shows keyword-heavy queries miss with vectors alone | Recall for names/codes/acronyms |
| Reranker | Eval recall fine but top-K order wrong at higher K | Precision of final context |
| Query rewriting / multi-hop | Follow-up questions degrade answer quality | Conversation-aware retrieval |
| Parent–child retrieval | Facts split across chunk boundaries | Answer completeness |
| Separate vector DB | > ~1M vectors or vector-specific scaling | Cost/query-latency isolation |
| Message broker events | Business needs fan-out (webhooks, analytics) | Decoupling |
| Microservices | Team > ~5 working separate deploys | Independent scaling |
| Kubernetes | No — stays a VPS/compose job even then | (explicitly: never without a real reason) |
| Caching layer | Hot reads (profiles, doc lists) with real traffic | Latency |
| Multi-region / CDN storage | Global audience | Latency/egress |

## 4. Future scaling strategy (honest, not aspirational)

1. **Data:** keep everything in Postgres until vectors dominate; then move embeddings
   to a dedicated pgvector cluster or vector DB — storage abstraction stays.
2. **Compute:** FastAPI stateless + horizontal instances behind the same DB; worker
   scales by adding processes reading `FOR UPDATE SKIP LOCKED`.
3. **Processing:** swap DB-backed worker for Celery/RQ only when queues/retries matter.
4. **Product:** workspaces (orgs) = add `orgs`/`memberships` tables + RLS policy tweak —
   the multi-tenancy model extends cleanly.
5. **Cost:** every external call logged with token counts; per-user quotas arrive with
   the metrics from [observability.md](observability.md).

## 5. What this project is, in one paragraph

A modular-monolith RAG SaaS that is honest about its scale: production-quality
isolation and testability at single-user-per-tenant, portfolio-scale traffic, and an
architecture that has an exit path for every vendor — without pretending it needs
infrastructure it doesn't.