# Security

## Threat model
| Threat | Primary control | Status |
|---|---|---|
| Cross-tenant data exposure / BOLA / IDOR | Org resolved from session + membership; every query scoped; RLS as backstop; isolation tests per route | Done (Phase 2) |
| Privilege escalation | Server-side permission matrix and assignable-role rules; no self role change; last-owner lock; audited | Done (Phase 2) |
| Session theft | HttpOnly, SameSite, Secure (staging/prod) cookies; hashed server-side sessions; idle + absolute expiry; revocation | Done (Phase 2); `__Host-` prefix Phase 11 |
| CSRF | SameSite=Lax + session-bound HMAC token on mutations; JSON-only pre-session endpoints | Done (Phase 2) |
| Account enumeration / credential stuffing | Uniform login errors, dummy-hash timing equalization, indistinguishable reset requests, rate limits | Done (Phase 2); lockout DoS noted in KNOWN_LIMITATIONS |
| Prompt injection via imported content | Scores never read model output; input and output gates; quarantine with human release; tool permissions in code, not prompts | Gates and scoring done (Phase 5), measured in `research/evaluations/GATES.md`, and the input gate is easy to evade by rewording; tools Phase 7 |
| Unsafe tool calls / confused deputy | Identity set by the server, never by arguments; one executor checks membership, scope, role, and binding on every call; no SQL/shell/arbitrary HTTP tools | Done (Phase 7) |
| Unauthorized external communication | Approval bound to exact text and address; final policy check at dispatch; suppression lists; no tool can approve or send; SMTP limited to loopback by default; tests for bypass | Done (Phase 8) |
| SSRF | Research fetcher with per-hop allowlist, connection pinned to a checked public IP, size limit and a deadline on every socket call | Done (Phase 5) |
| SQL injection | ORM / bound parameters only; no string-built SQL | Ongoing |
| XSS | React escaping; no `dangerouslySetInnerHTML` on untrusted content; CSP | CSP in Phase 11 |
| Webhook forgery / replay | HMAC signatures over time and body, a 5-minute window, event-ID dedupe, tenant trusted only after the signature | Done (Phase 10) |
| Resource exhaustion / abuse | Rate limits (Redis), request size caps, agent step/time/budget limits | Phases 2, 6 |
| Credential leakage | Env-only secrets; log redaction; provider credentials encrypted with AES-256-GCM, never returned, destroyed on removal | Done (Phase 10) |
| SSRF through a tenant's mail server | Internal addresses and this machine refused outside development; mail ports only; name resolved once and pinned; TLS required | Done (Phase 10); external paths untested against a real server |
| Duplicate background jobs | Leases, one active run per lead, unique per-run results | Done (Phase 6) |

## Controls implemented (Phase 1)
- Settings refuse to start in staging/production with the default or a short (<32 char) secret key.
- JSON logs redact keys matching password/secret/token/api_key/authorization/cookie/session and mask credentials in URLs.
- Error responses never include exception messages; validation errors omit submitted values.
- Readiness checks report only the exception type for failed dependencies.
- Client-supplied request IDs are validated to prevent log injection.
- Security headers on API and web: `nosniff`, `X-Frame-Options: DENY`, strict referrer policy; API responses `no-store`.
- Containers run as non-root; local infra ports bound to 127.0.0.1.
- Tests refuse to run against any database not named `*_test`.
- CI includes `pip-audit` and `pnpm audit`.

All of these are covered by tests in `apps/api/tests/test_platform.py` and `test_health.py`.

## Controls implemented (Phase 2)
| Control | Where | Tests |
|---|---|---|
| argon2id hashing, rehash on login, 12–256 char passwords | `core/security.py` | `test_auth.py` |
| Opaque 256-bit tokens; only SHA-256 digests stored (sessions, reset, verification, invitations) | `core/security.py`, `models/auth.py` | `test_tokens_are_stored_hashed` |
| Session cookie resolution, idle/absolute expiry, disabled users rejected | `core/auth.py:get_principal` | `test_auth.py` |
| CSRF HMAC bound to session; JSON-only bodies on unsafe methods | `core/auth.py`, `core/security.py` | `test_mutations_require_csrf_token`, `test_csrf_token_from_other_session_rejected` |
| Org context only from membership; 404 for non-members | `core/auth.py:get_org_context` | `test_tenancy.py` (every org route, IDOR on members and invitations) |
| RLS `FORCE` with per-command policies; app connects as non-superuser `salesiq_app`; no DELETE on organizations | migration `d6b53821b0ee` | direct-SQL tests in `test_tenancy.py`, `test_security_regressions.py` |
| Tenant context is transaction-local (`set_config(..., true)`) so pooled connections never leak it | `core/db.py` | `test_rls_context_does_not_leak_across_transactions` |
| Invitation lookup via SECURITY DEFINER owned by NOLOGIN BYPASSRLS role, pinned search_path | migration | `test_invitation_lookup_*` |
| Role rules: owners manage all, admins manage manager/rep/analyst, no self-change, last owner protected under org row lock | `core/permissions.py`, `services/org_service.py` | `test_permissions.py`, concurrency regression |
| Invitations redeemable only by the invited, verified address; locked against concurrent revoke/accept | `services/org_service.py` | `test_permissions.py`, regressions |
| Append-only audit log (app role has SELECT/INSERT only) | migration grants | `test_audit_log_is_append_only_for_app_role` |
| Redis rate limits on login, register, reset, token redemption, password change | `core/rate_limit.py`, `api/v1/auth.py` | `test_login_is_rate_limited`, `test_password_change_is_rate_limited` |
| 500s always carry the error envelope and request ID, never internals | `core/middleware.py` | `test_unhandled_error_does_not_leak_internals` |
| Web: session never readable by scripts; same-origin API via rewrites; open-redirect-safe `next` param; single-use links require a click | `apps/web` | `features/auth/schemas.test.ts`, Playwright |

