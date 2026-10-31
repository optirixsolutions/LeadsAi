# Known Limitations

Current as of Phase 11 (2026-10-31). What was verified is in RELEASE_CHECKLIST.md.

## Integrations, quotas, and billing
- **No real provider has been connected.** SMTP and webhooks were tested against a real server on this machine and real signed requests. STARTTLS, provider login, name resolution with
  pinning, and external hosts are written but have never reached a real server. A provider's own webhook format is not mapped, so a real one needs a small adapter.
- **Only email exists.** Calendars, CRMs, enrichment, OAuth, outbound webhooks, and payment are not built, because each needs a chosen provider and its credentials.
- There is no payment provider. Plans change only through the development adapter, so in production every organization stays on the default plan, unless someone edits the table.
- The encryption key cannot be rotated yet. Losing it means entering every stored password again.
- Health is checked on demand and after each send, not on a schedule, so a connection can break unnoticed between sends.
- One email connection per organization. Removing it sends the organization back to the server's own mail settings, if sending is on.
- Model tokens are counted after a run, so one run can overshoot the month's budget by its own limit. Tokens from a run that was cancelled or lost its lease are not counted. A resumed run is not counted as a new one.
- Only STARTTLS is spoken, so a provider that offers only implicit TLS on port 465 cannot connect.
- A large import is refused if its total rows would pass the lead limit, even if some are duplicates. A plan downgrade does not remove anything; it only blocks what would add more.
- Quotas are per calendar month in UTC, with no proration. Costs are estimates from configured rates, and local models have none.
- Rejected webhook requests share one limit per IP, which behind a proxy needs the forwarded-address setup in DEPLOYMENT.md.

## Analytics
- Figures are computed on each request, with no caching. On 50,000 leads the report took about 75 ms, on rows with no assessments, so larger or fully scored organizations are not measured.
- Days and all displayed times are UTC. There are no per-user time zones, and no export of a report.
- Campaign metrics do not exist, because campaigns do not. Delivery counts stop at "accepted by a mail server".
- The leads table can be filtered by fit but not sorted by score.
- Median approval wait and win rate use whatever closed in the window, however few, with the sample shown beside them. They are not forecasts.
- Screenshots of the new charts could not be taken because the app window was hidden. Their content and phone-width layout were checked by reading the page and measuring it.

## Outreach
- **No email has reached a real mailbox, or passed through a real provider.** Sending was tested only against a real SMTP server on this machine. STARTTLS,
  login, and external hosts are written but unexercised. Delivery status stops at "a mail server accepted it", with no bounce or open tracking, so a later
  bounce does not add an address to the suppression list.
- **The sender identity is not verified.** An admin can enter any sender address, and nothing here sets up SPF, DKIM, or DMARC.
- **Planted text reaches drafts, and a flag is not proof of an attack.** In the measurement, models repeated 8 of 12 attacks. Every number in model text is flagged, which fired on all 12 drafts, so
  it may stop being read, and text with no digits gets no flag from it. The person reviewing is the last line of defence. See `research/evaluations/AGENTS.md`. The link check covers only what its pattern
  recognizes, so "evil dot com" would not be flagged, and it also flags harmless text such as `Node.js`. Rewording a flagged link clears the flag.
- **Sender details are not part of an approval.** An admin who changes the sender name, address, or footer afterward changes approved email without a new approval. Only
  owners and admins can do this, and they can approve anyway, and the change is audited.
- The lead row is read but not locked during the final check, so a change at the same instant can miss it.
- A relay that reports a bad address only after accepting the message is not noticed.
- Quiet hours use the organization's time zone, not the recipient's, whose time zone is unknown.
- Suppression matches exact addresses and exact domains. A subdomain or a provider's address variants (such as `+tags`) are not covered.
- Removing a lead's email and adding it back to another lead reuses the same address, and suppression still applies, but the recontact rule looks at addresses, so it cannot
  tell two people apart who share one.
- Campaigns, sequences, and follow-ups do not exist. Each email is written, approved, and sent one at a time. Plain text only.
- A person can approve their own request if they hold `outreach:approve` (ADR-036).
- There is no retention limit on drafts or deliveries, and approved outreach is not exportable.

## Agents and MCP
- **Agent text can still carry a planted message.** Agents cannot act on it, but a reader might. See `research/evaluations/AGENTS.md`. Items an
  agent lists as unknown need no support from sources, so "call the CFO today" could pass as one, and CRM fields such as a title reach the model
  unscreened and can be cited.
- Follow-up tools and the follow-up agent do not exist yet, because follow-up tasks do not.
- `tool_calls` and agent `sources` have no retention limit. Rate-limited calls leave no row, so a flood is visible only in logs.
- Rate limits fail open if Redis is down, and the MCP server has no limit per IP for traffic without a valid token. Token lookups are by digest.
- Each model call's timeout shrinks as a run nears its time limit, but the client's retries still apply, so a run can overrun by a few calls.
- MCP metadata names an authorization server that does not exist, because tokens come from Settings, not an OAuth flow. Clients that insist on
  OAuth discovery will not connect.
- Whether Ollama truncates a long conversation at its context limit was not tested. Tool results are capped to keep this unlikely.

