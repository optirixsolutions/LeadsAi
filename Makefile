# Developer commands. On Windows, run via Git Bash or WSL (`make` is not built into PowerShell);
# the equivalent raw commands are listed in README.md.

API := apps/api
WEB := apps/web

.PHONY: setup infra infra-down migrate api web dev test test-api test-web e2e lint typecheck check contracts audit docker-up

setup:            ## Install all dependencies
	cd $(API) && uv sync
	pnpm install
	cd $(WEB) && pnpm exec playwright install chromium

infra:            ## Start Postgres and Redis
	docker compose up -d --wait postgres redis

infra-down:
	docker compose down

migrate:          ## Apply database migrations
	cd $(API) && uv run alembic upgrade head

api:              ## Run the API with reload
	cd $(API) && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

web:              ## Run the web app in dev mode
	pnpm --filter @salesiq/web dev

test: test-api test-web

test-api:
	cd $(API) && uv run pytest -q

test-web:
	pnpm --filter @salesiq/web test

e2e:              ## Requires `pnpm --filter @salesiq/web build` first
	pnpm --filter @salesiq/web test:e2e

lint:
	cd $(API) && uv run ruff check . && uv run ruff format --check .
	pnpm -r lint

typecheck:
	cd $(API) && uv run mypy
	pnpm -r typecheck

contracts:        ## Regenerate TS types from the API OpenAPI schema
	pnpm contracts:generate

audit:            ## Dependency vulnerability scan
	cd $(API) && uv run pip-audit
	pnpm audit --prod

check: lint typecheck test
	pnpm --filter @salesiq/contracts test

docker-up:        ## Full stack in containers
	docker compose --profile app up -d --build
