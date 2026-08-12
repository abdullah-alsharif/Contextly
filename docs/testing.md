# Testing Strategy

Pytest (backend), Vitest/Playwright-lite (frontend). Test DB = the dockerized
Postgres, recreated per test run via migrations; `AI_PROVIDER=fake`,
`STORAGE_PROVIDER=local` in tests.

## 1. Backend unit tests

- Chunking: token counts, overlap correctness, page attribution, empty-text handling.
- Embedding/chat provider contracts: batching, retry/backoff, error mapping
  (using `FakeProvider` + monkeypatched transport for NVIDIA/OpenRouter).
- Prompt/context builder: numbering, filename+page prefixing, injection delimiters.
- JWT verification: valid/expired/wrong-audience/wrong-signature tokens.
- Rate limiter: burst then `429`.

## 2. Backend API/integration tests

- Auth: `401` without token, invalid token, expired session.
- Documents: upload OK → `uploaded`; non-PDF `400`; >10 MB `413`; list/delete flows.
- Conversations: create with/without documents, rename, delete cascade.
- Messages: send → user message persisted → SSE stream (`fake` provider streams)
  → assistant message with sources; empty-selection `400`; question-length `422`.
- Worker: uploaded → ready; parse failure → failed with `status_error`; retry count
  increments; lease expiry reclaim.

## 3. Multi-tenancy matrix (the critical tests)

Two real users A and B, both with documents/conversations/messages. Assert `403/404/[]`:

| # | Attempt by A | Expected |
|---|---|---|
| 1 | `GET /documents/{B.doc}` | 404 |
| 2 | `DELETE /documents/{B.doc}` | 404, B's row intact |
| 3 | `GET /conversations/{B.conv}` | 404 |
| 4 | `PATCH /conversations/{A.conv}` with `document_ids=[B.doc]` | 404, selection unchanged |
| 5 | `GET /conversations/{B.conv}/messages` | 404 |
| 6 | `POST /conversations/{B.conv}/messages` | 404 |
| 7 | Direct SQL: `select from document_chunks where document_id = B.doc` as A | 0 rows (RLS) |
| 8 | Storage: A's signed URL for B's file key | denied (policy) |
| 9 | Retrieval: A asks a question containing B's facts | B's chunks never in context (assert via fake-embedding fingerprint) |
| 10 | RLS policy test: `SET role` to A then query B's rows | empty |

## 4. Document processing tests

- Valid small PDF (fixture) → `ready`, `total_chunks > 0`.
- Empty/corrupt PDF → `failed` + `status_error` set.
- Encrypted PDF → `failed` (clear error).
- Scanned (no text layer) PDF → `failed` with "no text extracted".
- Oversized → rejected before upload (413) and by worker guard.
- Retry: flaky `FakeProvider` (fail 2×, succeed 3rd) → `ready`, `retry_count=2`.

## 5. RAG tests

- Relevant query → top-K includes expected chunks (deterministic with fake embeddings).
- Irrelevant query → no chunks above soft floor → empty-retrieval path.
- Empty retrieval → no LLM call, "no relevant documents" answer.
- Source attribution: assistant message `sources` contains filename + page + score for
  every cited chunk.
- Context construction: snippet numbering, page prefixes, untrusted-delimiter wrap.
- Streaming: SSE events terminate with `done` and a persisted message.

## 6. RAG evaluation dataset (early, `eval/`)

Deliberately small (~40–60 pairs), seed PDFs in `eval/documents/` (e.g. a made-up
company's policy pack: refunds, shipping, HR handbook — content with unambiguous
facts, page numbers known).

```json
// eval/datasets/qa.json
{
  "query": "What is the refund window?",
  "expected_document": "refund-policy.pdf",
  "expected_page": 2,
  "answer_contains": ["30 days"],
  "hard_negative_document": "shipping-policy.pdf"
}
```

Harness (`eval/run_eval.py`):

1. **Retrieval metrics** (offline, deterministic): `recall@k` (k=6), `MRR@k` — does
   the expected doc/page rank within top-K? Requires `expected_document` to embed
   somewhere in that doc — also catch a broken chunking/embedding pipeline early.