## Workflows
- Checkpoint tables have no tenant column and no RLS. They hold only IDs, statuses, and counts, and only the worker role can reach them.
- Runs waiting for approval never expire. They hold their lead's active slot and one of the organization's 20, until someone decides
  or cancels.
- Each start of a run counts as an attempt, and workers do not release leases on shutdown. Restarting a worker therefore delays its
  runs by up to the lease time and uses up one of three attempts.
- Worker status shows the process is alive, not that its work threads are making progress.
- A model call under way cannot be interrupted, so cancelling takes effect when it returns.
- Retries inside the model client are not shown one by one: the trace gives the count on the failed step.
- A deadline is checked between steps, so a run can overrun by up to one model call (about 9 minutes at worst).
- Imports above 1,000 rows wait for a worker, and an organization can queue 3 at a time. Each still runs as one transaction with one
  query per row (36 s for the largest file), and its file sits in the database until processed.
- A lead's page makes about 11 API calls per render, which is noticeable under load.
- Upgrading `langgraph-checkpoint-postgres` may need a new migration (see DEPLOYMENT.md).

## Sales intelligence
- **The input gate is easy to evade by rewording.** See `research/evaluations/GATES.md`. Its score on the dataset is optimistic
  because the test attacks reuse the training templates. Pages can also hide text in ways the fetcher does not strip, such as
  CSS classes or off-screen positioning.
- **Evidence text can move a score without any model.** A prospect's page or a rep's note that contains a configured keyword
  raises the score, so scores are `pending_review` until a person approves them. Nothing acts on a score automatically yet.
- Signals are keyword matches, so a need phrased differently is missed. The score has not been calibrated against outcomes
  and is not a conversion probability.
- A manager's rejection is not sticky against reworded text; only changes of case and spacing map to the same row.
- Any rep can edit a company's domain, which is the fetch allowlist. The IP checks are the real control. Domain changes and
  blocked fetches are not audited, and public suffixes such as `co.uk` are not rejected as domains.
- ICP keywords are free text, so nothing technically stops someone configuring a keyword about a personal attribute. Criteria
  fields are firmographic by design.
- Briefs come from small local models and have no human ratings.
- The Phase 4 results in `REPORT.md` predate the prompt change in version `2026-10-30.2`, which moved names inside the untrusted
  block. They were not rerun, so the live rows in `GATES.md` are the only results on the current prompt.
- The fetcher has not been run against the public internet, only real local servers, so TLS paths are unexercised by tests.
- `lead_id` foreign keys do not include `organization_id`; RLS checks the org column, and every path validates the lead first.

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
- CSV imports are capped at 5 MB / 10,000 rows in one transaction, with no progress within a run. Duplicate detection is by email
  only; leads without an email are never treated as duplicates.
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
- **CSP:** it allows inline scripts, because Next's bootstrap needs them without per-request nonces, so it limits where scripts come from and what a page can reach, but does not stop an inline injection by itself.
- `users`, `user_sessions`, and `auth_tokens` are not under RLS; the app role can read them. Isolation there relies on
  application code (every query filters by the authenticated user or a token digest).
- Not yet tested: absolute session TTL expiry, behaviour when an HTTP server omits `Content-Length` on bodies.

## Operational
- Two browser tests on mobile are flaky, unexplained: `sign out, then sign back in` failed once locally, and `a workflow runs in the background and its steps can be followed` needed CI's one retry on `23e6f8e`. Browser tests also time out when real models or image builds load the machine.
- Empty files named after fragments of code (`tuple[User`, `str`) keep appearing in `apps/api` and `apps/web`. Twelve were committed by accident. The source is not known, so check `git status` before committing.
- CI builds the images but does not run them. Running the stack in containers was done by hand, with `scripts/release_smoke.py`.
- No OpenTelemetry export, or error-monitoring integration yet (planned Phases 6, 11).
- The web build resolves the API URL for rewrites at **build time** (`SALESIQ_API_URL`); change it and rebuild per environment.
- Host port 55432 is inside Windows' ephemeral range (49152–65535), so any local process can take it as a random socket
  port. Docker then starts Postgres healthy but unpublished (`docker compose ps` shows only `5432/tcp`) and connections
  time out. Workaround: set `SALESIQ_PG_PORT`, `SALESIQ_TEST_DB_HOST`, and the database URLs to a free port below 49152.
- Playwright reuses whatever already listens on the API port, so another project on :8000 answers its requests and every test
  fails. Build and test with `SALESIQ_API_URL` set to a free port.
- `make` is unavailable in plain PowerShell; use Git Bash/WSL or the raw commands in README.
- Existing local Postgres volumes created before Phase 2 lack the `salesiq_app` and `salesiq_definer` roles; run the
  role statements from `infra/docker/postgres-init.sql` once, or recreate the volume (`docker compose down -v`).

## Tooling
- `pnpm` reports `eslint@9` as deprecated; `eslint-config-next@16.4.3` is validated against ESLint 9, so the upgrade to 10 is deferred.
- Starlette's TestClient emits a deprecation warning about `httpx`; it is filtered in pytest config until FastAPI's test client migrates.
