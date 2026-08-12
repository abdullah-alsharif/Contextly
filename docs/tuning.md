# Phase 12 — RAG Tuning Decision Record

**Source**: docs/roadmap.md Phase 12, docs/rag.md §2, docs/testing.md §6.
**Spec**: specs/013-polish-tuning-portfolio/spec.md (FR-001..004, SC-001/002/007).
**Data**: [eval/reports/tuning-sweep.md](../eval/reports/tuning-sweep.md) (9 configs, 60
queries, hermetic lexical embeddings, `AI_PROVIDER=fake` forced) +
per-config reports `eval/reports/sweep-*.md`.
**Reproduce**: `PYTHONPATH=backend python3 -m eval.sweep --out
eval/reports/tuning-sweep.md` (deterministic — byte-identical on re-run).

## Executive summary

**The MVP defaults (chunk ~500 / overlap ~50 tokens, top-K 6, `ef_search` 40) are kept
as-is.** Every candidate scored recall@6 = 1.000 on both gated variants (doc + page,
docs/testing.md §6) — the committed dataset's ceiling — and no candidate matched the
default's **perfect document MRR (1.000)** while also improving page MRR. Per spec
FR-003, a default changes only when a candidate measurably improves retrieval; none
did. No defaults changed; no `docs/rag.md` §2 edits needed; the committed baseline
report (`eval/reports/rag-eval.md`) is untouched.

## Sweep results (summary)

| Config | recall@6 | MRR | page recall@6 | page MRR | Gate |
|---|---|---|---|---|---|
| **500/50/top-6 (default)** | **1.000** | **1.000** | **1.000** | 0.956 | PASS |
| 300/50/top-6 | 1.000 | 0.992 | 0.983 | 0.936 | PASS |
| 400/50/top-6 | 1.000 | 0.983 | 0.983 | 0.950 | PASS |
| 600/50/top-6 | 1.000 | 0.992 | 1.000 | 0.978 | PASS |
| 700/50/top-6 | 1.000 | 0.983 | 1.000 | 0.963 | PASS |
| 500/25/top-6 | 1.000 | 1.000 | 1.000 | 0.956 | PASS |
| 500/75/top-6 | 1.000 | 1.000 | 1.000 | 0.956 | PASS |
| 500/50/top-4 | 1.000 | 1.000 | 1.000 | 0.956 | PASS |
| 500/50/top-8 | 1.000 | 1.000 | 1.000 | 0.956 | PASS |

Full per-config detail (per-query ranks + diagnostics): `eval/reports/sweep-*.md`.

## Decisions

### D1 — Chunk size: keep ~500 tokens (default)

- **Why**: default scores perfect doc recall + MRR. Chunk 600 improves page MRR
  (+0.022) but trades away perfect doc MRR (−0.008: one query's expected document is
  no longer first) and grows context per chunk. Chunks 300–400 drop page recall to
  0.983 — smaller windows split multi-sentence facts and reduce per-page coverage
  (docs/ingestion.md §4.3 page-aware merging).
- **Trade-off**: chunk size vs precision — larger chunks keep pages covered but
  blur the document-level ranking (a chunk spanning several pages dilutes the signal
  that picks one document over a similar-topic hard negative); smaller chunks sharpen
  ranking but risk splitting facts, dropping page coverage. Measured: 400-token worst
  doc MRR 0.983 / page recall 0.983; 600-token page MRR best 0.978 but doc MRR 0.992.
  Default sits at the Pareto-optimal corner: perfect doc recall + MRR, page recall
  1.000, page MRR 0.956.

### D2 — Chunk overlap: keep ~50 tokens

- **Why**: overlap 25 and 75 are byte-identical to the default on every metric
  (1.000/1.000/1.000/0.956). No measurable effect on this corpus — the page-aware
  chunker (docs/ingestion.md §4.3) already keeps sentence boundaries intact, so
  overlap only matters when a sentence straddles a cut point (docs/rag.md §2: boundary
  resilience). 50 stays: it is the documented MVP rationale, costs ~10% extra tokens,
  and there is zero evidence either direction.
- **Trade-off**: overlap vs cost — more overlap means more duplicate tokens per chunk
  (with 50/500 ≈ +10% embedding + retrieval volume); no measured retrieval benefit
  either way on this dataset.

### D3 — Top-K: keep 6

- **Why**: top-4 and top-8 are metric-identical to top-6 on this corpus (expected
  document always ranked first, so K truncation never bites at any of 4/6/8).
- **Trade-off**: top-K vs context size vs cost — each extra chunk adds ~500 tokens to
  the generation prompt (docs/rag.md §2 context ≈ 6 chunks ~3k tokens). This corpus
  saturates at K=4, so K=6 is pure headroom for larger real-world corpora; K=6 stays
  as the documented default with the rationale unchanged.

### D4 — `ef_search`: keep 40

- **Why**: `ef_search` is a partial-search (HNSW) recall/speed knob on the pgvector
  index — set transaction-locally in retrieval
  (`set_config('hnsw.ef_search', …)`, backend/app/services/retrieval.py:135-138). It is
  **invisible to the hermetic eval harness**, which ranks exhaustively over the
  in-memory corpus (eval/run_eval.py:275-345) — an exhaustive search is the recall
  ceiling any `ef_search` approximates, so the harness can never measure it. Per spec
  FR-004 / research R3, no fake measurement was invented.
- **Trade-off**: `ef_search` vs latency — larger values scan more of the HNSW graph,
  approaching exhaustive (exact) recall at increasing per-query cost; smaller values
  are faster but can miss near neighbors. 40 is pgvector's conventional middle ground
  for `LIMIT top_k` (6) queries and the documented MVP choice (docs/rag.md §2). The
  opt-in real-DB probe (Postgres + real embeddings + keys) can measure latency/recall
  for 20/40/80 later if the product grows; it is credential-bound, not a phase gate.

### D5 — Answer quality: not measured in the hermetic sweep

- The fake provider's canned generation scores correctness ~0.033 (plumbing only,
  docs/testing.md §6); answer metrics are meaningful only with a real provider
  (`eval.sweep --provider nvidia|openrouter` + keys, research R7) and are outside the
  phase gate. Grounding (answer facts in retrieved excerpts) is 1.000 for every
  config — the retrieved context always contains the expected facts.

## Trade-off summary (spec FR-005)

| Trade-off | Balanced by | Measured evidence |
|---|---|---|
| Context size vs cost | top-K 6 + chunk 500 ≈ ~3k tokens/query prompt | top-4/6/8 identical metrics; every extra chunk ≈ 500 tokens |
| Chunk size vs precision | 500 tokens: facts fit (page recall 1.000) while document ranking stays sharp (doc MRR 1.000) | 300/400 drop page coverage (0.983); 600-700 blur doc ranking (0.992/0.983) |
| `ef_search` vs latency | HNSW recall/speed; 40 = conventional balance at K=6 | not harness-measurable (exhaustive ranking = recall ceiling); real-DB probe is the future opt-in |
| Overlap vs cost | ~50 tokens boundary resilience at ~+10% token cost | 25/50/75 metric-identical on this corpus |

## What this leaves for the future

- Larger/diverse corpora (more documents, harder negatives) would make the sweep
  discriminating beyond 1.000 ceilings — the harness and driver are ready;
  `docs/testing.md` §6 documents the dataset schema for extension.
- Real-DB `ef_search` latency probe (credential-bound).
- Real-provider answer-quality sweep (credential-bound).