.PHONY: up down logs migrate test lint

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

lint: ## Backend: ruff + mypy · Frontend: tsc + eslint
	docker compose exec backend ruff check app
	docker compose exec backend mypy app
	docker compose exec frontend npx tsc --noEmit
	docker compose exec frontend npx eslint .
