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

Planned groups: `auth`, `organizations`, `members`, `leads`, `companies`, `research`, `qualification`, `opportunities`,
`pipeline`, `activities`, `tasks`, `outreach`, `approvals`, `agents`, `workflows`, `integrations`, `analytics`, `usage`, `audit`.
