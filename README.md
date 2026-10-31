# SalesIQ

Evidence-driven revenue intelligence and sales automation platform.

> Status: all build phases done, not deployed. See [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for what has and has not been verified.

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

Run the API, the background worker, and the web app in three terminals:
```bash
cd apps/api && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
```bash
cd apps/api && uv run python -m app.tasks.worker
```
```bash
pnpm --filter @salesiq/web dev
```

The worker runs workflows, research briefs, and imports above 1,000 rows. Without it they stay queued, and System status says so.
Model work needs [Ollama](https://ollama.com) with the models in `apps/api/app/agents/llm/models.yaml`.

- Web: http://localhost:3000
- API docs: http://127.0.0.1:8000/api/docs
- Readiness: http://127.0.0.1:8000/api/v1/health/ready

Full stack in containers: `docker compose up -d --wait postgres redis`, then `docker compose --profile migrate run --rm migrate`, then
`docker compose --profile app up -d --build`. If ports are taken, set `SALESIQ_API_PORT`, `SALESIQ_WEB_PORT`, `SALESIQ_MCP_PORT`, `SALESIQ_PG_PORT`, and `SALESIQ_REDIS_PORT`.
Then `python scripts/release_smoke.py <web url> <mcp url> localhost:8100` walks a disposable deployment end to end.

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
| [RELEASE_CHECKLIST](docs/RELEASE_CHECKLIST.md) | What was verified, and what still needs the owner |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, boundaries, request flow |
| [DATA_MODEL](docs/DATA_MODEL.md) | Schema and tenancy rules |
| [API_SPEC](docs/API_SPEC.md) | Conventions and endpoints |
| [SECURITY](docs/SECURITY.md) | Threat model and controls |
| [AI_EVALUATION](docs/AI_EVALUATION.md) | Model strategy and evaluation |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Build, release, backups |
| [DECISIONS](docs/DECISIONS.md) | Architecture decision log |
| [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md) | Honest list of gaps |
