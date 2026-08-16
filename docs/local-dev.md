# Local Development

## 1. Principles

- Start everything with one command.
- Zero-cost and offline-friendly: no AI/storage credentials required for dev/tests
  (`fake` provider + `local` storage).
- Production-like structure: backend, frontend, Postgres+pgvector in containers.

## 2. Repository structure

```
contextly/
├── frontend/                      # Next.js 14+ (App Router, TS, Tailwind)
│   ├── app/
│   │   ├── (auth)/login/register
│   │   ├── (app)/dashboard/documents/chat/settings
│   │   └── api/                   # server-side proxy routes (auth, backend calls)
│   ├── components/                # chat, upload, sources, sidebar…
│   ├── lib/                       # api client, session helpers
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app, CORS, middleware, routers
│   │   ├── api/                   # routers: auth, documents, conversations, messages
│   │   ├── core/                  # config, security (JWT), errors, rate limiting
│   │   ├── db/                    # engine, session, migrations hooks
│   │   ├── providers/             # ai/ (ai_provider.py, nvidia.py, openrouter.py, fake.py)
│   │   │                          # storage/ (storage_provider.py, supabase.py, local.py, s3.py)
│   │   ├── services/              # documents.py (pipeline), retrieval.py, chat.py, workers.py
│   │   └── schemas/               # pydantic request/response models
│   ├── tests/                     # unit + integration + security matrix
│   ├── worker.py                  # DB-backed worker entrypoint (python -m app.worker)
│   ├── pyproject.toml / requirements.txt / requirements.lock
│   └── Dockerfile
├── eval/                          # RAG evaluation dataset + harness
│   ├── datasets/                  # qa pairs, expected sources
│   ├── documents/                 # seed PDFs (fixtures)
│   └── run_eval.py
├── designs/                        # UI design source material (from external design export)
│   ├── design-system.md            # raw token spec (reference only)
│   └── prototypes/                 # chat.html + dashboard.html interactive references
├── infrastructure/
│   ├── migrations/                # numbered SQL files
│   └── docker/                    # compose fragments, healthchecks
├── docs/                          # this blueprint
├── docker-compose.yml
├── .env.example
└── README.md
```

## 3. Docker Compose (dev)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: contextly
      POSTGRES_PASSWORD: contextly
      POSTGRES_DB: contextly
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U contextly"]
      interval: 2s
      timeout: 2s
      retries: 10

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://contextly:contextly@db:5432/contextly
      AI_PROVIDER: fake
      STORAGE_PROVIDER: local
      LOCAL_STORAGE_DIR: /data/storage
      AUTH_MODE: dev                    # dev token issuer; JWT verification disabled
      CORS_ORIGINS: http://localhost:3000
    volumes:
      - ./backend:/app
      - storage-data:/data/storage
    ports: ["8000:8000"]
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    depends_on:
      db: {condition: service_healthy}

  worker:
    build: ./backend
    environment: *backend-env             # same env
    command: python -m app.worker
    depends_on:
      db: {condition: service_healthy}

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_BACKEND_URL: http://localhost:8000
    ports: ["3000:3000"]
    depends_on: [backend]

volumes:
  storage-data:
```

**Dev auth mode:** `AUTH_MODE=dev` issues a dev JWT (any user id) so the whole stack
runs without Supabase. Production switches to real JWT verification via env — one code
path (a `get_current_user` dependency that delegates to `DevAuthenticator` or
`SupabaseJWTVerifier`).

**DATABASE_URL scheme:** the env surface uses the plain `postgresql://` scheme
(no `+asyncpg` dialect suffix) — it is consumed directly by the sync psycopg
migrations runner and health probe (`backend/app/migrate.py`, `backend/app/main.py`).
The async SQLAlchemy engine in Phase 1 derives its `postgresql+asyncpg://` dialect at
the engine layer from the same `DATABASE_URL`; the env var keeps a single scheme.

## 4. First run (3 commands)

```bash
cp .env.example .env            # defaults are dev-safe
docker compose up --build
# → backend on :8000, frontend on :3000, db on :5432
docker compose exec backend python -m app.migrate   # apply migrations
```

## 5. Dev without Supabase

| Concern | Dev behavior |
|---|---|
| Auth | dev JWT; `/auth/me` returns a seeded profile |
| Storage | `LocalStorageProvider` → `./data/storage/{user_id}/…` |
| AI | `FakeProvider`: hash-based deterministic embeddings + canned RAG answers |
| Real-mode smoke test | set `AI_PROVIDER=nvidia`, `STORAGE_PROVIDER=supabase`, real keys in `.env` — same code path |

## 6. Optional but recommended

- `Makefile`: `make up`, `make migrate`, `make test`, `make lint`, `make eval`.
- `pre-commit`: ruff + mypy + tsc quick checks.
- A `scripts/seed_eval.sh` that loads the eval PDFs into a dev user so the demo data is one command.