# Contextly - RAG Parameter Sweep Report (Phase 12)

**Reproduce:** `PYTHONPATH=backend python3 -m eval.sweep --out eval/reports/tuning-sweep.md` (hermetic; `AI_PROVIDER=fake` forced)

Sweeps the committed Phase-10 dataset (`eval/datasets/qa.json`, 60 queries) one-at-a-time around the MVP defaults (chunk ~500 / overlap ~50 tokens, top-K 6, docs/rag.md §2, docs/roadmap.md Phase 12). Retrieval metrics run on the deterministic lexical embeddings; `ef_search` is a pgvector HNSW knob invisible to the hermetic harness (see docs/tuning.md).

| Config | recall@6 | MRR | page recall@6 | page MRR | grounding | correctness | Gate (>= 0.85) |
|---|---|---|---|---|---|---|---|
| chunk=500/overlap=50/top-k=6 **default** | 1.000 | 1.000 | 1.000 | 0.956 | 1.000 | 0.033 | PASS |
| chunk=300/overlap=50/top-k=6  | 1.000 | 0.992 | 0.983 | 0.936 | 0.983 | 0.033 | PASS |
| chunk=400/overlap=50/top-k=6  | 1.000 | 0.983 | 0.983 | 0.950 | 0.983 | 0.033 | PASS |
| chunk=600/overlap=50/top-k=6  | 1.000 | 0.992 | 1.000 | 0.978 | 1.000 | 0.033 | PASS |
| chunk=700/overlap=50/top-k=6  | 1.000 | 0.983 | 1.000 | 0.963 | 1.000 | 0.033 | PASS |
| chunk=500/overlap=25/top-k=6  | 1.000 | 1.000 | 1.000 | 0.956 | 1.000 | 0.033 | PASS |
| chunk=500/overlap=75/top-k=6  | 1.000 | 1.000 | 1.000 | 0.956 | 1.000 | 0.033 | PASS |
| chunk=500/overlap=50/top-k=4  | 1.000 | 1.000 | 1.000 | 0.956 | 1.000 | 0.033 | PASS |
| chunk=500/overlap=50/top-k=8  | 1.000 | 1.000 | 1.000 | 0.956 | 1.000 | 0.033 | PASS |

_Default row first; one axis perturbed at a time. `correctness` reflects the generation provider: the fake provider scores ~0 (plumbing only, docs/testing.md §6). Real-provider answer metrics are opt-in (`--provider nvidia|openrouter`, research R7)._

## Methodology

- Grid: chunk size 300/400/500/600/700, overlap 25/50/75, top-K 4/6/8, each axis perturbed around the defaults (research R2).
- Harness: `eval/run_eval.py` per config with `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS` env overrides and `--top-k` (eval/run_eval.py:164-197, 520-547); per-config reports written alongside this file.
- Gate: both recall@6 variants >= 0.85 (docs/testing.md §6). The sweep is measurement-only: it never changes defaults. If a config improves on the default, the decision to adopt it lives in `docs/tuning.md` (spec FR-003).
- Hermeticity: `AI_PROVIDER=fake` forced per run (constitution VI); real embeddings opt-in via `--provider` (research R7).
