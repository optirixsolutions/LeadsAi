# API Specification

Base path: `/api/v1`. Machine-readable schema: `GET /api/v1/openapi.json` (interactive docs at `/api/docs` outside production).
TypeScript types are generated into `packages/contracts/src/openapi.ts`.

## Conventions
- **Errors** — every non-2xx response:
  ```json
  {"error": {"code": "not_found", "message": "Lead not found", "details": null, "request_id": "9f2c…"}}
  ```
  Codes: `bad_request`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error`, `method_not_allowed`, `internal_error`.
  500s never include exception text; 422 details include location and message but not the submitted value.
- **Correlation** — `x-request-id` is accepted if it matches `[A-Za-z0-9._-]{8,64}`, otherwise generated; always returned.
- **Pagination** (from Phase 3) — cursor-based: `?limit=50&cursor=…`, response `{"items": [...], "next_cursor": …}`.
- **Idempotency** (from Phase 3) — mutating endpoints that may be retried accept `Idempotency-Key`.
- **Long-running work** — returns `202` with an execution ID; status via `GET /workflows/{id}` or SSE.
- **Auth** (from Phase 2) — HttpOnly session cookie; mutations require `x-csrf-token`.

## Endpoints
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health/live` | none | Process is serving. `{status, service, version}` |
| GET | `/health/ready` | none | Per-dependency checks for database and redis. 200 when all ok, 503 when degraded. Errors report the exception type only |

| POST | `/auth/register`, `/auth/login` | none (JSON only, rate limited) | Create account / sign in; sets session + CSRF cookies |
| POST | `/auth/logout`, `/auth/password` | session + CSRF | Sign out; change password (revokes other sessions) |
| GET / DELETE | `/auth/me`, `/auth/sessions`, `/auth/sessions/{id}` | session | Current user + memberships; list/revoke own sessions |
| POST | `/auth/password-reset/request`, `/auth/password-reset/confirm`, `/auth/verify-email`, `/auth/verify-email/resend` | none / session | Single-use token flows; request always returns 202 |
| POST / GET | `/organizations` | session | Create (caller becomes owner) / list own orgs |
| GET / PATCH | `/organizations/{org_id}` | member / `org:update` | Read / rename |
| GET / PATCH / DELETE | `/organizations/{org_id}/members[/{id}]` | member / `members:manage` | List, change role, remove or leave |
| POST / GET / DELETE | `/organizations/{org_id}/invitations[/{id}]` | `members:invite` | Invite, list pending, revoke |
| POST | `/invitations/preview`, `/invitations/accept` | none / verified session | Inspect or redeem an invitation token |
| GET | `/organizations/{org_id}/audit?limit&cursor` | `audit:read` | Cursor-paginated audit log |
| GET / POST | `/organizations/{org_id}/leads` | `leads:read` / `leads:write` | List (filters `q`, `status` (repeatable), `owner` (id or `none`), `tag`, `company_id`, `source`, `import_id`; `sort` one of `created_at`, `updated_at`, `last_name`, `email` with optional `-`; `limit`, `cursor`) / create. Duplicate email → 409 `duplicate_lead` with `details.existing_lead_id` |
| GET / PATCH / DELETE | `/organizations/{org_id}/leads/{id}` | read / write / `leads:delete` | Detail with timeline (50 latest) and opportunities / partial update / soft delete |
| POST | `/organizations/{org_id}/leads/{id}/notes` | `leads:write` | Append a note; returns the timeline |
| POST | `/organizations/{org_id}/leads/bulk` | `leads:write` (+`leads:delete` for delete) | `{ids ≤ 500, action: assign\|set_status\|add_tag\|remove_tag\|delete, value}` → `{affected}`; IDs outside the org are ignored |
| GET | `/organizations/{org_id}/leads/export` | `leads:export` | CSV of the filtered leads (≤ 50,000), formula-escaped, audited |
| POST | `/organizations/{org_id}/lead-imports/preview` | `leads:import` | `{filename, content}` → headers, 5 sample rows, row count, suggested mapping |
| POST / GET | `/organizations/{org_id}/lead-imports[/{id}]` | `leads:import` / `leads:read` | Run an import (201) or replay an identical one (200, `replayed: true`) / read its result |
| GET / POST / PATCH | `/organizations/{org_id}/companies[/{id}]` | read / write | List (`q`, cursor) / create / detail with lead count / update |
| GET / POST / PATCH | `/organizations/{org_id}/pipeline/stages[/{id}]` | `pipeline:read` / `pipeline:configure` | List / add / rename stages |
| GET | `/organizations/{org_id}/pipeline/summary` | `pipeline:read` | Count and per-currency totals per stage |
| GET / POST / PATCH | `/organizations/{org_id}/opportunities[/{id}]` | `pipeline:read` / `pipeline:write` | List (`stage_id`, `owner_id`, `include_closed`) / create / move or edit |
| GET | `/organizations/{org_id}/analytics/overview` | `pipeline:read` | Lead counts by status, 30-day additions, open pipeline and 90-day won value per currency, recent activity |
| GET / POST | `/organizations/{org_id}/icp`, `/icp/versions` | `intelligence:read` / `icp:configure` | Active ICP (`null` if none), version history, save a new immutable version |
| GET / POST | `/organizations/{org_id}/leads/{id}/evidence` | `intelligence:read` / `research:write` | List (≤ 500) / add a finding. Text is screened; instruction-like text is stored as `quarantined`. Repeats return the original row. 409 `evidence_limit` at 500 per lead |
| POST | `/organizations/{org_id}/leads/{id}/evidence/fetch` | `research:write` | `{url}`: fetch an HTTPS page on the lead's company domain. 422 `fetch_blocked`, 502 `fetch_failed`, 400 `company_domain_required`. 10 per minute per org |
| PATCH | `/organizations/{org_id}/leads/{id}/evidence/{id}` | `intelligence:review` | `{status: accepted\|rejected}`; audited |
| GET / POST | `/organizations/{org_id}/leads/{id}/assessments` | `intelligence:read` / `assessments:run` | History (≤ 50) / score the lead now; returns the result with its evidence. 409 `icp_required` if no ICP exists. 30 per minute per user |
| GET / PATCH | `/organizations/{org_id}/assessments/{id}` | `intelligence:read` / `intelligence:review` | Result with the stored evidence behind it / `{evaluation_status: approved\|rejected}`; audited |
| POST | `/organizations/{org_id}/leads/{id}/briefs` | `research:write` | 202; a model writes a brief after the response. 409 `evidence_required` or a brief already running, 429 past limits |
| GET | `/organizations/{org_id}/leads/{id}/briefs/latest` | `intelligence:read` | Poll for status `running`, `completed`, `rejected`, or `failed` with `failure_category`; 404 if none. `rejected_claims[].text` is null without `intelligence:review` |

