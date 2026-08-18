# Contextly - RAG Evaluation Report (Phase 13 — conversational multi-turn)

**Reproduce:** `PYTHONPATH=backend python3 -m eval.run_eval --dataset conversational --out eval/reports/conversational-eval.md`
**Embedding:** `lexical-hashed-bigrams` (provider: `fake`) - hermetic lexical proxy; real embeddings are the documented opt-in (`AI_PROVIDER=nvidia|openrouter` + keys, plan D2)
**Top-K:** 6 (docs/rag.md §2 default) · **Queries:** 12 · **Documents:** 5 · **Chunks:** 15

## Summary

| Metric | Value | Gate |
|---|---|---|
| recall@6 (expected document in top-6) | 1.000 | advisory (≥ 0.85) |
| MRR (document) | 0.958 | |
| recall@6 (expected page covered by a chunk) | 1.000 | advisory (≥ 0.85) |
| MRR (page coverage) | 0.861 | |
| Grounding (answer facts in retrieved excerpts) | 1.000 | |
| Answer correctness (rule-based judge, generated answer) | 0.000 | |

> The conversational set is **advisory**: the Phase 13 spec does not gate the exit code on it (SC-001 is a quality target, specs/014-chat-multi-turn-context/spec.md §6).

> Answer correctness reflects the generation provider: the fake provider's canned stub scores ~0 (plumbing only, docs/testing.md §6); real providers score the true answer quality.

## Per-query detail

| # | Raw question | Derived query | Expected | Top-1 | Doc rank | MRR | Page @6 | Flag |
|---|---|---|---|---|---|---|---|---|---|
| 1 | and what condition must the item be in to get the refund? | What is the refund window for returned items? and what condition must the item be in to get the refund? | refund-policy.pdf p3 | refund-policy.pdf p1-4 | 0 | 1.000 | ✅ |  |
| 2 | and what about opened items? | Is there a fee to return unopened items? and what about opened items? | refund-policy.pdf p4 | refund-policy.pdf p1-4 | 0 | 1.000 | ✅ |  |
| 3 | and can gift cards be returned or exchanged? | What items are not refundable? and can gift cards be returned or exchanged? | refund-policy.pdf p5 | refund-policy.pdf p5-9 | 0 | 1.000 | ✅ |  |
| 4 | and where do I submit my request? | How quickly is a refund issued after you inspect the return? and where do I submit my request? | refund-policy.pdf p12 | refund-policy.pdf p1-4 | 0 | 1.000 | ✅ |  |
| 5 | and what about a defect that shows up later? | What happens if my order arrived damaged? and what about a defect that shows up later? | refund-policy.pdf p10 | refund-policy.pdf p10-14 | 0 | 1.000 | ✅ |  |
| 6 | and how fast is standard shipping? | How long after confirmation does an order ship? and how fast is standard shipping? | shipping-policy.pdf p3 | shipping-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 7 | and is free shipping available for international orders? | At what order total does shipping become free? and is free shipping available for international orders? | shipping-policy.pdf p6 | shipping-policy.pdf p6-10 | 0 | 1.000 | ✅ |  |
| 8 | within how many hours must I do it? | Can I change the delivery address after ordering? within how many hours must I do it? | shipping-policy.pdf p8 | shipping-policy.pdf p6-10 | 0 | 1.000 | ✅ |  |
| 9 | and how much paid vacation do new hires accrue in the first year? | How many hours are in the standard workweek? and how much paid vacation do new hires accrue in the first year? | hr-handbook.pdf p4 | hr-handbook.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 10 | and can employment be ended without cause? | How much notice should a resigning employee give? and can employment be ended without cause? | hr-handbook.pdf p2 | hr-handbook.pdf p11-15 | 0 | 1.000 | ✅ |  |
| 11 | and what about unpaid family leave? | How long is paid parental leave for new parents? and what about unpaid family leave? | hr-handbook.pdf p15 | benefits-policy.pdf p6-10 | 1 | 0.500 | ✅ | ⚠️ expected doc not first |
| 12 | and what should I do when I get a suspicious phishing email at work? | How long must work passwords be and what extra step is required? and what should I do when I get a suspicious phishing email at work? | data-security-policy.pdf p3 | data-security-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |

## Diagnostics

Queries where the expected document was not retrieved first, with the top-K documents retrieved instead.

### 11. and what about unpaid family leave?

- Expected: `hr-handbook.pdf` p15 (hard negative: `refund-policy.pdf`)
- doc_rank=1, page_rank=1, mrr=0.500
- Retrieved:

  - `1.` benefits-policy.pdf p6-10 - sim -0.4286 - `'Disability insurance. Short-term disability pays 60% of sala'`
  - `2.` hr-handbook.pdf p11-15 - sim -0.7332 - `'Remote work. Remote arrangements are approved by your manage'`
  - `3.` benefits-policy.pdf p11-13 - sim -0.8076 - `'Commuter benefits. The commuter benefit allows pre-tax deduc'`
  - `4.` hr-handbook.pdf p1-5 - sim -0.8155 - `'Acme Supply Co. - Employee Handbook. Effective January 1, 20'`
  - `5.` hr-handbook.pdf p6-10 - sim -0.9173 - `'Paid holidays. Acme observes 10 company holidays per year, i'`
  - `6.` shipping-policy.pdf p1-5 - sim -0.9688 - `'Acme Supply Co. - Shipping & Delivery Policy. Effective Janu'`


_No hard-negative trap was triggered: the expected document always outranked the similar-topic doc._

## Methodology

- Corpus: `eval/documents/*.pdf` parsed with `app.services.pipeline.parse_pdf` and chunked with `app.services.chunker.chunk_pages` at the locked defaults (chunk 500 tokens / overlap 50 tokens, ~2.4 chars/token - docs/rag.md §2, docs/ingestion.md §4.3).
- Ranking: squared L2 distance over the embeddings (mirroring the product's pgvector `embedding <-> query`, retrieval.py), top-K 6; ties broken deterministically by `(filename, page, chunk_index)`.
- Conversational queries are **referential**: the follow-up alone cannot resolve the referent, so the harness derives the retrieval query from history + question (specs/014-chat-multi-turn-context US1, docs/chat.md §4.1). Hermetic (lexical) mode concatenates the history's user turns with the current question (deterministic stand-in); real providers run the product's `rewrite_question` LLM rewrite with raw-question fallback.
- `recall@6`: expected document present in the top-K chunks (docs/testing.md §6). Page coverage: an expected page lies inside a retrieved chunk's [page_start, page_end] - the chunker merges short pages so page citations are chunk starts (docs/ingestion.md §4.3). The gate requires BOTH variants ≥ threshold: on this 15-chunk corpus doc-level recall@6 sits near the content-blind random baseline (~0.8-0.9) while page coverage drops to ~0.4, so the page variant is what catches broken embedding/retrieval (edge cases).
- Hard negatives are reported but not gated: a hard_negative_document that outranks the expected document is surfaced in the diagnostics.
- Answer metrics run the full pipeline (retrieve → prompt → generate) with the configured provider; the rule-based judge checks `answer_contains` strings case-insensitively (docs/testing.md §6).
