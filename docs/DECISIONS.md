# Architecture Decision Log

Format: ID · date · decision · rationale · consequences.

### ADR-001 · 2026-10-29 · Modular monorepo, one backend plus workers
Monorepo with `apps/api`, `apps/web`, `packages/*`. A single FastAPI service with domain modules; long-running work goes to
separately deployable worker processes later. No microservices until an operational need justifies one.

### ADR-002 · 2026-10-29 · Synchronous SQLAlchemy 2 with psycopg 3
FastAPI runs sync endpoints in a threadpool. Sync sessions are simpler to reason about for transactions, RLS session
variables, and Alembic. Revisit if profiling shows threadpool saturation.

### ADR-003 · 2026-10-29 · Python 3.12
3.14 is available locally, but agent/LLM libraries planned for later phases (LangGraph, CrewAI) have historically lagged
on new Python releases. 3.12 is pinned in `.python-version` and the Docker image.

### ADR-004 · 2026-10-29 · OpenAPI-generated TypeScript contracts
The API is the source of truth. `packages/contracts` generates types from the exported schema with `openapi-typescript`;
CI fails on drift. Avoids hand-maintained duplicate types.

### ADR-005 · 2026-10-29 · Web talks to the API server-side
Server Components call the API with a server-only base URL (`SALESIQ_API_URL`, guarded by `server-only`). Client-side
fetching is added only for interactive views. Keeps internal URLs out of the bundle and avoids CORS for reads.

### ADR-006 · 2026-10-29 · Non-default host ports for local infra
Postgres 55432, Redis 56379, both bound to 127.0.0.1. The dev machine already runs other stacks on default ports.

### ADR-007 · 2026-10-29 · TypeScript 6.0 for the web app, 5.9 for contracts
TypeScript 7 (native) is current, but Next.js type-checking relies on the JS compiler API. The web app uses 6.0.3 (latest
JS-based release); contracts use 5.9.3 because `openapi-typescript` declares a `^5` peer.

### ADR-008 · 2026-10-29 · Standalone Next output only for Docker
`output: "standalone"` is enabled by `SALESIQ_STANDALONE=1` in the image build, so `next start` keeps working for local
runs and Playwright.

### ADR-009 · 2026-10-29 · Migrations are a release step
Containers do not migrate on boot. A one-off `alembic upgrade head` job runs before rollout, so concurrent replicas never
race on DDL.
