# Security Model

Priorities for a portfolio project: **correct tenant isolation**, safe file handling,
defensible auth, and prompt-injection mitigation. Everything else is proportionate
(e.g. no OAuth SSO, no fancy key rotation).

## 1. Authentication & sessions

- Supabase GoTrue issues JWTs; backend validates **signature + expiry + issuer + audience**
  on every request (cached JWKS, no per-request network call).
- JWT `sub` = user uuid = `profiles.id`; all tenant scoping derives from it.
- Sessions are Supabase-managed (refresh tokens in httpOnly cookies via the frontend
  server). Backend never stores session state — stateless JWT validation keeps the API
  horizontally scale-free.
- Profiles bootstrap: on first `/auth/me`, create `profiles` row if missing (upsert).

## 2. Authorization

- Every endpoint resolves its resource through an owner chain:
  `document` → `user_id = sub`; `conversation` → `user_id = sub`;
  `message` → via conversation → user.
- Ownership failure → `404` (anti-enumeration).
- Cross-resource moves are forbidden: you cannot attach another user's document to
  your conversation (validated in the PATCH/POST handler and blocked by RLS check).
- Multi-tenancy at the DB: see [multi-tenancy.md](multi-tenancy.md) — RLS is the
  enforced boundary; query filters are the audit trail.

## 3. File uploads

| Threat | Control |
|---|---|
| Wrong file type | content-type + extension check (`.pdf` only); re-check magic bytes (`%PDF-`) |
| Oversized files | 10 MB cap pre-upload; storage policy hard cap; streaming read into memory with `Content-Length` check |
| Malicious/parsing payloads | parse with `pypdf` in an isolated worker step; never render HTML/JS from document text; text is HTML-escaped in the UI |
| Path traversal in filename | client filename never enters the object key; key = `{user_id}/docs/{document_id}.pdf`; sanitize display name (strip control chars) |
| Direct object access | no public bucket; signed URLs 5 min; storage policy restricts by folder = user id |
| Malware/zip bombs | not applicable (PDF only, size capped, text-only extraction) — note as accepted risk |

## 4. RAG security

- **Prompt injection via documents:** retrieved content is delimited and marked
  untrusted; system prompt says to ignore instructions inside excerpts. This is
  mitigation, not a guarantee — documented as accepted residual risk (chat only
  surfaces *text*, never executed).
- **Data leakage / cross-user retrieval:** enforced by (a) retrieval SQL filters
  (user + conversation documents), (b) RLS, (c) test matrix. Defense in depth, not a
  single check.
- **Malicious document content:** output is plain text to the chat UI; rendering escapes
  HTML. No markdown-to-HTML with raw injection.
- **LLM instruction conflicts:** system prompt is appended after user context so
  system rules win tiebreaks; question length capped (4000 chars).

## 5. API security

| Concern | Measure |
|---|---|
| Rate limiting | in-process token bucket per user id (e.g. 30 req/min chat, 120 req/min general); `slowapi` or hand-rolled dependency; `429` with `Retry-After` |
| CORS | allowlist from env; credentials only for the frontend origin |
| Input validation | Pydantic schemas everywhere; `content` length caps; enum checks on `status`; uuid parsing |
| SQL injection | parameterized queries / ORM only (SQLAlchemy); retrieval SQL uses bind params |
| Secrets | env-only; `.env.example` with no real values; never logged; CI secrets in GitHub Actions |
| API abuse | 10 MB upload cap, signed URL expiry, no public endpoints besides auth/me-style health |
| Security headers | CSP, X-Content-Type-Options, frame-ancestors on the frontend |
| Audit | request id per request; user id logged (not PII beyond email where needed) |

## 6. Secrets inventory

| Env var | Purpose |
|---|---|
| `AUTH_MODE` | `dev` (well-known secret) or `supabase` (JWT validation). Dev mode only allowed when `APP_ENV=dev` (startup guard) |
| `DEV_JWT_SECRET` | dev-mode JWT signing secret (well-known default `contextly-dev-secret-0123456789abcdef`, env-overridable; never a real secret) |
| `SUPABASE_URL` | JWT issuer (`.auth/v1` suffix derived at startup); required for Supabase auth mode |
| `SUPABASE_JWT_SECRET` | HS256 JWT validation (legacy Supabase tokens); at least one of secret or JWKS URL required |
| `SUPABASE_JWKS_URL` | RS256 JWKS endpoint (default derived from `SUPABASE_URL`); fetched and cached (300s) |
| `JWT_LEEWAY_SECONDS` | clock-skew leeway for JWT validation (default 30) |
| `SUPABASE_SERVICE_ROLE_KEY` | storage uploads + deletes from the backend (API + worker) — never in frontend |
| `DATABASE_URL` | Postgres (runtime role, RLS-respecting) |
| `NVIDIA_API_KEY` / `OPENROUTER_API_KEY` | AI provider (one per selected provider) |
| `STORAGE_PROVIDER`, `AI_PROVIDER` | module selection (`local`/`supabase`, `fake`/`nvidia`/`openrouter`) |
| `STORAGE_BUCKET` | Supabase storage bucket name (default `documents`) |
| `UPLOAD_MAX_BYTES` | per-file upload cap enforced in the API before processing (default 10485760) |

## 7. Accepted risks (documented, not ignored)

1. Prompt injection is mitigated but not eliminated (inherent to RAG).
2. Rate limiting is per-process (fine for single worker; revisit when multi-process).
3. `pypdf` is not a hardened parser (PDF-only + size caps + no execution surface).
4. No SSO/2FA — out of scope for portfolio.
5. Service-role key exists; it must never appear in the Next.js client bundle.