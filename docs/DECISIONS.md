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

### ADR-010 · 2026-10-30 · Server-side sessions over JWTs
Opaque 256-bit tokens in HttpOnly cookies, stored as SHA-256 digests, so sessions can be revoked instantly (logout,
password change/reset, device list) and nothing sensitive is readable by scripts. CSRF uses an HMAC of the session
token, so no CSRF state is stored server-side.

### ADR-011 · 2026-10-30 · Postgres RLS as defense in depth, with a non-superuser runtime role
Application code scopes every query by the org resolved from membership. RLS (`FORCE`, per-command policies keyed by
transaction-local `app.org_id` / `app.user_id`) catches anything that slips. The API connects as `salesiq_app`,
because owners and superusers bypass RLS. Writes and deletes are confined to the current org; reads may span the
caller's own memberships so they can list their orgs.

### ADR-012 · 2026-10-30 · Explicit commits in handlers
`get_db` never auto-commits. Handlers commit after the work is complete and before returning, so a client never gets
a success response for a write that later fails to commit. Because tenant context is transaction-local, any read after
a commit must re-apply it (`restore_context`). Server defaults come back via RETURNING (`eager_defaults`) to avoid
post-commit reloads.

### ADR-013 · 2026-10-30 · Browser calls the API through a same-origin rewrite
Next.js rewrites `/api/v1/*` to the API, so session cookies are first-party and no CORS is needed. Server components
call the API directly and forward the incoming cookie. Downside: the rewrite target is fixed at build time (ADR-008 image).

### ADR-014 · 2026-10-30 · Invitation acceptance requires a verified email
A leaked invite link alone must not grant access. The invitee's account must match the invited address and be verified.
This costs new users a second email; revisit with "token redemption verifies a brand-new account".
