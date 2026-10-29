# Implementation Roadmap

**Current phase:** Phase 1 complete → next is Phase 2 (authentication and multi-tenancy).
**Last updated:** 2026-10-29

## Phase status
| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, docs | Done |
| 1 | Foundation: monorepo, API, web, DB, Docker, CI | Done (CI workflow not yet run on GitHub) |
| 2 | Auth, organizations, memberships, permissions, audit, isolation tests | Next |
| 3 | Leads, companies, activities, CSV import/export, dedupe, pipeline | Pending |
| 4 | Research lab: notebooks, synthetic data, provider abstraction, eval baseline | Pending |
| 5 | Sales intelligence: evidence, ICP, explainable scoring | Pending |
| 6 | LangGraph workflows with Postgres checkpoints | Pending |
| 7 | MCP server and bounded agents | Pending |
| 8 | Outreach drafts, suppression, approvals, dispatch adapter | Pending |
| 9 | Full dashboard and analytics | Pending |
| 10 | Integrations, quotas, entitlements | Pending |
| 11 | Hardening and release | Pending |

## Phase 0 — audit findings
- Repository was empty (no git, no code). Greenfield build following the spec layout.
- Toolchain on the dev machine: Python 3.12.10 (3.14 also present), Node 23.11, pnpm 10.9, uv 0.11.19, Docker 29.7.
- Host ports 5432/6379 are used by other local projects, so compose publishes Postgres on 55432 and Redis on 56379 (overridable).

## Phase 1 — completed
- Monorepo: `apps/api`, `apps/web`, `packages/contracts`, `infra`, `research`, `docs`, `.github`.
- API: settings with production secret guard; JSON logging with secret redaction; request-ID middleware with
  injection-safe IDs; security headers; uniform error envelope (no internal detail or echoed input);
  `/api/v1/health/live` and `/api/v1/health/ready` (per-dependency status, 503 when degraded); OpenAPI at `/api/v1/openapi.json`.
- Database: SQLAlchemy 2 models + first Alembic migration (organizations, users, memberships, audit_logs) with naming conventions.
- Contracts: TS types generated from the API schema; `--check` mode guards drift in CI.
- Web: app shell (collapsible sidebar with persisted preference, breadcrumb, mobile nav), design tokens, Overview and
  System status pages backed by the live readiness endpoint, error and 404 boundaries, honest empty states.
- Docker: API and web images (non-root, standalone Next output); compose with health-gated dependencies.
- CI: lint, format, mypy, pytest with Postgres/Redis services, contract drift, vitest, build, Playwright, dependency audits, image builds.

## Tests run (2026-10-29, local Windows machine)
| Check | Result |
|---|---|
| API `pytest` | 16 passed, 0 skipped (includes migration round-trip and model/migration drift against real Postgres) |
| API `ruff check`, `ruff format --check` | Clean |
| API `mypy --strict` | No issues (23 files) |
| Web `vitest` | 5 passed |
| Web `eslint`, `tsc --noEmit` | Clean |
| Web `next build` | Succeeded |
| Playwright (desktop + mobile, API running) | 8 passed, 2 skipped (sidebar tests are desktop-only by design) |
| `docker build` API and web | Succeeded |
| `docker compose --profile app up` | All 4 services healthy; `/health/ready` ok; `/status` renders live status |
| Contracts drift check | Up to date |
| `pip-audit`, `pnpm audit --prod` | No known vulnerabilities |
| GitHub Actions CI | Not run — no remote repository configured |

## Known blockers
- None for Phase 2. Model-provider API keys will be needed for non-mock evaluation in Phase 4.

## Next concrete steps (Phase 2)
1. Add password hashing (argon2) and server-side sessions stored in Postgres, delivered as `HttpOnly; Secure; SameSite=Lax` cookies.
2. Add CSRF double-submit token for cookie-authenticated mutations.
3. Endpoints: register (flag-gated), login, logout, session revoke, `GET /me`, org create/list, invitations.
4. Permission matrix in code (`app/core/permissions.py`) and a `require(permission)` dependency that resolves
   `organization_id` from the session + membership, never from client input.
5. Enable Postgres RLS on tenant tables keyed by a per-transaction `app.current_org` setting, as defense in depth.
6. Audit-log writes for auth and membership events.
7. Tests: cross-tenant read/write denial, IDOR on every org-scoped route, role escalation, session revocation.
8. Web: login page, org switcher, settings → team.
