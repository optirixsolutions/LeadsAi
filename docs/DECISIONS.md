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

### ADR-031 · 2026-10-31 · An approval is its own record, not a paused workflow
The roadmap planned to use the Phase 6 workflow interrupt. A person may take days to decide, and a paused run holds its lead and one of the
organization's 20 run slots for all of that time. So `approval_requests` stands alone, and drafts need no running worker to be reviewed.
Workflow interrupts remain for status changes proposed by a run.

### ADR-032 · 2026-10-31 · An approval covers exact text for an exact address
It stores a SHA-256 of the recipient, subject, and body. The approver's request has to carry the hash of what their screen showed, so an edit
made while they read cannot be approved by accident. Any edit ends the approval, and sending recomputes the hash from what is stored.

### ADR-033 · 2026-10-31 · At most once, even if that means asking a person
The delivery row is committed before the connection opens, and a partial unique index allows one live delivery per approval. If the connection
drops after the message starts going out, or the process dies, the outcome is `unknown`, and only a person can settle it. It never retries by
itself, because the same email twice is worse than a person having to check a log. A refusal or a failed connection sent nothing, so it can be retried.

### ADR-034 · 2026-10-31 · Sending happens in the API request, one organization at a time
Every send takes a lock on the organization's settings row while it checks and records, and releases it before connecting. This keeps limits and
the recontact rule exact under concurrency, and no database connection is held during SMTP, which has a 15-second timeout. A send is a person
clicking a button, so nothing here needs the queue until campaigns exist.

### ADR-035 · 2026-10-31 · The dispatch adapter is real SMTP, and cannot leave this machine by accident
The owner ruled out mocks (ADR-015), so tests use a real SMTP server on localhost, including real refusals and a server that hangs up. The default
is `disabled`. A host that is not a loopback address is refused unless `SALESIQ_DISPATCH_ALLOW_EXTERNAL` is set, and outside development that also
requires STARTTLS. Sending to real people needs an organization to turn sending on and a deliberate server setting, in addition to every approval.

### ADR-036 · 2026-10-31 · Approvers may approve their own requests
Reps cannot approve, which is the separation that matters: the person closest to the quota does not decide alone. A manager or admin may approve
their own request, because small teams would otherwise be stuck. The audit entry records it as `own_request`.

### ADR-037 · 2026-10-31 · Opt-out links are signed, name a delivery, and need a POST
A link names a delivery and not an address, so logs reveal nothing about the person. It never expires, because an old email still has to work. It
sets the tenant from a verified signature, which is the one route where tenancy comes from anything other than a session. A GET does nothing, because
mail scanners follow links. An opt-out cannot be removed by a person.

### ADR-038 · 2026-10-31 · Credentials are encrypted with a key kept outside the database
AES-256-GCM, with each value bound to its organization, record, and purpose, so ciphertext copied to another row does not decrypt. The key is separate from `secret_key`, and
startup refuses to run outside development without it. A password can be replaced but never read back through the API. Rotating the key itself is not built, so a lost or changed key
means entering passwords again.

### ADR-039 · 2026-10-31 · Email connects through SMTP, which needs no choice of vendor
Most email providers offer SMTP, so one adapter covers them, and building it did not need the owner to pick one. Connecting a provider still sends nothing to anyone outside this machine
without `SALESIQ_DISPATCH_ALLOW_EXTERNAL`. A tenant chooses this address, so it is treated as hostile: this machine's services are off limits outside development, other addresses must be
public and on a mail port, and a name is resolved once and that address used, so it cannot later point somewhere internal.

### ADR-040 · 2026-10-31 · Provider events use one signed format, and the tenant is trusted only after the signature
The webhook URL names an organization and connection, which proves nothing. Only a valid signature from that connection's own secret does, covering the time and the body. Providers each
have their own format, and mapping one needs choosing one, so today's format is our own. A provider's report is stored beside a delivery's outcome rather than replacing it, because
"accepted" and "delivered" are claims from different parties.

### ADR-041 · 2026-10-31 · Plans are configuration, and there is no fake payment
Limits live in `core/plans.yaml` and are checked on the server, under a lock per organization and metric. No payment provider exists, so plans change only through an owner-only adapter that
refuses to run outside development. Model tokens are charged after the fact, since a run's use is unknown beforehand: a new run is refused once the month's budget is gone, and one run can
overshoot by its own hard limit.
