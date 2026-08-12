# Contextly

Multi-tenant AI document platform: upload PDFs, get grounded answers with verifiable
sources. RAG chat with streaming, citations, and source excerpts.

**Stack**: Next.js 14 (App Router) · FastAPI · PostgreSQL 16 + pgvector · Docker Compose.

## First run (3 commands)

Requires Docker with Compose v2. No accounts, keys, or credentials needed.

```bash
cp .env.example .env          # defaults are dev-safe
docker compose up --build     # db :5432 · backend :8000 · frontend :3000
docker compose exec backend python -m app.migrate   # apply migrations
```

## Verify

```bash
curl -s localhost:8000/healthz   # 200 {"status":"ok","checks":{"database":true,"ai_provider":true}}
curl -s localhost:8000/          # hello-world JSON
open http://localhost:3000       # Phase 0 shell
```

## Makefile cheat sheet

```bash
make up        # docker compose up --build -d
make down      # docker compose down
make logs      # docker compose logs -f
make migrate   # apply numbered SQL migrations in infrastructure/migrations/
make test      # backend pytest (in container)
make lint      # ruff + mypy (backend) · tsc + eslint (frontend)
```

## Dev-mode behaviors

| Concern | Dev behavior |
|---|---|
| Auth | `AUTH_MODE=dev` — dev token issuer, no Supabase needed (JWT verification disabled) |
| Storage | `STORAGE_PROVIDER=local` → `./data/storage/{user_id}/…` (volume `storage-data` mounted at `/data/storage`) |
| AI | `AI_PROVIDER=fake` — deterministic, offline; hash-based embeddings + canned answers |
| Real-mode smoke test | set `AI_PROVIDER=nvidia` / `STORAGE_PROVIDER=supabase` with real keys in `.env` — same code path |

Real values are never committed. `.env` and `data/` are gitignored.

## Production ($0 stack)

Deploy to Vercel + Render + Supabase with a real AI provider — accounts, credentials,
and step-by-step instructions in **[docs/deployment-walkthrough.md](docs/deployment-walkthrough.md)**.
Condensed operator runbook + post-deploy verification checklist:
[docs/deployment.md §9-10](docs/deployment.md).

## Remapping host ports

Compose maps host → container ports in `docker-compose.yml` (`5432:5432` db, `8000:8000`
backend, `3000:3000` frontend). To free a busy host port, edit the left side of the
mapping, e.g. `ports: ["5433:5432"]` for db or `ports: ["8080:8000"]` for backend, then
align the env values that reference the port (`.env`, no compose edits needed):

| Remapped service | Also update in `.env` |
|---|---|
| db (`5432` → `5433`) | `DATABASE_URL=postgresql://contextly:contextly@db:5433/contextly` |
| backend (`8000` → `8080`) | `CORS_ORIGINS=http://localhost:8080` and `NEXT_PUBLIC_BACKEND_URL=http://localhost:8080` |
| frontend (`3000` → `3100`) | open `http://localhost:3100`; no env change required |

Service-to-service traffic inside the compose network is unaffected (containers always
reach each other on the container port).

## CI

Push / PR runs `.github/workflows/ci.yml`: backend (ruff + mypy + pytest against a
Postgres 16 service container) and frontend (tsc + eslint + next build), fail fast.

## Database (Phase 1)

`make migrate` now creates the full application schema (profiles, documents,
document_chunks with `vector(1024)` + HNSW index, conversations, conversation_documents,
messages) from `infrastructure/migrations/0001_init.sql` — plain reviewed SQL, no ORM
magic.

Tenant isolation is enforced at the database by Row Level Security on every tenant table
(see `docs/multi-tenancy.md`). Runtime queries must connect as the `contextly_app` role
(LOGIN, no `BYPASSRLS`); the compose `db` user is a superuser and bypasses RLS, so it is
only for migrations/admin. Contract: `specs/002-database-schema/contracts/database.md`.

## Repo layout

```
backend/       FastAPI app (backend/app), tests, Dockerfile
frontend/      Next.js App Router (frontend/app), components, lib
infrastructure/ migrations (numbered SQL) + docker fragments
eval/          RAG evaluation datasets + fixtures (populated in Phase 10)
docs/ designs/ blueprint and design source material
```
