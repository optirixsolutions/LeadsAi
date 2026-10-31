# Deployment

Status: every image was built and the full stack run from an empty database on one development machine. No production environment exists yet. See RELEASE_CHECKLIST.md.

## Images
| Image | Dockerfile | Context | Notes |
|---|---|---|---|
| API | `infra/docker/api.Dockerfile` | `apps/api` | Python 3.12 slim, `uv sync --frozen --no-dev`, non-root, healthcheck on `/health/live` |
| Web | `infra/docker/web.Dockerfile` | repo root | Node 22 alpine, Next standalone output, non-root |

## Local full stack
```bash
docker compose up -d --wait postgres redis
docker compose --profile migrate run --rm migrate
docker compose --profile app up -d --build
python scripts/release_smoke.py http://127.0.0.1:3000 http://127.0.0.1:8100 localhost:8100
```
The `api` service runs as `salesiq_app`, and only the one-off `migrate` service holds the owner URL (`SALESIQ_MIGRATION_DATABASE_URL`).

## Worker
The `worker` service uses the API image and runs `python -m app.tasks.worker`. It has no HTTP port, and it connects
as `salesiq_worker` (`SALESIQ_WORKER_DATABASE_URL`). Run as many as you like: claims are atomic. `SALESIQ_WORKER_CONCURRENCY` sets runs per process, and
`SALESIQ_WORKER_LEASE_SECONDS` sets how long a dead worker's run waits before recovery. It reaches Ollama on the Docker host by default;
set `SALESIQ_OLLAMA_BASE_URL` to use another model server. On stop, a worker finishes what it can within 10 seconds, and anything
unfinished is recovered by another worker when its lease expires.

## MCP server
`python -m app.mcp.http` (the `mcp` service) serves outside MCP clients at `/mcp`, and every request needs a token from Settings → MCP tokens.
It binds to localhost by default and serves only the host in `SALESIQ_MCP_PUBLIC_URL`. Outside development that URL must be HTTPS, so put TLS
in front of it. Set `SALESIQ_MCP_HOST` to listen beyond localhost. It connects as `salesiq_app` and needs no worker rights.

Upgrading `langgraph-checkpoint-postgres` may add checkpoint migrations, which the app role cannot run. Add an Alembic revision that
runs its setup as the schema owner in the same release.

## Sending outreach
Off by default. To let approved email leave, set these on the API, then have an admin turn sending on in Outreach → Settings.

| Variable | Notes |
|---|---|
| `SALESIQ_DISPATCH_ADAPTER` | `disabled` (default) or `smtp` |
| `SALESIQ_DISPATCH_SMTP_HOST`, `_PORT` | Default `127.0.0.1:1025`. Anything but loopback also needs the next setting |
| `SALESIQ_DISPATCH_ALLOW_EXTERNAL` | **Real people can receive what goes through this.** Outside development it requires STARTTLS |
| `SALESIQ_DISPATCH_SMTP_STARTTLS`, `_USERNAME`, `_PASSWORD`, `_TIMEOUT_S` | Server login and timeout |
| `SALESIQ_WEB_BASE_URL` | Opt-out links are built from this. Outside development, startup refuses SMTP sending unless it is a public HTTPS address |

To try sending without reaching anyone, run a local mail catcher on port 1025, such as `uv run python -m tests.support.smtp_sink 1025 mail.jsonl` from `apps/api`,
which keeps what it receives in that file and passes nothing on.

## Provider credentials and plans
`SALESIQ_CREDENTIALS_KEY` is required outside development: `python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`. Keep it in a secret manager and back it up
separately from the database. Without it, stored provider passwords cannot be read, and rotating it is not built yet, so changing it means entering them again.

`SALESIQ_DEFAULT_PLAN` (default `team`) names a plan in `apps/api/app/core/plans.yaml`. Editing that file changes limits on the next restart. No payment provider exists: to connect one,
add an adapter that writes `subscriptions` from its signed webhooks, and keep `POST /billing/development-plan` refusing outside development.

To connect an email provider: an owner or admin adds its SMTP details under Integrations, and gives the provider the webhook address and secret shown once. Providers have their own event
formats, so one that cannot send ours needs a small adapter in front of `webhook_service`. Mail reaches real people only with `SALESIQ_DISPATCH_ADAPTER=smtp` and
`SALESIQ_DISPATCH_ALLOW_EXTERNAL=true`.

## Database roles (provision before the first migration)
| Role | Attributes | Purpose |
|---|---|---|
| Schema owner | LOGIN, owns `public` | Runs migrations only (`SALESIQ_MIGRATION_DATABASE_URL`) |
| `salesiq_app` | LOGIN, NOSUPERUSER, NOBYPASSRLS, not an owner | API runtime (`SALESIQ_DATABASE_URL`). Connecting as an owner or superuser silently disables RLS |
| `salesiq_worker` | LOGIN, NOSUPERUSER, NOBYPASSRLS | Worker runtime (`SALESIQ_WORKER_DATABASE_URL`). Must exist before migrating; the migration fails otherwise. An existing local database needs it created once, from `infra/docker/postgres-init.sql` |
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
| `SALESIQ_CREDENTIALS_KEY` | yes (base64, 32 bytes) | From a secret manager. Encrypts provider credentials |
| `SALESIQ_MAILER` | yes | Must be `disabled` outside development until a real provider adapter exists |
| `SALESIQ_REGISTRATION_ENABLED` | no | Default `true` |
| `SALESIQ_API_URL` (web, **build time**) | yes | Internal API URL for the same-origin `/api/v1` rewrite; rebuild the web image to change it |

## Reverse proxy and client IPs
Rate limits key on the client IP. Run uvicorn with `--forwarded-allow-ips=<trusted proxy CIDRs>` and make sure the
proxy (load balancer and the Next.js rewrite hop) forwards `X-Forwarded-For`. Otherwise every user shares one bucket.
Never trust forwarded headers from arbitrary sources.

## Backups and recovery
Back up three things separately, because each is useless without the others in some way:
- **The database,** by your provider's point-in-time recovery where possible, or `pg_dump -Fc`.
- **`SALESIQ_CREDENTIALS_KEY`.** Without it, a restored database has passwords nobody can read, and each provider has to be connected again. Keep it out of the database backup.
- **`SALESIQ_SECRET_KEY`.** Without it, sessions end, and opt-out links in emails already sent stop working. That last one matters: those people can still ask by replying, but the link fails.

To restore:
```bash
pg_dump -U salesiq -d salesiq -Fc -f salesiq.dump
createdb -U salesiq salesiq_restored
pg_restore -U salesiq -d salesiq_restored --exit-on-error salesiq.dump
```
The roles `salesiq_app`, `salesiq_worker`, and `salesiq_definer` belong to the server and not the dump, so create them first on a new server (`infra/docker/postgres-init.sql`). Then compare row counts, confirm that the app role sees nothing with no tenant set, and run `python scripts/release_smoke.py`.

Run a restore drill every quarter and record it here.

| Date | Where | Result |
|---|---|---|
| 2026-10-31 | Local container, small database | Counts for 6 tables matched. 27 tables under forced RLS and 32 policies intact. The app role saw 0 leads with no tenant set, and was refused a delete |

Redis holds only cache, rate-limit, and coordination state, and is not a system of record. A lost worker's runs recover on their own when their leases expire.
