# Security

## Threat model
| Threat | Primary control | Status |
|---|---|---|
| Cross-tenant data exposure / BOLA / IDOR | Org resolved from session + membership; every query scoped; RLS as backstop; isolation tests per route | Done (Phase 2) |
| Privilege escalation | Server-side permission matrix and assignable-role rules; no self role change; last-owner lock; audited | Done (Phase 2) |
| Session theft | HttpOnly, SameSite, Secure (staging/prod) cookies; hashed server-side sessions; idle + absolute expiry; revocation | Done (Phase 2); `__Host-` prefix Phase 11 |
| CSRF | SameSite=Lax + session-bound HMAC token on mutations; JSON-only pre-session endpoints | Done (Phase 2) |
| Account enumeration / credential stuffing | Uniform login errors, dummy-hash timing equalization, indistinguishable reset requests, rate limits | Done (Phase 2); lockout DoS noted in KNOWN_LIMITATIONS |
| Prompt injection via imported content | Retrieved text is data, never instructions; tool permissions enforced in code, not prompts; injection test suite | Phases 5–7 |
| Unsafe tool calls / confused deputy | MCP tools carry actor + tenant context; authorization inside each tool; no SQL/shell/arbitrary HTTP tools | Phase 7 |
| Unauthorized external communication | Approval record + final policy check at dispatch; suppression lists; tests for bypass | Phase 8 |
| SSRF | Research fetcher with allowlist, DNS-rebinding-safe IP checks, no private ranges, size/time limits | Phase 5 |
| SQL injection | ORM / bound parameters only; no string-built SQL | Ongoing |
| XSS | React escaping; no `dangerouslySetInnerHTML` on untrusted content; CSP | CSP in Phase 11 |
| Webhook forgery / replay | HMAC signatures, timestamp window, event-ID dedupe | Phase 10 |
| Resource exhaustion / abuse | Rate limits (Redis), request size caps, agent step/time/budget limits | Phases 2, 6 |
| Credential leakage | Env-only secrets; log redaction; encrypted integration tokens | Redaction done; encryption Phase 10 |
| Duplicate background jobs | Idempotency keys, row locks, unique job keys | Phase 6 |

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

## Database roles
| Role | Login | Superuser | BYPASSRLS | Used for |
|---|---|---|---|---|
| schema owner (`salesiq` locally) | yes | dev only | — | Alembic migrations only |
| `salesiq_app` | yes | no | no | API runtime; subject to RLS |
| `salesiq_definer` | no | no | yes | Owns `invitation_lookup()` only |

Every migration that adds a table must also grant `salesiq_app` exactly the privileges it needs and add RLS policies
for tenant-owned tables. `tests/test_migrations.py` checks that RLS is enabled and forced.

## Rules
- Treat model output as untrusted until schema-validated and policy-checked.
- Never log secrets, tokens, or unnecessary personal data.
- Never build SQL, shell commands, or URLs from untrusted content.
- Do not expose an unauthenticated MCP server or API beyond localhost.
