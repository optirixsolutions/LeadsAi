# Implementation Roadmap

**Current phase:** Phase 7 complete → next is Phase 8 (outreach and approvals).
**Last updated:** 2026-10-31

## Phase status
| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, docs | Done |
| 1 | Foundation: monorepo, API, web, DB, Docker, CI | Done (CI workflow not yet run on GitHub) |
| 2 | Auth, organizations, memberships, permissions, audit, isolation tests | Done (CI not yet run on GitHub) |
| 3 | Leads, companies, activities, CSV import/export, dedupe, pipeline | Done (CI not yet run on GitHub) |
| 4 | Research lab: notebooks, synthetic data, provider abstraction, eval baseline | Done (Colab paths and hosted route not executed) |
| 5 | Sales intelligence: evidence, ICP, explainable scoring | Done (fetcher not run against the public internet; CI not run) |
| 6 | LangGraph workflows with Postgres checkpoints | Done (container worker not run; CI not run) |
| 7 | MCP server and bounded agents | Done (containers not run; CI not run) |
| 8 | Outreach drafts, suppression, approvals, dispatch adapter | Next |
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

## Phase 5 — completed
Acceptance met: a lead can be assessed, and every reason and signal in the result resolves to a stored evidence row.
- **ICP:** criteria and weights in immutable versions; Settings → ICP and scoring, with history.
- **Evidence and source tracking:** findings, CRM fields, and fetched pages, each with source, time, and review state. Fetching
  uses the SSRF-resistant fetcher and is limited to the lead's company domain.
- **Evidence validation:** the input gate quarantines instruction-like text until a manager or admin releases it.
- **Scoring and qualification:** a deterministic 0–100 score with components, cited reasons, dated signals, missing information,
  and a review status. CRM-only results are escalated as `insufficient_evidence`.
- **Briefs:** real model output, checked by the output gate, shown as inference, and never read by scoring.
- **Web:** assessment, brief, evidence, and company-facts panels on the lead page, with citations that jump to the source.
- **Independent security review** found no tenant breach, role bypass, XSS, or route to private IPv4 addresses. Fixed with tests:
  CPU exhaustion through a site-chosen charset, a deadline that did not cover response headers, a slow gate pattern, a company
  name outside the untrusted block, ungated missing-information text, gate evasion through invisible and lookalike characters,
  unbounded writes and briefs, IPv6 gaps, and unhandled malformed input. Remaining items are in KNOWN_LIMITATIONS.
- **Measured:** the input gate caught none of 8 reworded attacks. See AI_EVALUATION.md and `research/evaluations/GATES.md`.

## Phase 6 — completed
Acceptance met: a failed run shows which step failed, why, and what to do, and resuming continues from the last completed step
with no duplicate assessment, brief, or activity. A test kills a real worker process during a model call, and another recovers the run.
- **Queue:** runs in Postgres with leases; workers claim through definer functions that return IDs only (ADR-021, ADR-022).
- **Graphs:** typed state, a research graph and a lead-intelligence graph, Postgres checkpoints, cancellation, deadlines.
- **Side effects:** made safe to repeat by database constraints (ADR-023).
- **Approval:** a proposed status change pauses the run until a manager or admin decides, and is recorded under that person.
- **Imports:** above 1,000 rows they go to the worker, because the largest allowed file took 36 s (ADR-025). The file is deleted once processed.
- **Web:** workflow card on the lead page, Workflows list and run detail with the step trace, worker status on System status.
- **Independent review** found no cross-tenant path and no way for a rep to approve a change. Fixed with tests: checkpoint reads that
  could run code, a crash that could lose a person's decision, approvals recorded under the requester, addresses and provider text in
  checkpoints, orphaned checkpoints, a leftover brief blocking its lead, unbounded import queues, unfair claims, and a late answer
  overwriting a newer one. One finding was only partly fixed: see the first item in KNOWN_LIMITATIONS.

## Phase 7 — completed
Acceptance met: authorized tools work, unauthorized calls fail and are logged, and agent output passes a deterministic review before it is stored.
- **Worker role:** workers connect as `salesiq_worker`, and the API can no longer reach checkpoints or claim work (ADR-029).
- **MCP server:** 16 tools over real services on the official SDK, in memory for agents and over HTTP with tokens for outside clients (ADR-026, ADR-028).
- **Agents:** research, qualification, and pipeline analyst, as workflow steps with the same trace and recovery. Read-only tools, one lead, hard
  limits (ADR-027). Attacks measured against real models in `research/evaluations/AGENTS.md`.
- **Web:** Agents page, run view with sources and every tool call, agent buttons on the lead page, Settings → MCP tokens.
- **Independent review** found no authorization bypass, no cross-tenant path, and no write path for an agent. Fixed with tests: malformed calls
  that could skip the audit log, free text in the log, agent budgets that could be exceeded, cancellation ignored mid-run, tokens surviving a
  password change or removal, MCP bypassing REST rate limits, one rep filling the queue, a migration that failed open, and the API holding the owner URL.

## Tests run (2026-10-31, local Windows machine)
Playwright ran with `SALESIQ_API_URL` on a free port because another local project holds :8000.
| Check | Result |
|---|---|
| API `pytest` | 401 passed, 0 skipped, including real Ollama models, real MCP over HTTP, and a killed worker process |
| API `ruff check`, `ruff format`, `mypy --strict` | Clean (87 files) |
| Web `vitest` | 37 passed |
| Web `eslint`, `tsc --noEmit`, `next build` | Clean / succeeded |
| Playwright (desktop + mobile, real API, worker, Postgres) | 45 passed, 3 skipped (sidebar tests are desktop-only) |
| `docker compose config` | Valid; the images and the containerized worker were not built or run |
| Notebooks 01–06 (local Ollama, Phase 4) | All executed; not rerun on the new prompt version; Colab paths not run |
| Contracts drift check | Up to date |
| `pip-audit`, `pnpm audit --prod` | No known vulnerabilities |
| GitHub Actions CI | Not run — no remote repository configured |

## Known blockers
- Sending real email needs a provider choice and explicit approval. Phase 8 can be built and tested fully up to that point without one.

## Next concrete steps (Phase 8)
1. Outreach drafts: a bounded agent writes, using only cited facts, and every draft is a record a person can edit.
2. Suppression lists and opt-outs, checked by fixed rules at draft time and again at dispatch.
3. Approval requests through the workflow interrupt from Phase 6, recorded under the person who approves.
4. A dispatch adapter that refuses to send without an approval record and a final policy check. No real provider without explicit approval.
5. Outreach and follow-up tools for MCP, with sending never available as a tool.