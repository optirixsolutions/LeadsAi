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

### ADR-015 · 2026-10-30 · Real models only, through one OpenAI-compatible client
The project owner ruled out mock AI: evaluations, notebooks, and workflows call real models, and tests use real failures
(closed ports, missing models, absent keys) and skip model calls when no model is reachable. This overrides the original
spec's "mock adapters first". Ollama, the Hugging Face router, and vLLM share one OpenAI-compatible client, so adding a
model is a `models.yaml` entry; a provider with a different protocol adds a client. Local models are the default because
they cost nothing per token and send no data out. The downside is that CI cannot exercise model behaviour.

### ADR-016 · 2026-10-30 · Qwen3 runs with thinking off
With thinking on and a 1024-token output limit, about 1 in 4 Qwen3 calls used the whole limit reasoning and returned no
answer. Raising the limit would make each call slower on hardware that already splits the model across CPU and GPU, so
`qwen3-4b` sets `reasoning_effort: none`. The fix came from the failure mechanism, diagnosed on train items, and prompts
were not changed. The stopped run stays in `research/evaluations/v1-test-qwen3-4b/` (records only) as evidence. Reaching
the limit is now a separate `truncated` failure rather than `schema_invalid`.

### ADR-017 · 2026-10-30 · Scores are deterministic; models only write labelled briefs
Phase 4 measured every model following planted instructions, so no model output can change a score, a status, or evidence.
A score comes from rules over stored CRM fields and accepted evidence, which makes it reproducible and traceable to rows. The
cost is recall: signals are configured keywords, so a need phrased differently is missed. A model brief is shown separately as
inference, with its claims checked against the evidence. A later phase may let models propose signals for human approval.

### ADR-018 · 2026-10-30 · Screened text is quarantined, not deleted, and reps cannot release it
False positives are expected, so flagged text is kept for review and has no effect until a manager or admin releases it.
Reps cannot release it, or they could plant an instruction and approve it themselves.

### ADR-019 · 2026-10-30 · Briefs run in-process until the Phase 6 worker
Local models can take minutes, longer than a web request should wait, and a durable worker arrives in Phase 6. Until then a brief
runs after the response on an API thread, limited by global slots and a per-org cap. A restart loses it, and it is reported as
`stale` after 10 minutes.

### ADR-020 · 2026-10-30 · The fetcher pins its connections with an httpcore backend
Checking an address and then letting the HTTP client resolve it again leaves a DNS rebinding gap. A custom `httpcore` network
backend resolves, checks, and connects to the checked address, and TLS still verifies the original hostname. This relies on
httpcore's backend interface, so `httpcore` is a direct dependency.

### ADR-021 · 2026-10-30 · The job queue is a Postgres table with leases
Redis is treated as disposable here (rate limits fail open), so losing work with it would be wrong. Runs live in Postgres, next to
the records they change. Workers claim with `FOR UPDATE SKIP LOCKED`, renew a lease while working, and a dead worker's run is
recovered when the lease expires. This replaces ADR-019. It costs some polling load, and it would need revisiting at a volume far
above what this product has now.

### ADR-022 · 2026-10-30 · Workers cross tenants only through narrow definer functions
A worker must find work across organizations, but RLS correctly hides that from the app role. `workflow_claim()` and `import_claim()`
return IDs only, and everything after that runs under the requester's tenant context, as ordinary RLS-checked queries. Authority is
looked up again when work runs, so a person who left or lost a role cannot keep acting through a queued job.

### ADR-023 · 2026-10-30 · Side effects are protected by database constraints, not by checkpoints alone
A step can repeat, because a crash between its commit and the checkpoint re-runs it. So a run can have one assessment and one brief
(unique `workflow_run_id`), evidence is deduplicated by content, and a status change first checks the lead still has the status the
approver saw. Checkpoints keep work from repeating in the normal case, and the constraints make a repeat harmless in the rest.

### ADR-024 · 2026-10-30 · Checkpoints hold only IDs and statuses
LangGraph's tables have no tenant column and sit outside RLS, so tenant data must not enter them. State carries row IDs, counts, and
statuses, and each step reads what it needs under RLS. Exceptions are stored too, so provider text and unexpected errors are replaced
before they leave a step. Checkpoints are read with the strict deserializer, because the default can construct arbitrary objects from a
stored row. They are deleted when a run succeeds, and a sweep removes the rest. LangSmith tracing is forced off, because LangGraph
ships a client for it.

### ADR-025 · 2026-10-30 · Large imports go to the worker; small ones stay in the request
The largest allowed import took 36 s when measured, which is too long for a web request. Most files are far smaller, so up to 1,000
rows still finish immediately, and the shared code means both paths behave the same. A queued file is personal data, so it is
stored only until processed and is cleared in the transaction that finishes the import.

### ADR-026 · 2026-10-31 · Identity for tools comes from the server, and every call passes one executor
A tool call is a request, not an authorization. Identity comes from a verified token or the workflow that started an agent, tool schemas
have no field for organization or user, and `mcp/registry.py:execute` checks membership, scope, role, and lead binding on every call. The
server dispatches straight to it instead of using the SDK's per-tool argument handling, so that unknown tools and malformed arguments are
refused and logged like any other call.

### ADR-027 · 2026-10-31 · Agents only read, and the quality reviewer is not a model
Planted instructions cannot be reliably detected, so what limits them is what an agent can do. Agents get a short list of read-only tools,
are bound to one lead, and have hard limits on turns, tool calls, tokens, and time. Their answers pass fixed rules. A model reviewer could
be talked past in the way Phase 4 measured. CrewAI is not used, because nothing here needs agents to collaborate. Outreach and follow-up
agents wait for what they act on to exist.

### ADR-028 · 2026-10-31 · Tools exist only where a real service stands behind them
The specification's catalog includes outreach, follow-up, and integration tools, and suggests mock implementations. The project owner ruled
out mocks (ADR-015), and a tool over nothing would be a dead control, so those tools arrive with their services in Phases 8 to 10.

### ADR-029 · 2026-10-31 · Workers have their own database role
`salesiq_worker` inherits the API role's rights inside a tenant, under the same RLS, and is alone able to use checkpoints and claim functions.
A compromised API therefore cannot claim work or write a checkpoint. The migration fails if the role is missing, because recording the
separation when it has not happened would be worse than stopping. Migrations run as a separate one-off job, so neither service holds the owner URL.

### ADR-030 · 2026-10-31 · MCP tokens are personal, revocable, and never exceed their owner
A token acts as its owner with their role at the time of each call, and a read token cannot use write tools. Changing a password or leaving an
organization revokes tokens, and a write token needs the current password to create, so a stolen session cannot mint lasting write access.
