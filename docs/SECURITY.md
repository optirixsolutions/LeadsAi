# Security

## Threat model
| Threat | Primary control | Status |
|---|---|---|
| Cross-tenant data exposure / BOLA / IDOR | Org resolved from session + membership; every query scoped; RLS as backstop; isolation tests per route | Phase 2 |
| Privilege escalation | Server-side permission matrix; role changes restricted to owner/admin and audited | Phase 2 |
| Session theft | HttpOnly, Secure, SameSite cookies; server-side revocable sessions; nothing in localStorage | Phase 2 |
| CSRF | SameSite=Lax + double-submit token on mutations | Phase 2 |
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

## Rules
- Treat model output as untrusted until schema-validated and policy-checked.
- Never log secrets, tokens, or unnecessary personal data.
- Never build SQL, shell commands, or URLs from untrusted content.
- Do not expose an unauthenticated MCP server or API beyond localhost.
