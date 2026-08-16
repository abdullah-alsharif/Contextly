# Contextly - RAG Evaluation Report (Phase 10)

**Reproduce:** `PYTHONPATH=backend python3 -m eval.run_eval --out eval/reports/rag-eval.md`
**Embedding:** `lexical-hashed-bigrams` (provider: `fake`) - hermetic lexical proxy; real embeddings are the documented opt-in (`AI_PROVIDER=nvidia|openrouter` + keys, plan D2)
**Top-K:** 6 (docs/rag.md §2 default) · **Queries:** 60 · **Documents:** 5 · **Chunks:** 14

## Summary

| Metric | Value | Gate |
|---|---|---|
| recall@6 (expected document in top-6) | 1.000 | **PASS** (≥ 0.85) |
| MRR (document) | 0.992 | |
| recall@6 (expected page covered by a chunk) | 1.000 | **PASS** (≥ 0.85) |
| MRR (page coverage) | 0.978 | |
| Grounding (answer facts in retrieved excerpts) | 1.000 | |
| Answer correctness (rule-based judge, generated answer) | 0.033 | |

> Answer correctness reflects the generation provider: the fake provider's canned stub scores ~0 (plumbing only, docs/testing.md §6); real providers score the true answer quality.

## Per-query detail

| # | Query | Expected | Top-1 | Doc rank | MRR | Page @6 | Flag |
|---|---|---|---|---|---|---|---|
| 1 | What is the refund window for returned items? | refund-policy.pdf p2 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 2 | Do refund requests submitted after 30 days get declined? | refund-policy.pdf p2 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 3 | What condition must a returned item be in to get a refund? | refund-policy.pdf p3 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 4 | Is there a fee for returning opened items? | refund-policy.pdf p4 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 5 | Is there a fee to return unopened items? | refund-policy.pdf p4 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 6 | What items are not refundable? | refund-policy.pdf p5 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 7 | Can gift cards be returned or exchanged? | refund-policy.pdf p5 | refund-policy.pdf p1-5 | 0 | 1.000 | ✅ |  |
| 8 | Which payment method do refunds go back to? | refund-policy.pdf p6 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 9 | What do I get if I return an item without a receipt? | refund-policy.pdf p6 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 10 | How quickly is a refund issued after you inspect the return? | refund-policy.pdf p7 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 11 | Do you provide a return shipping label? | refund-policy.pdf p8 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 12 | What does a gift recipient receive for a returned gift? | refund-policy.pdf p9 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 13 | How long does the limited warranty cover defects? | refund-policy.pdf p10 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 14 | What happens if my order arrived damaged? | refund-policy.pdf p11 | refund-policy.pdf p6-11 | 0 | 1.000 | ✅ |  |
| 15 | Where do I submit a refund request? | refund-policy.pdf p12 | refund-policy.pdf p12-14 | 0 | 1.000 | ✅ |  |
| 16 | What happens if I file a chargeback with my credit card company? | refund-policy.pdf p13 | refund-policy.pdf p12-14 | 0 | 1.000 | ✅ |  |
| 17 | Which refund policy version applies to my order? | refund-policy.pdf p14 | refund-policy.pdf p12-14 | 0 | 1.000 | ✅ |  |
| 18 | How long after confirmation does an order ship? | shipping-policy.pdf p2 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 19 | How fast is standard shipping within the United States? | shipping-policy.pdf p3 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 20 | Until what time must I order to get next-day express delivery? | shipping-policy.pdf p4 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 21 | How long does international delivery take? | shipping-policy.pdf p5 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 22 | At what order total does shipping become free? | shipping-policy.pdf p6 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 23 | Is free shipping available for international orders? | shipping-policy.pdf p6 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 24 | How do I find the tracking number for my order? | shipping-policy.pdf p7 | shipping-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 25 | Can I change the delivery address after ordering? | shipping-policy.pdf p8 | shipping-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 26 | How many delivery attempts does the carrier make? | shipping-policy.pdf p9 | shipping-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 27 | Do orders above a certain value require a signature? | shipping-policy.pdf p10 | shipping-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 28 | Can P.O. boxes get express delivery? | shipping-policy.pdf p11 | shipping-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 29 | What should I do if my package has not arrived? | shipping-policy.pdf p12 | shipping-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 30 | How much shipping insurance is included with a package? | shipping-policy.pdf p13 | shipping-policy.pdf p13-14 | 0 | 1.000 | ✅ |  |
| 31 | Which version of the shipping policy applies to my order? | shipping-policy.pdf p14 | shipping-policy.pdf p13-14 | 0 | 1.000 | ✅ |  |
| 32 | Can employment at Acme be ended without cause? | hr-handbook.pdf p2 | hr-handbook.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 33 | How many hours are in the standard workweek? | hr-handbook.pdf p3 | hr-handbook.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 34 | How much paid vacation do new hires accrue in the first year? | hr-handbook.pdf p4 | hr-handbook.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 35 | How many paid sick days do employees get per year? | hr-handbook.pdf p5 | hr-handbook.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 36 | How many company holidays does Acme observe each year? | hr-handbook.pdf p6 | hr-handbook.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 37 | How many days of employment must pass before health coverage begins? | hr-handbook.pdf p7 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 38 | What is the company match on the 401(k) plan? | hr-handbook.pdf p8 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 39 | How soon must I file an expense report after a business expense? | hr-handbook.pdf p9 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 40 | Who should I contact if I experience harassment at work? | hr-handbook.pdf p10 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 41 | What security controls do remote employees have to keep? | hr-handbook.pdf p11 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 42 | How often are performance reviews held? | hr-handbook.pdf p12 | hr-handbook.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 43 | How much notice should a resigning employee give? | hr-handbook.pdf p13 | hr-handbook.pdf p13-16 | 0 | 1.000 | ✅ |  |
| 44 | What are employees barred from disclosing? | hr-handbook.pdf p14 | hr-handbook.pdf p13-16 | 0 | 1.000 | ✅ |  |
| 45 | How many weeks of unpaid family leave are available? | hr-handbook.pdf p15 | hr-handbook.pdf p13-16 | 0 | 1.000 | ✅ |  |
| 46 | Who answers benefits questions? | hr-handbook.pdf p16 | benefits-policy.pdf p13 | 1 | 0.500 | ✅ | ⚠️ expected doc not first |
| 47 | What is the deductible on the PPO health plan? | benefits-policy.pdf p2 | benefits-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 48 | Is orthodontia for dependents covered under dental? | benefits-policy.pdf p3 | benefits-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 49 | How often is a vision eye exam covered? | benefits-policy.pdf p4 | benefits-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 50 | How much life insurance does Acme pay for full-time employees? | benefits-policy.pdf p5 | benefits-policy.pdf p1-6 | 0 | 1.000 | ✅ |  |
| 51 | How much can I set aside in a health care FSA? | benefits-policy.pdf p7 | benefits-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 52 | How long is paid parental leave for new parents? | benefits-policy.pdf p8 | benefits-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 53 | What is the annual wellness stipend amount? | benefits-policy.pdf p9 | benefits-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 54 | How much tuition does Acme reimburse per year? | benefits-policy.pdf p10 | benefits-policy.pdf p7-12 | 0 | 1.000 | ✅ |  |
| 55 | How long must work passwords be and what extra step is required? | data-security-policy.pdf p2 | data-security-policy.pdf p1-8 | 0 | 1.000 | ✅ |  |
| 56 | What should I do when I get a suspicious phishing email at work? | data-security-policy.pdf p3 | data-security-policy.pdf p1-8 | 0 | 1.000 | ✅ |  |
| 57 | What encryption does Acme require on company laptops? | data-security-policy.pdf p4 | data-security-policy.pdf p1-8 | 0 | 1.000 | ✅ |  |
| 58 | How quickly must a suspected breach be reported? | data-security-policy.pdf p7 | data-security-policy.pdf p1-8 | 0 | 1.000 | ✅ |  |
| 59 | What must vendors sign before accessing Acme data? | data-security-policy.pdf p9 | data-security-policy.pdf p9-10 | 0 | 1.000 | ✅ |  |
| 60 | What is required for remote access to company systems? | data-security-policy.pdf p6 | data-security-policy.pdf p1-8 | 0 | 1.000 | ✅ |  |

