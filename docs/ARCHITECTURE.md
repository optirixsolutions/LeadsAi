# Architecture

## Components
```
Browser ──► Next.js (apps/web) ──server-side fetch──► FastAPI (apps/api) ──► PostgreSQL
                                                          │                ├─► Redis
                                                          ├─► Workers (Phase 6: durable jobs)
                                                          ├─► AI orchestration (LangGraph, Phase 6)
                                                          └─► MCP server (Phase 7)
```

| Layer | Owns | Never does |
|---|---|---|
| Web | Presentation, interaction, client validation, API consumption | Authorization decisions, direct DB access |
| API | Authn/authz, validation, business rules, persistence, integrations | Trust client-supplied tenant IDs |
| AI orchestration | Model routing, structured inference, workflow state, evaluation | Bypass API permission checks |
| MCP | Exposes approved capabilities as typed tools | Replace auth or business logic |
| Workers | Long-running research, enrichment, imports, analytics | Retry irreversible actions without reconciliation |

## API internals (`apps/api/app`)
| Package | Purpose |
|---|---|
| `core/config.py` | Env-based settings; refuses insecure defaults outside development |
| `core/middleware.py` | Request ID (validated or generated), access log, security headers (pure ASGI) |
| `core/errors.py` | Uniform error envelope; hides internals; strips input from validation errors |
| `core/db.py` | Engine, sessions, per-request transaction dependency |
| `observability/logging.py` | JSON logs with request correlation and secret redaction |
| `models/` | SQLAlchemy models; naming conventions for stable migrations |
| `api/v1/` | Versioned routers |
| `schemas/`, `repositories/`, `services/` | Pydantic I/O, data access, domain logic (populated from Phase 2) |
| `workflows/`, `agents/`, `mcp/`, `integrations/`, `tasks/` | Reserved for later phases |

Middleware order (outermost first): request context → CORS → routing. Request context is outermost so every response,
including CORS rejections and 500s, carries `x-request-id`.

## Web internals (`apps/web`)
- `app/` routes (Server Components by default). Pages needing live data are `force-dynamic`.
- `components/shell` app frame; `components/ui` design-system primitives.
- `features/<domain>` feature modules (logic + components). Pure logic is unit-tested with Vitest.
- `lib/api.ts` server-only API client; `lib/api-result.ts` shared result type.
- Design tokens are defined once in `app/globals.css` (`@theme`).

## Tenancy model (Phase 2 target)
Session cookie → user → membership lookup for the requested org → role → permission check. The resolved
`organization_id` scopes every repository query and is also set as a Postgres session variable for RLS policies.

## Reliability principles
- Long-running operations return an execution ID; clients poll or subscribe via SSE.
- Jobs are durable (Postgres-backed), idempotent, bounded in retries, and observable.
- External side effects require recorded approval and a final server-side check at dispatch time.
