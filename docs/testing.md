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
| 4 | `PATCH /conversations/{A.conv}` with `document_ids=[B.doc]` | 400, selection unchanged |
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

## 7. Frontend tests

- Unit: chat reducer/stream-assembly logic, sources rendering, formatting.
- E2E (Playwright, small): login → upload → wait ready → create conversation →
  select doc → ask → see streaming answer + sources. One happy path + one empty-state path.

## 8. CI

GitHub Actions: backend lint (ruff) + typecheck (mypy) + pytest; frontend
lint/typecheck/build; eval smoke on fixtures (fake provider). The multi-tenancy
matrix and RAG tests are mandatory on every PR touching services/ or api/.