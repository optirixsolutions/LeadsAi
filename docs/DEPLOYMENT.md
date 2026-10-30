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
The `api` service has both URLs set: it runs as `salesiq_app`, and Alembic uses `SALESIQ_MIGRATION_DATABASE_URL`.

## Worker
The `worker` service uses the API image and runs `python -m app.tasks.worker`. It has no HTTP port, and it connects as `salesiq_app`
like the API. Run as many as you like: claims are atomic. `SALESIQ_WORKER_CONCURRENCY` sets runs per process, and
`SALESIQ_WORKER_LEASE_SECONDS` sets how long a dead worker's run waits before recovery. It reaches Ollama on the Docker host by default;
set `SALESIQ_OLLAMA_BASE_URL` to use another model server. On stop, a worker finishes what it can within 10 seconds, and anything
unfinished is recovered by another worker when its lease expires.

Upgrading `langgraph-checkpoint-postgres` may add checkpoint migrations, which the app role cannot run. Add an Alembic revision that
runs its setup as the schema owner in the same release.

## Database roles (provision before the first migration)
| Role | Attributes | Purpose |
|---|---|---|
| Schema owner | LOGIN, owns `public` | Runs migrations only (`SALESIQ_MIGRATION_DATABASE_URL`) |
| `salesiq_app` | LOGIN, NOSUPERUSER, NOBYPASSRLS, not an owner | API runtime (`SALESIQ_DATABASE_URL`). Connecting as an owner or superuser silently disables RLS |
| `salesiq_definer` | NOLOGIN, BYPASSRLS | Owns `invitation_lookup()`, `workflow_claim()`, and `import_claim()`; creating it needs a superuser (or a managed-Postgres admin role) |

`infra/docker/postgres-init.sql` holds the local versions of these statements. Migrations grant privileges to these
roles if they exist and log a notice otherwise.

## Release procedure (target)
1. CI green on the commit (lint, types, tests, e2e, audits, image builds).
2. Build and tag images with the commit SHA.
3. Run `alembic upgrade head` as a one-off job against the target database (never on container boot).
4. Roll out API and workers, then web. Readiness (`/api/v1/health/ready`) gates traffic.
5. Migrations must be backward compatible with the previous API version (expand → migrate → contract).

## Required configuration
| Variable | Required | Notes |
|---|---|---|
| `SALESIQ_ENVIRONMENT` | yes | `production` disables `/api/docs` and enforces secret checks |
| `SALESIQ_SECRET_KEY` | yes (≥32 chars) | From a secret manager |
| `SALESIQ_DATABASE_URL` | yes | Runtime role `salesiq_app`; `postgresql+psycopg://…`; use TLS (`sslmode=require`) |
| `SALESIQ_MIGRATION_DATABASE_URL` | for migrations | Schema-owner credentials; only in the migration job |
| `SALESIQ_REDIS_URL` | yes | Use `rediss://` in production |
| `SALESIQ_CORS_ORIGINS` | yes | JSON list of web origins |
| `SALESIQ_WEB_BASE_URL` | yes | Public web URL used in email links |
| `SALESIQ_MAILER` | yes | Must be `disabled` outside development until a real provider adapter exists |
| `SALESIQ_REGISTRATION_ENABLED` | no | Default `true` |
| `SALESIQ_API_URL` (web, **build time**) | yes | Internal API URL for the same-origin `/api/v1` rewrite; rebuild the web image to change it |

## Reverse proxy and client IPs
Rate limits key on the client IP. Run uvicorn with `--forwarded-allow-ips=<trusted proxy CIDRs>` and make sure the
proxy (load balancer and the Next.js rewrite hop) forwards `X-Forwarded-For`. Otherwise every user shares one bucket.
Never trust forwarded headers from arbitrary sources.

## Backups and recovery (to be completed in Phase 11)
- Managed Postgres with point-in-time recovery; daily snapshot retention per plan.
- Quarterly restore drill into a scratch environment; record results here.
- Redis holds only cache, rate-limit, and coordination state; it is not a system of record.
