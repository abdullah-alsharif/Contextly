.PHONY: up down logs migrate test eval eval-sweep lint

PYTHON ?= python3

up: ## Bring up db, backend, worker, frontend
	docker compose up --build -d

down: ## Tear everything down
	docker compose down

logs: ## Tail compose logs
	docker compose logs -f

migrate: ## Apply numbered SQL migrations
	docker compose exec backend python -m app.migrate

test: ## Backend pytest (in container)
	docker compose exec backend pytest

eval: ## Phase 10 RAG eval (headless, hermetic, fake provider) + eval unit tests
	# Offline harness: no DB/UI needed (docs/testing.md §6). Requires backend
	# deps locally (e.g. `backend/.venv/bin/python` or `pip install -r
	# backend/requirements.txt`): PYTHON ?= python3 here.
	PYTHONPATH=backend $(PYTHON) -m eval.run_eval --out eval/reports/rag-eval.md && \
	PYTHONPATH=backend $(PYTHON) -m pytest eval/tests -q

eval-sweep: ## Phase 12 RAG parameter sweep (docs/rag.md §2 grid, hermetic) + sweep tests
	# Measurement-only: never touches eval/reports/rag-eval.md (baseline guard,
	# docs/tuning.md). Same local-deps requirement as `eval`.
	PYTHONPATH=backend $(PYTHON) -m eval.sweep --out eval/reports/tuning-sweep.md && \
	PYTHONPATH=backend $(PYTHON) -m pytest eval/tests/test_sweep.py -q

lint: ## Backend: ruff + mypy · Frontend: tsc + eslint
	docker compose exec backend ruff check app
	docker compose exec backend mypy app
	docker compose exec frontend npx tsc --noEmit
	docker compose exec frontend npx eslint .
