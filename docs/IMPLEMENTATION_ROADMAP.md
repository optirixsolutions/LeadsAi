# Implementation Roadmap

**Current phase:** Phase 2 complete → next is Phase 3 (lead and CRM domain).
**Last updated:** 2026-10-30

## Phase status
| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, docs | Done |
| 1 | Foundation: monorepo, API, web, DB, Docker, CI | Done (CI workflow not yet run on GitHub) |
| 2 | Auth, organizations, memberships, permissions, audit, isolation tests | Done (CI not yet run on GitHub) |
| 3 | Leads, companies, activities, CSV import/export, dedupe, pipeline | Next |
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
- Monorepo, FastAPI foundation (config guards, JSON logs with redaction, request IDs, error envelope, health probes),
  first migration, generated TS contracts, Next.js shell, Docker images, compose, CI. Commit `11d3cd8`.

## Phase 2 — completed
- **Identity:** argon2id passwords (12–256 chars), timing-equalized login, server-side sessions (SHA-256 of a 256-bit
  token) in `HttpOnly; SameSite=Lax` cookies (`Secure` in staging/production), absolute TTL 14 days and 24 h idle
  timeout, fresh token per login, re-login revokes the browser's previous session, logout and per-device revocation,
  password change (revokes other sessions), password reset and email verification with single-use expiring tokens.
- **CSRF:** HMAC(session) token echoed in `x-csrf-token` on every cookie-authenticated mutation; pre-session endpoints
  require `application/json` (forces a CORS preflight).
- **Tenancy:** organizations, memberships, invitations. Org context comes only from the caller's membership; non-members
  get 404. Postgres RLS (`FORCE`, per-command policies) with the API connecting as non-superuser `salesiq_app`;
  invitation tokens resolved by a narrow `SECURITY DEFINER` function owned by NOLOGIN `salesiq_definer`.
- **Authorization:** role → permission matrix (`app/core/permissions.py`); owners manage all roles, admins manage
  manager/sales rep/analyst only; nobody changes their own role; last owner protected under a row lock.
- **Invitations:** emailed token, must be redeemed by the invited address with a verified email; re-invite replaces
  only invites the actor could revoke.
- **Audit:** append-only (`SELECT, INSERT` grants only) log of auth, org, member, and invitation events with request IDs;
  cursor-paginated `GET /organizations/{id}/audit`.
- **Rate limits (Redis):** login per email and per IP, registration, password reset, token redemption, password change.
- **Web:** sign in, register, forgot/reset password, verify email, invitation preview/accept, onboarding, org switcher,
  user menu, Settings → Team (roles, removal, invitations), Organization (rename, audit log), Account (password,
  sessions). Browser calls the API same-origin through Next rewrites; `proxy.ts` redirects signed-out visitors.
- **Independent security review** (subagent, read-only) found no route-level IDOR. Fixed: unverified accounts accepting
  invites, last-owner race, RLS DELETE outside org context, definer function owned by a superuser, `pg_temp`
  shadowing, invitation lock/re-invite displacement, unlimited password-change attempts, orphaned sessions on re-login.
  Each has a regression test in `tests/test_security_regressions.py`; the race test was confirmed to fail with the lock
  removed. Remaining items are in KNOWN_LIMITATIONS.

## Tests run (2026-10-30, local Windows machine)
| Check | Result |
|---|---|
| API `pytest` | 87 passed, 0 skipped (auth, tenancy incl. direct RLS checks, permissions, regressions, migrations, platform) |
| API `ruff check`, `ruff format`, `mypy --strict` | Clean (37 files) |
| Web `vitest` | 20 passed |
| Web `eslint`, `tsc --noEmit`, `next build` | Clean / succeeded |
| Playwright (desktop + mobile, real API + Postgres) | 22 passed, 2 skipped (sidebar tests are desktop-only) |
| Contracts drift check | Up to date |
| `pip-audit`, `pnpm audit --prod` | No known vulnerabilities |
| `docker build` + `compose --profile app up` | Healthy; registration through the web proxy sets HttpOnly cookie; API connects as `salesiq_app` |
| GitHub Actions CI | Not run — no remote repository configured |

## Known blockers
- None for Phase 3. A real email provider is needed before production (see KNOWN_LIMITATIONS).

## Next concrete steps (Phase 3)
1. Tables: `companies`, `leads`, `lead_sources`, `lead_imports`, `lead_activities`, `pipeline_stages`, `opportunities`,
   `tasks`, `custom_field_definitions`; RLS on each, with grants added in the same migration.
2. Extend the permission matrix with `leads:read|write|delete|export|import`, `pipeline:*`.
3. Lead CRUD with cursor pagination, filters, sorting; normalized email/domain fields for dedupe.
4. CSV import as a durable job: upload → validate/preview → idempotent commit keyed by file hash + mapping, explicit
   duplicate policy (skip / update / create), per-row error report. CSV export with formula-injection escaping.
5. Pipeline stages per org (seeded defaults), opportunities with stage transitions recorded as activities.
6. Tests: tenant isolation for every new route, import idempotency, duplicate handling, CSV injection.
7. Web: Leads table (search, filters, bulk actions), lead profile, pipeline board + table.
