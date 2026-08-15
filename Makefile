.PHONY: up down logs migrate test eval eval-sweep lint smoke check

# Prefer the backend venv (backend/.venv) when present; fall back to a system
# python3 that must have backend + ruff deps installed (see `eval` below).
PYTHON ?= $(shell [ -x backend/.venv/bin/python ] && echo backend/.venv/bin/python || echo python3)

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
	# backend/requirements.txt`).
	APP_ENV=dev AI_PROVIDER=fake PYTHONPATH=backend $(PYTHON) -m eval.run_eval --out eval/reports/rag-eval.md && \
	APP_ENV=dev AI_PROVIDER=fake PYTHONPATH=backend $(PYTHON) -m pytest eval/tests -q

eval-sweep: ## Phase 12 RAG parameter sweep (docs/rag.md §2 grid, hermetic) + sweep tests
	# Measurement-only: never touches eval/reports/rag-eval.md (baseline guard,
	# docs/tuning.md). Same local-deps requirement as `eval`.
	PYTHONPATH=backend $(PYTHON) -m eval.sweep --out eval/reports/tuning-sweep.md && \
	PYTHONPATH=backend $(PYTHON) -m pytest eval/tests/test_sweep.py -q

lint: ## Backend: ruff + mypy · Frontend: tsc + eslint (mirrors CI scope)
	docker compose exec backend ruff check app tests
	docker compose exec backend mypy app
	docker compose exec frontend npx tsc --noEmit
	docker compose exec frontend npx eslint .

smoke: ## Playwright smoke on the full stack (needs db+backend+worker up)
	# Runs on the host (playwright.config.ts spawns `npm run dev` on :3000).
	# The compose frontend container also binds :3000, so it is parked for the
	# run and restored afterwards; a stopped frontend stays stopped. First run
	# needs browsers: `cd frontend && npm run smoke:install`.
	@frontend_up=$$(docker compose ps -q frontend); \
	if [ -n "$$frontend_up" ]; then docker compose stop frontend; fi; \
	cd frontend && npm run smoke; status=$$?; \
	if [ -n "$$frontend_up" ]; then docker compose start frontend; fi; \
	exit $$status

check: ## Local CI gate (mirrors .github/workflows/ci.yml) + every script
	# Backend steps run in the compose backend container (DB-gated pytest +
	# security matrix, like CI's postgres service); eval and frontend steps run
	# on the host. Brings up db/backend/worker itself and leaves them running.
	# Covers: ruff/mypy/migrate/pytest/matrix, eval, eval-sweep, tsc, eslint,
	# security:check, next build, and the Playwright smoke (via `smoke`).
	docker compose up -d db backend worker
	docker compose exec backend ruff check app tests
	docker compose exec backend mypy app
	docker compose exec backend python -m app.migrate
	docker compose exec backend pytest -q
	docker compose exec backend sh -c 'count=$$(pytest tests/security/test_multi_tenancy_matrix.py --collect-only -q | grep -c "::"); echo "security matrix tests collected: $$count"; test "$$count" = "10" && pytest tests/security/test_multi_tenancy_matrix.py -q'
	APP_ENV=dev AI_PROVIDER=fake $(PYTHON) -m ruff check --config backend/pyproject.toml eval
	APP_ENV=dev AI_PROVIDER=fake PYTHONPATH=backend $(PYTHON) -m eval.run_eval --out eval/reports/rag-eval.md
	APP_ENV=dev AI_PROVIDER=fake PYTHONPATH=backend $(PYTHON) -m pytest eval/tests -q
	$(MAKE) eval-sweep
	cd frontend && npx tsc --noEmit
	cd frontend && npx eslint .
	cd frontend && npm run security:check
	cd frontend && npx next build
	$(MAKE) smoke