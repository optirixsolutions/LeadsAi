# Known Limitations

Current as of Phase 4 (2026-10-30).

## AI evaluation
- The dataset is small, synthetic, and fictional, with rule-derived labels. Results compare methods; they do not predict
  production accuracy or conversion. No human ratings have been collected.
- The Hugging Face hosted route and the Colab paths in the notebooks have not been executed (no `HF_TOKEN` set, no Colab run).
- CI has no GPU or model, so tests that call a model skip there and run only on a machine with Ollama.
- Ollama ignores `context_tokens` from `models.yaml`. It loaded Qwen3 with a 40,960-token context, which took 9.2 GB and
  split the model 31%/69% across CPU and GPU, so its latency here is not a best case.
- Ollama's reported output tokens appear to leave out reasoning text, so token counts understate thinking runs.
- Local cost covers tokens only, not hardware or power.

## Functional
- No research, scoring, agents, or outreach in the product yet (Phases 5–8). The model layer is not wired into any API route.
- **CSV import is synchronous** and capped at 5 MB / 10,000 rows in one transaction. It becomes a durable background
  job with progress tracking when the worker lands (Phase 6). Duplicate detection is by email only; leads without an
  email are never treated as duplicates.
- No tasks/follow-ups table yet (planned with the Follow-up agent), no custom-field definitions (values are free-form
  JSON), and no saved views.
- Pipeline stages can be added and renamed but not reordered or deleted; the board shows at most 500 opportunities.
- Sales reps can edit any lead in their org, not only leads assigned to them.
- Dates and money are formatted in en-US and UTC for everyone until per-user locale settings exist.
- Sidebar entries for unbuilt modules are non-interactive and labelled with their delivery phase.
- **No real email provider.** `SALESIQ_MAILER=log` prints verification, reset, and invitation links to the API log
  (development only; startup refuses it in staging/production). With `disabled`, no emails are sent, so verification,
  password reset, and invitations cannot be completed. A provider adapter is required before any real deployment.
- An invitee must verify their email before accepting, which means two emails for a new user. A future improvement is
  to let redemption of the invite token itself verify a brand-new account.
- Pending invitations stay valid if the inviter is later demoted or removed.
- No organization deletion, ownership transfer UI, or user account deletion yet.

## Security (from the Phase 2 review, accepted for now)
- **Login lockout DoS:** the per-email login limit (10/min) lets someone who knows an address block its logins for a
  minute at a time. Planned: progressive delays plus per-IP limits weighted above per-email ones.
- **Client IP behind proxies:** rate limits key on the ASGI client address. Traffic that arrives through the Next.js
  rewrite or a load balancer shares one IP unless uvicorn's `--forwarded-allow-ips` is set to the trusted proxy and the
  proxy forwards `X-Forwarded-For`. Must be configured per deployment (see DEPLOYMENT.md).
- **Rate limiter fails open** when Redis is down (deliberate, to avoid locking everyone out; readiness reports Redis down).
- **Cookie prefixes:** cookies are not yet `__Host-` prefixed, so a compromised sibling subdomain could plant cookies.
  Planned for staging/production in Phase 11, along with a CSP.
- `users`, `user_sessions`, and `auth_tokens` are not under RLS; the app role can read them. Isolation there relies on
  application code (every query filters by the authenticated user or a token digest).
- Not yet tested: absolute session TTL expiry, behaviour when an HTTP server omits `Content-Length` on bodies.

## Operational
- GitHub Actions workflow is written but has not run; no remote repository is configured.
- No background worker, OpenTelemetry export, or error-monitoring integration yet (planned Phases 6, 11).
- The web build resolves the API URL for rewrites at **build time** (`SALESIQ_API_URL`); change it and rebuild per environment.
- Host port 55432 is inside Windows' ephemeral range (49152–65535), so any local process can take it as a random socket
  port. Docker then starts Postgres healthy but unpublished (`docker compose ps` shows only `5432/tcp`) and connections
  time out. Workaround: set `SALESIQ_PG_PORT`, `SALESIQ_TEST_DB_HOST`, and the database URLs to a free port below 49152.
- `make` is unavailable in plain PowerShell; use Git Bash/WSL or the raw commands in README.
- Existing local Postgres volumes created before Phase 2 lack the `salesiq_app` and `salesiq_definer` roles; run the
  role statements from `infra/docker/postgres-init.sql` once, or recreate the volume (`docker compose down -v`).

## Tooling
- `pnpm` reports `eslint@9` as deprecated; `eslint-config-next@16.4.3` is validated against ESLint 9, so the upgrade to 10 is deferred.
- Starlette's TestClient emits a deprecation warning about `httpx`; it is filtered in pytest config until FastAPI's test client migrates.