| POST | `/organizations/{org_id}/leads/{id}/workflows` | `workflows:run` | `{urls ≤ 3, propose_status}`; 202, run queued. 409 if the lead already has an active run, 429 past limits |
| GET | `/organizations/{org_id}/workflows[?lead_id]`, `/workflows/{id}` | `workflows:read` | Newest 50 / one run with its step trace, diagnosis, and result |
| POST | `/organizations/{org_id}/workflows/{id}/cancel`, `/resume` | `workflows:run` | Cancel an active run / continue a failed run from its last checkpoint. 409 when not applicable |
| POST | `/organizations/{org_id}/workflows/{id}/decision` | `intelligence:review` | `{decision: approved\|rejected}` for a run in `waiting_approval`; audited |
| GET | `/workers/health` | session | `{alive}`: whether a background worker reported in recently |

| GET | `/organizations/{org_id}/agents` | `workflows:read` | Agent roles, their tools and limits, and the whole tool catalog |
| POST | `/organizations/{org_id}/agents/{role}/runs` | `workflows:run` | `{lead_id}` for `research` and `qualification`; none for `pipeline`. 202, queued. 409 if one is already active for that lead or agent |
| GET | `/organizations/{org_id}/agent-runs[?lead_id]`, `/agent-runs/{id}` | `workflows:read` | Newest 50 / one run with its findings, sources, and tool calls. Removed claim wording needs `intelligence:review` |
| GET / POST / DELETE | `/organizations/{org_id}/mcp-tokens[/{id}]` | `workflows:read`, own tokens only | List / create (`current_password` is required for `scope: write`; the secret appears only in this response) / revoke |

**MCP server** (`python -m app.mcp.http`, streamable HTTP at `/mcp`): every request needs `Authorization: Bearer <token>`. Tools: `search_leads`,
`get_lead_profile`, `create_lead`, `update_lead`, `list_lead_activities`, `get_research_evidence`, `search_company_research`, `save_research_evidence`,
`get_lead_score`, `evaluate_lead_fit`, `get_icp_configuration`, `get_pipeline_summary`, `list_open_opportunities`, `get_opportunity_details`,
`get_workflow_status`, `request_action_approval`. Failed calls return `is_error` with text `category: message`. A tool can ask for a status change
to be approved, but no tool can approve one.

`POST /lead-imports` returns 202 with status `queued` above 1,000 rows; poll `GET /lead-imports/{id}`. `POST /leads/{id}/briefs` queues
a research run, so it now also needs a running worker.

References to other records (company, lead, stage, owner) that are not in the caller's org return 422
`invalid_reference`. Non-members receive 404 on every org-scoped route. Full schemas: `/api/v1/openapi.json`.

Scores rank a lead against the organization's ICP. They are deterministic, are not conversion probabilities, and are never
changed by model output. Research older than the ICP's `signal_ttl_days` does not count toward them.

Planned groups: `tasks`, `outreach`, `approvals`, `integrations`, `usage`.
