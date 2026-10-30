# Implementation Roadmap

**Current phase:** Phase 4 complete → next is Phase 5 (sales intelligence).
**Last updated:** 2026-10-30

## Phase status
| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, docs | Done |
| 1 | Foundation: monorepo, API, web, DB, Docker, CI | Done (CI workflow not yet run on GitHub) |
| 2 | Auth, organizations, memberships, permissions, audit, isolation tests | Done (CI not yet run on GitHub) |
| 3 | Leads, companies, activities, CSV import/export, dedupe, pipeline | Done (CI not yet run on GitHub) |
| 4 | Research lab: notebooks, synthetic data, provider abstraction, eval baseline | Done (Colab paths and hosted route not executed) |
| 5 | Sales intelligence: evidence, ICP, explainable scoring | Next |
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

## Phase 3 — completed
- **Data:** companies (unique normalized domain per org), leads (soft delete, unique live email per org, tags,
  custom fields, owner, source, import link), append-only activity timeline, CSV import records, pipeline stages
  (six defaults seeded per org and backfilled for existing orgs), opportunities (per-currency amounts, won/lost
  closing). RLS on every table; the app role has no DELETE on leads, companies, or opportunities and cannot change
  activities.
- **Permissions:** `leads:read|write|delete|import|export`, `pipeline:read|write|configure`. Sales reps sell but
  cannot delete, import, or export; analysts are read-only and cannot export.
- **API:** lead CRUD with duplicate detection (409 with the existing lead's ID); filters (search over name/email/
  company/title with escaped wildcards, status, owner/unassigned, tag, company, source, import); keyset pagination
  on five sort keys with totals; bulk assign / status / tag / delete (500 IDs, out-of-org IDs ignored); notes;
  companies; CSV preview with suggested mapping and an idempotent import (SHA-256 of file + settings) with
  skip/update duplicate policies, in-file dedupe, company matching by domain then name (free-mail domains ignored),
  and per-row errors; formula-safe CSV export (audited); stages; opportunities with stage-change history;
  per-currency pipeline summary; stored-record analytics overview.
- **Web:** Overview with real metrics; Leads table (URL filters, sort, selection, bulk toolbar, pagination, export);
  new lead; lead profile (inline edit, timeline, notes, opportunities, delete); import wizard (preview, mapping,
  policy, results with row errors); Pipeline board and table with per-currency stage totals and accessible stage moves.
- Formatting uses one locale and UTC on server and client so hydration never mismatches (per-user settings later).

## Phase 4 — completed
- **Model layer** (`app/agents/llm/`): one OpenAI-compatible client, YAML registry, retries, reported fallback, cost
  estimates, and distinct failure categories including `truncated`. Real models only (ADR-015). Not yet wired into the API.
- **Dataset** (`research/datasets/v1`): fictional, with a held-out split whose wording does not appear in train.
- **Evaluation** (`app/agents/evaluation/`): rule baseline, six tasks, per-call records, and a generated report.
- **Notebooks 01–06:** executed locally against real models, including an in-memory MCP tool-permission demo.
- **Results:** [research/evaluations/REPORT.md](../research/evaluations/REPORT.md); summary in AI_EVALUATION.md. The largest
  finding is that every model followed planted instructions at a measurable rate, so Phase 5 needs quality gates.

## Tests run (2026-10-30, local Windows machine)
API, contract, and `vitest` results are from the Phase 4 commit. `next build` and Playwright are from Phase 3 and were not
rerun, because Phase 4 did not change the web app.
| Check | Result |
|---|---|
| API `pytest` | 160 passed, 0 skipped, including real calls to local Ollama models |
| API `ruff check`, `ruff format`, `mypy --strict` | Clean (57 files) |
| Web `vitest` | 24 passed |
| Web `eslint`, `tsc --noEmit` | Clean |
| `next build` (Phase 3) | Succeeded |
| Playwright, desktop + mobile, real API + Postgres (Phase 3) | 30 passed, 2 skipped (sidebar tests are desktop-only) |
| Notebooks 01–06 (local Ollama) | All executed; Colab paths not run |
| Contracts drift check | Up to date |
| `pip-audit`, `pnpm audit --prod` | No known vulnerabilities |
| GitHub Actions CI | Not run — no remote repository configured |

## Known blockers
- None for Phase 5. Real email (Phase 8) needs a provider choice and explicit approval.

## Next concrete steps (Phase 5)
1. Evidence store: tables under RLS for sources and evidence items with provenance, wired to the model layer.
2. Research fetcher with the SSRF controls in SECURITY.md. Fetched text is untrusted input.
3. ICP definitions per organization and an explainable score with deterministic rules first; models add cited reasons.
4. Quality gates from the Phase 4 findings: reject uncited or unsupported claims and invented numbers, and strip or
   quarantine instruction-like evidence before it reaches a model. Model labels never trigger an action on their own.
5. Add injection cases to the evaluation for each new surface, and tune on train only.