# Contextly — AGENTS.md

Auto-loaded at session start. Read the pointers below and in the linked docs before
taking any action.

## Project

Contextly is a multi-tenant AI document platform: upload PDFs → async ingestion →
chunking → embeddings → pgvector → RAG chat with streaming answers + source citations.

Stack (locked, see `docs/README.md` for the full decisions table):
- Next.js + TypeScript + Tailwind (frontend)
- FastAPI + Python (backend + DB-backed worker)
- PostgreSQL + pgvector (Supabase hosted or self-hosted)
- Supabase Auth + Storage (MVP), behind `AIProvider` / `StorageProvider` abstractions
- NVIDIA NIM default AI provider (switch via `AI_PROVIDER`)

## Source of truth (read before implementing)

- `docs/README.md` — document map and locked MVP decisions
- `docs/architecture.md`, `docs/database.md`, `docs/api.md` — system/schema/API specs
- `docs/multi-tenancy.md`, `docs/security.md` — RLS + ownership rules (non-negotiable)
- `docs/ingestion.md`, `docs/rag.md`, `docs/chat.md` — pipelines and their defaults
- `docs/local-dev.md` — repo structure + docker-compose layout
- `docs/roadmap.md` — phases 0–12; each phase has a definition of done. Work one phase at a time.

## Workflow (spec-driven)

Run the `/speckit.*` commands for this project (`constitution`, `specify`, `plan`,
`tasks`, `implement`, `converge`). Specs and tasks live in the project workspace
(`specs/`, managed by spec-kit). Cite `docs/*.md` as the architectural source of
truth when writing specs/plans.

Local tools: `specify` CLI (v0.12.2) installed via uv.

## Design

UI must follow the design system in `docs/frontend-design.md`. Reference UIs:
`designs/prototypes/chat.html` and `designs/prototypes/dashboard.html`. Token spec:
`designs/design-system.md`. Relevant skills: `frontend-design`,
`codebase-design`, `supabase`, `supabase-postgres-best-practices`.

## Local state (do not commit)

These are gitignored and live only on this machine, even though tools use them:
- `.agents/skills/` — installed skill definitions
- `.opencode/commands/` — spec-kit `/speckit.*` commands
- `.specify/` — spec-kit project state
- `skills-lock.json`

## Getting started

```bash
make up        # docker compose: db + migrations + backend + worker + frontend
make migrate   # apply infrastructure/migrations
make test      # backend pytest
```

Current task: **Phase 11** (production deployment, $0 stack) per `docs/roadmap.md` —
spec/plan/tasks in `specs/012-production-deployment/`. Committed `render.yaml` (web
service + worker, `/healthz` health check, migrations as `preDeployCommand`),
deploy-blocker guards (`MIGRATION_DATABASE_URL`, `STORAGE_PROVIDER=local` rejected
outside dev, `LOG_LEVEL`), Vercel frontend env (`NEXT_PUBLIC_*`), runbook + verification
checklist in `docs/deployment.md §9-10`, and the credential walkthrough in
`docs/deployment-walkthrough.md`. Credential-bound steps (T012-T024) need Supabase/
Render/Vercel/NVIDIA or OpenRouter; tuning is Phase 12.