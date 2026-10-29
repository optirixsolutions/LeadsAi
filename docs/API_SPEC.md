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

Non-members receive 404 on every org-scoped route. Full schemas: `/api/v1/openapi.json`.

Planned groups: `leads`, `companies`, `research`, `qualification`, `opportunities`,
`pipeline`, `activities`, `tasks`, `outreach`, `approvals`, `agents`, `workflows`, `integrations`, `analytics`, `usage`, `audit`.
