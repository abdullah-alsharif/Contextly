# Observability

Lightweight and free: structured JSON logs + counters. No APM, no hosted tracing.

## 1. Logging

- Python `logging` with a JSON formatter; `LOG_LEVEL` env (default `info`, `debug` in dev).
- Every request: one access log with `request_id`, `method`, `path`, `status`,
  `user_id`, `duration_ms`.
- Every async stage: a structured line with stage name, duration, counts
  (e.g. `stage=parse duration_ms=420 pages=12`, `stage=embed chunks=40 ms=3100 tokens=20100`).
- Errors: stack trace at `error` level + `request_id` + user id + provider/status for
  upstream failures. Provider 401s get a distinct `configuration_error` marker.
- Logs stream to stdout/stderr only → platform log collectors (Render logs, Docker,
  Vercel) pick them up for free.

## 2. Metrics (counters in code, no extra infra)

Expose `GET /metrics` as plain-text counters (custom middleware, ~50 lines; no
Prometheus lib needed in MVP). Counters reset with the process — acceptable.

| Metric | Where emitted |
|---|---|
| `api_requests_total{method,path,status}` | middleware |
| `upload_total{status}` / `upload_bytes_total` | documents service |
| `pipeline_stage_duration_ms{stage}` histogram-ish (avg/max/count) | ingestion pipeline |
| `pipeline_documents_total{outcome}` | worker finalize |
| `retrieval_total{found,empty}` + `retrieval_duration_ms` | retrieval service |
| `llm_total{provider,model,stream}` + `llm_tokens_total{in,out}` | AI provider base |
| `errors_total{kind}` | global exception handler |

## 3. What each failure path logs (must-have)

| Failure | Observable via |
|---|---|
| API error | access log + `errors_total` + `detail` message |
| Document processing failure | `pipeline_documents_total{outcome=failed}` + `documents.status_error` in DB + worker log |
| Embedding failure | provider log (provider/model/status) + pipeline stage log |
| Retrieval failure / empty retrieval | `retrieval_total{empty}` + chunk of question logged (debug) |
| LLM failure | `llm_total` + error log with provider/status |
| Retrieval latency | `retrieval_duration_ms` |
| LLM latency | `llm_ms` on message + `llm_total` histogram |
| Token usage | `llm_tokens_total` + per-message `input_tokens/output_tokens` |

## 4. Debugging from the DB alone

Because the worker writes `status_error`, `retry_count`, `lease_until`, and messages
carry `retrieval_ms`/`llm_ms`/tokens, a quick SQL read answers most "what happened"
questions without log spelunking — deliberately, for a one-person ops load.

Since Phase 14, the `action_logs` table (docs/database.md §2.5) adds a
user-visible, RLS-scoped event history: `select … from action_logs where
user_id = '<uid>' order by created_at desc` shows every upload/replace/delete/
reprocess plus pipeline outcomes, with `error_message`/`error_trace` (≤ 8 KB)
on failures — the Logs page is a read over this table (docs/api.md §6).

## 5. Tracing (future, only if needed)

When latency questions become real, add OpenTelemetry spans on retrieval/LLM/pipeline
to the same logs. Not in MVP.