## Controls implemented (Phase 3)
| Control | Where | Tests |
|---|---|---|
| RLS forced on all six CRM tables; app role has no DELETE on leads/companies/opportunities and cannot modify activities | migration `dcaf2a468d1d` | `test_crm_isolation.py` |
| Every CRM route scoped by membership; cross-org IDs return 404, cross-org references return 422 | `services/lead_service.py`, `pipeline_service.py` | `test_b_cannot_*` |
| Assignees must be org members (prevents planting foreign user IDs) | `ensure_member` | `test_owner_must_be_org_member` |
| Bulk actions filter IDs by org and lock rows | `bulk_update` | `test_bulk_ignores_other_orgs_leads` |
| Search escapes LIKE wildcards; sort keys are allowlisted | `_filtered`, `SORTS` | `test_filters_search_and_totals` |
| CSV import size/row/column caps, strict mapping, per-row validation; idempotency key prevents duplicate imports | `csv_service.py` | `test_imports.py` |
| CSV export neutralizes formula injection (`= + - @` tab, CR) and is audited; analysts and reps cannot export | `safe_cell`, permissions | `test_export_escapes_formulas_and_is_audited`, role matrix test |
| Link fields accept only http(s) (no `javascript:` links); external links open with `noopener noreferrer` | `schemas/crm.py`, lead profile | `test_unsafe_url_rejected` |
| Per-org dedupe never reveals another org's leads | unique index per org | `test_same_email_may_exist_in_two_orgs` |

## Controls implemented (Phase 5)
An independent review of this phase found no tenant breach, role bypass, XSS, or route to private IPv4 addresses. Its other
findings were fixed with tests except where KNOWN_LIMITATIONS says otherwise.
| Control | Where | Tests |
|---|---|---|
| Fetcher: HTTPS and port 443 only, no IP literals or URL credentials, allowlist on every hop, redirects capped | `integrations/fetcher.py` | `test_fetcher.py` |
| Every resolved address must be public (IPv6 limited to `2000::/3`, embedded IPv4 refused); the socket connects to the checked address, and TLS still verifies the hostname | `_PinnedBackend`, `is_public_ip` | `test_internal_addresses_are_not_public`, `test_connects_to_the_checked_address_not_a_new_lookup` |
| Total deadline applied to each socket read and write, including headers; size cap; safe charsets only; robots.txt fails closed on server errors | `_DeadlineStream`, `_safe_charset` | `test_deadline_stops_a_server_that_never_finishes_its_headers`, `test_dangerous_charset_is_not_used` |
| Scores are deterministic and read no model output; a brief cannot change one | `services/scoring.py` | `test_real_brief_cites_only_stored_evidence_and_ignores_quarantine` |
| Input gate over normalized text, plus invisible and lookalike characters; bounded patterns | `agents/gates.py` | `test_screen_*` |
| Output gate on claims, summary, and missing information: citations, support, numbers, links and addresses | `check_output` | `test_bad_claims_are_rejected_with_a_reason`, `test_links_and_addresses_not_in_the_sources_are_removed` |
| Whoever adds evidence cannot release it: release needs `intelligence:review` | `core/permissions.py` | `test_quarantined_evidence_changes_nothing_until_released` |
| Company names and all evidence sit inside the untrusted block, and data cannot close it or forge items | `evaluation/tasks.py` | `test_prompt_cannot_close_or_forge_its_data_block` |
| Provenance protected by column grants: ICP versions insert-only, review columns only on evidence and scores, no DELETE | migration `f08206afd104` | `test_rls_and_grants_protect_provenance` |
| Limits: per-user writes, per-org fetches and briefs, global model slots, evidence per lead | `api/v1/intelligence.py`, `brief_service.py` | `test_writes_are_rate_limited`, `test_one_org_cannot_run_unlimited_briefs` |
| Database errors in logs never include parameters | `core/db.py` | Not separately tested |