## Diagnostics

Queries where the expected document was not retrieved first, with the top-K documents retrieved instead.

### 46. Who answers benefits questions?

- Expected: `hr-handbook.pdf` p16 (hard negative: `refund-policy.pdf`)
- doc_rank=1, page_rank=1, mrr=0.500
- Retrieved:

  - `1.` benefits-policy.pdf p13 - sim -0.6054 - `'Plan changes. Benefits change during annual open enrollment,'`
  - `2.` hr-handbook.pdf p13-16 - sim -0.7451 - `'Notice of resignation. Employees who resign voluntarily are '`
  - `3.` data-security-policy.pdf p9-10 - sim -0.9005 - `'Third parties. Vendors must sign a data processing agreement'`
  - `4.` refund-policy.pdf p12-14 - sim -0.9232 - `'How to request a refund. Open the Acme Support portal and ch'`
  - `5.` benefits-policy.pdf p1-6 - sim -0.9409 - `'Acme Supply Co. Benefits Program. Effective January 1, 2026.'`
  - `6.` hr-handbook.pdf p1-6 - sim -0.9671 - `'Acme Supply Co. - Employee Handbook. Effective January 1, 20'`


_No hard-negative trap was triggered: the expected document always outranked the similar-topic doc._

## Methodology

- Corpus: `eval/documents/*.pdf` parsed with `app.services.pipeline.parse_pdf` and chunked with `app.services.chunker.chunk_pages` at the locked defaults (chunk 500 tokens / overlap 50 tokens, ~2.4 chars/token - docs/rag.md §2, docs/ingestion.md §4.3).
- Ranking: squared L2 distance over the embeddings (mirroring the product's pgvector `embedding <-> query`, retrieval.py), top-K 6; ties broken deterministically by `(filename, page, chunk_index)`.
- `recall@6`: expected document present in the top-K chunks (docs/testing.md §6). Page coverage: an expected page lies inside a retrieved chunk's [page_start, page_end] - the chunker merges short pages so page citations are chunk starts (docs/ingestion.md §4.3). The gate requires BOTH variants ≥ threshold: on this 15-chunk corpus doc-level recall@6 sits near the content-blind random baseline (~0.8-0.9) while page coverage drops to ~0.4, so the page variant is what catches broken embedding/retrieval (edge cases).
- Hard negatives are reported but not gated: a hard_negative_document that outranks the expected document is surfaced in the diagnostics.
- Answer metrics run the full pipeline (retrieve → prompt → generate) with the configured provider; the rule-based judge checks `answer_contains` strings case-insensitively (docs/testing.md §6).