2. **Answer metrics** (LLM-as-judge): for each pair, run the RAG pipeline, then have
   the judge model score `faithfulness` (answer grounded in excerpts) and
   `correctness` (contains `answer_contains` facts). Fake-provider mode tests plumbing;
   real mode gives the true score.
3. Report: markdown table `results/` + pass/fail thresholds (recall@6 ≥ 0.85) that gate
   CI once stable.

The eval harness is written in Phase 4/5 (with chunking+embeddings), **not** deferred —
it is the measurable proof that RAG works.

### 6.1 Phase 10 realized harness

Implemented in Phase 10 (`specs/011-rag-evaluation/`):

- **Seed corpus** — `eval/documents/*.pdf`: 5 Acme policy PDFs generated
  deterministically by `eval/generate_documents.py` (refund, shipping, benefits,
  data security, HR handbook). Re-running the generator is byte-identical.
- **Dataset** — `eval/datasets/qa.json`: 60 query pairs following the schema
  above; each has an `expected_page`, `answer_contains` facts that the harness
  verifies sit on that page (drift fails the run), and a `hard_negative_document`.
- **Harness** — `eval/run_eval.py`: reads the PDFs, chunks with the locked
  Phase-5 defaults (chunk 500 / overlap 50 tokens, docs/rag.md §2), embeds via
  the configured provider, ranks each query over top-K=6, and computes
  `recall@6`, `MRR`, page-coverage variants, plus rule-based answer checks on
  full-pipeline runs (`answer_contains` in the generated answer → correctness,
  and in the retrieved excerpts → grounding).
- **Hermetic mode** — the fake provider's embeddings are content-blind
  (docs/ai-providers.md §2), so `AI_PROVIDER=fake` swaps in the deterministic
  lexical embedder `eval/embedding.py` (hashed word unigrams+bigrams, corpus IDF
  — stdlib only). CI uses this and needs no DB/network/keys. Real embeddings are
  the documented opt-in: `AI_PROVIDER=nvidia|openrouter` (+ keys) locally.
- **Cross-platform determinism** — the embedder computes its IDF log with
  IEEE-754 basic arithmetic only (`frexp` + odd-power series, `_log`), never
  the platform libm, so vectors are bit-identical on every IEEE-conformant
  machine and reports re-run byte-identical. A golden sha256 of the committed
  corpus vectors in `eval/tests` pins this; CI runs the same check on glibc.
- **Gate** — `recall@6 ≥ 0.85` (document *and* page-coverage variants) is the
  harness exit-code gate (docs/roadmap.md Phase 10 DoD) and is enforced in CI.
  On this 15-chunk corpus doc-level recall@6 sits near the content-blind random
  baseline (~0.8–0.9) while page coverage drops to ~0.4, so gating both keeps
  broken embedding/retrieval from slipping through. Report is committed to
  `eval/reports/rag-eval.md` and regenerated deterministically.
- **Run** — `make eval` (or `PYTHONPATH=backend python3 -m eval.run_eval
  --out eval/reports/rag-eval.md`); unit tests live in `eval/tests/`.
- **Scope (known limits)** — the harness is an offline upper bound on retrieval:
  it ranks with exact squared-L2 over all corpus chunks (mirroring the product's
  pgvector `embedding <-> query`, docs/rag.md §2), so it does not exercise the
  HNSW/ef_search approximation, conversation-document selection, or tenant
  scoping of `search_ready_documents`. It measures the chunking + embedding +
  ranking chain, which is exactly what Phase 12 tunes.

## 7. Frontend tests

- Unit: chat reducer/stream-assembly logic, sources rendering, formatting.
- E2E (Playwright, small): login → upload → wait ready → create conversation →
  select doc → ask → see streaming answer + sources. One happy path + one empty-state path.

## 8. CI

GitHub Actions: backend lint (ruff) + typecheck (mypy) + pytest; frontend
lint/typecheck/build; eval smoke on fixtures (fake provider). The multi-tenancy
matrix and RAG tests are mandatory on every PR touching services/ or api/.