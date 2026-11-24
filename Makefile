.DEFAULT_GOAL := help
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin

.PHONY: help setup up down logs ps migrate revision \
        be-test be-lint be-fmt fe-test fe-lint fe-build check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install backend (venv) and frontend deps locally
	python3 -m venv $(BACKEND)/.venv
	$(PY)/pip install -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm ci

up: ## Start the full stack (postgres, redis, api, worker, frontend)
	docker compose up -d --build

down: ## Stop the stack
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f --tail=100

ps: ## Show service status
	docker compose ps

migrate: ## Apply DB migrations inside the api container
	docker compose exec api alembic upgrade head

revision: ## Create a migration: make revision m="add users"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

be-test: ## Backend tests
	cd $(BACKEND) && .venv/bin/pytest

be-lint: ## Backend lint + type check
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app

be-fmt: ## Backend autoformat
	cd $(BACKEND) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

fe-test: ## Frontend tests
	cd $(FRONTEND) && npm test

fe-lint: ## Frontend lint + type check + format check
	cd $(FRONTEND) && npm run lint && npm run typecheck && npm run format:check

fe-build: ## Frontend production build
	cd $(FRONTEND) && npm run build

check: be-lint be-test fe-lint fe-test fe-build ## Everything CI runs
