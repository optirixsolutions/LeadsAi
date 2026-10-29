# Deployment

Status: container images and compose are verified locally. No production environment exists yet.

## Images
| Image | Dockerfile | Context | Notes |
|---|---|---|---|
| API | `infra/docker/api.Dockerfile` | `apps/api` | Python 3.12 slim, `uv sync --frozen --no-dev`, non-root, healthcheck on `/health/live` |
| Web | `infra/docker/web.Dockerfile` | repo root | Node 22 alpine, Next standalone output, non-root |

## Local full stack
```bash
docker compose --profile app up -d --build --wait
docker compose run --rm api .venv/bin/alembic upgrade head
```

## Release procedure (target)
1. CI green on the commit (lint, types, tests, e2e, audits, image builds).
2. Build and tag images with the commit SHA.
3. Run `alembic upgrade head` as a one-off job against the target database (never on container boot).
4. Roll out API, then web. Readiness (`/api/v1/health/ready`) gates traffic.
5. Migrations must be backward compatible with the previous API version (expand → migrate → contract).

## Required configuration
| Variable | Required | Notes |
|---|---|---|
| `SALESIQ_ENVIRONMENT` | yes | `production` disables `/api/docs` and enforces secret checks |
| `SALESIQ_SECRET_KEY` | yes (≥32 chars) | From a secret manager |
| `SALESIQ_DATABASE_URL` | yes | `postgresql+psycopg://…`; use TLS (`sslmode=require`) |
| `SALESIQ_REDIS_URL` | yes | Use `rediss://` in production |
| `SALESIQ_CORS_ORIGINS` | yes | JSON list of web origins |
| `SALESIQ_API_URL` (web) | yes | Internal API URL, server-side only |

## Backups and recovery (to be completed in Phase 11)
- Managed Postgres with point-in-time recovery; daily snapshot retention per plan.
- Quarterly restore drill into a scratch environment; record results here.
- Redis holds only cache, rate-limit, and coordination state; it is not a system of record.