## Controls implemented (Phase 6)
| Control | Where | Tests |
|---|---|---|
| Workers cross tenants only through definer functions that return IDs; all later work is under the requester's RLS context | migrations, `workflows/runner.py` | `test_rls_hides_runs_without_tenant_context_and_claim_is_the_only_way_across` |
| Authority is rechecked at every step, so leaving or losing a role stops a queued run | `traced`, `worker_context` | `test_requester_who_left_cannot_keep_acting`, `test_demoted_requester_stops_at_the_next_step` |
| Status changes need a person's decision, are recorded under them, and never overwrite a newer choice | `apply_decision` | `test_decision_is_recorded_under_the_person_who_made_it`, `test_approval_does_not_overwrite_a_newer_choice` |
| Checkpoints are read strictly and hold no lead data, addresses, or provider text | `checkpoint_serde`, `_failed` | `test_checkpoint_reader_will_not_construct_objects_from_a_stored_blob`, `test_failed_run_checkpoint_holds_neither_addresses_nor_provider_text` |
| A worker that lost its lease cannot overwrite newer work | `_finish`, `write_brief` | `test_lost_lease_stops_the_old_worker_from_writing`, `test_late_answer_from_a_worker_that_lost_its_lease_is_dropped` |
| LangSmith tracing stays off, even if the environment enables it | `workflows/runner.py` | `test_tracing_stays_off_even_if_the_environment_turns_it_on` |
| Limits: active runs and queued imports per org, fair claims, rate limits on starts, resumes, and imports | services, migrations | `test_org_limit_on_active_runs`, `test_queue_of_large_imports_is_bounded_per_org` |

## Controls implemented (Phase 7)
An independent review found no authorization bypass, no cross-tenant path, and no write path an agent can reach. Its other findings were
fixed with tests except where KNOWN_LIMITATIONS says otherwise.
| Control | Where | Tests |
|---|---|---|
| Every tool call authorized and logged in one place, including refused, invalid, and unknown calls | `mcp/registry.py:execute` | `test_every_kind_of_bad_call_over_http_is_refused_and_logged` |
| Tools take no identity, and extra arguments are refused | input models, `execute` | `test_tools_cannot_be_told_who_to_act_as`, `test_arguments_cannot_smuggle_an_identity` |
| Agents: read-only tool list, one lead, hard limits on turns, tool calls, tokens, time, and result size | `agents/roles.py`, `agents/runtime.py` | `test_hostile_model_cannot_write_leave_its_lead_or_invent_tools`, `test_many_parallel_requests_cannot_exceed_the_tool_budget_or_grow_the_prompt`, `test_token_budget_ends_the_run_without_another_model_call` |
| Agent answers pass a deterministic review, and citations resolve to what the agent was shown | `agent_service.review` | `test_agent_answer_is_checked_and_traced_to_its_sources` |
| Tool results and refusals are marked as data; cancellation applies between model turns | `agents/runtime.py` | `test_refusal_text_is_marked_as_data_and_does_not_echo_the_name`, `test_cancelling_stops_an_agent_between_turns` |
| Audit log is append-only and holds validated IDs only; odd tool names cannot reach it | `tool_calls` grants, `_log_name` | `test_tool_log_is_append_only_and_tenant_scoped`, `test_odd_tool_names_cannot_write_to_the_log_or_break_the_call` |
| Tokens: digest stored, shown once, limited by scope and current role; revoked on password change and removal; write tokens need the password | `mcp/http.py`, `token_service.py` | `test_token_loses_power_as_soon_as_its_owner_does`, `test_password_change_revokes_tokens`, `test_removal_revokes_tokens_for_good`, `test_write_token_needs_the_password` |
| MCP HTTP serves only its configured host, with limits on request size and HTTPS required outside development | `mcp/http.py` | `test_http_refuses_missing_wrong_revoked_and_expired_tokens` |
| API role cannot reach checkpoints or claim functions | migration `280aff41aff2` | `test_api_role_cannot_reach_worker_only_things` |

## Database roles
| Role | Login | Superuser | BYPASSRLS | Used for |
|---|---|---|---|---|
| schema owner (`salesiq` locally) | yes | dev only | — | Alembic migrations only |
| `salesiq_app` | yes | no | no | API runtime; subject to RLS |
| `salesiq_worker` | yes | no | no | Worker runtime: the API role's rights under the same RLS, plus checkpoints and claim functions |
| `salesiq_definer` | no | no | yes | Owns `invitation_lookup()`, `workflow_claim()`, `import_claim()`, `workflow_finished_threads()` |

Every migration that adds a table must also grant `salesiq_app` exactly the privileges it needs and add RLS policies
for tenant-owned tables. `tests/test_migrations.py` checks that RLS is enabled and forced.

## Rules
- Treat model output as untrusted until schema-validated and policy-checked.
- Never log secrets, tokens, or unnecessary personal data.
- Never build SQL, shell commands, or URLs from untrusted content.
- Do not expose an unauthenticated MCP server or API beyond localhost.
