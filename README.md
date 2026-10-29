# SalesIQ

Evidence-driven revenue intelligence and sales automation platform.

> Status: foundation (Phase 1). See [docs/IMPLEMENTATION_ROADMAP.md](docs/IMPLEMENTATION_ROADMAP.md).

## Prerequisites
- Docker with Compose v2
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20.9+ and pnpm 10 (`corepack enable`)

## Quick start
```bash
cp .env.example .env
docker compose up -d --wait postgres redis
cd apps/api && uv sync && uv run alembic upgrade head && cd ../..
pnpm install
```

Run the API and web app in two terminals:
```bash
cd apps/api && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
```bash
pnpm --filter @salesiq/web dev
```

- Web: http://localhost:3000
- API docs: http://127.0.0.1:8000/api/docs
- Readiness: http://127.0.0.1:8000/api/v1/health/ready

Full stack in containers: `docker compose --profile app up -d --build`, then
`docker compose run --rm api .venv/bin/alembic upgrade head`.

## Checks
```bash
cd apps/api && uv run ruff check . && uv run mypy && uv run pytest -q
```
```bash
pnpm -r lint && pnpm -r typecheck && pnpm --filter @salesiq/web test
```
```bash
pnpm --filter @salesiq/web build && pnpm --filter @salesiq/web test:e2e
```

`make` targets wrap these commands (Git Bash/WSL on Windows).

## Documentation
| Doc | Purpose |
|---|---|
| [PRODUCT_SPEC](docs/PRODUCT_SPEC.md) | What SalesIQ does and for whom |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, boundaries, request flow |
| [DATA_MODEL](docs/DATA_MODEL.md) | Schema and tenancy rules |
| [API_SPEC](docs/API_SPEC.md) | Conventions and endpoints |
| [SECURITY](docs/SECURITY.md) | Threat model and controls |
| [AI_EVALUATION](docs/AI_EVALUATION.md) | Model strategy and evaluation |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Build, release, backups |
| [DECISIONS](docs/DECISIONS.md) | Architecture decision log |
| [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md) | Honest list of gaps |
