.DEFAULT_GOAL := help
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin

.PHONY: help setup up down logs ps migrate revision seed \
        be-lint be-fmt fe-lock fe-lint fe-build check \
        prod-up prod-down prod-logs

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

seed: ## Create demo buyer + 4 suppliers (password: Demo@12345)
	docker compose exec -T api python -m app.cli.seed

be-lint: ## Backend lint + type check
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app

be-fmt: ## Backend autoformat
	cd $(BACKEND) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

fe-lock: ## Regenerate package-lock.json with the Docker image's npm (run after adding deps)
	docker run --rm -v "$(CURDIR)/$(FRONTEND):/app" -w /app node:24-alpine \
		npm install --package-lock-only --no-audit --no-fund

fe-lint: ## Frontend lint + type check + format check
	cd $(FRONTEND) && npm run lint && npm run typecheck && npm run format:check

fe-build: ## Frontend production build
	cd $(FRONTEND) && npm run build

check: be-lint fe-lint fe-build ## Lint, type-check and build (what CI runs)

# ---------------------------------------------------------------- production-style stack
PROD := docker compose -f docker-compose.prod.yml --env-file .env.prod

prod-up: ## Build + start the production stack (Nginx on :8088). Needs .env.prod
	@test -f .env.prod || (echo "Create .env.prod from .env.prod.example first" && exit 1)
	$(PROD) up -d --build --wait

prod-down: ## Stop the production stack
	$(PROD) down

prod-logs: ## Tail production logs
	$(PROD) logs -f --tail=100
