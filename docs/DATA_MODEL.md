# Data Model

PostgreSQL 17, managed by Alembic (`apps/api/migrations`). Conventions:
- UUID primary keys; `created_at` / `updated_at` as `timestamptz` (UTC).
- Every tenant-owned table has a non-null `organization_id` FK; queries are always scoped by it.
- Deterministic constraint names (see `models/base.py`) so autogenerate diffs stay stable.
- `tests/test_migrations.py` proves upgrade → downgrade → upgrade works and that models match migrations.

## Implemented (migration `625e5163de83`)
| Table | Key columns | Notes |
|---|---|---|
| `organizations` | `name`, `slug` (unique) | Tenant root |
| `users` | `email` (unique, stored lowercase), `password_hash`, `email_verified_at`, `disabled_at` | Global identity; tenant access via memberships |
| `memberships` | `organization_id`, `user_id`, `role` (enum) | Unique per (org, user); cascades on org/user delete |
| `audit_logs` | `organization_id?`, `actor_user_id?`, `action`, `target_type`, `target_id`, `request_id`, `data` (JSONB) | Append-only; index on (org, created_at); FKs set null so history survives deletions |

Roles: `owner`, `admin`, `manager`, `sales_rep`, `analyst`.

## Implemented (migration `d6b53821b0ee`)
| Table | Key columns | Notes |
|---|---|---|
| `user_sessions` | `user_id`, `token_hash` (unique), `expires_at`, `last_seen_at`, `revoked_at`, `ip_address`, `user_agent` | Server-side sessions; raw token never stored |
| `invitations` | `organization_id`, `email`, `role`, `token_hash`, `expires_at`, `accepted_at`, `revoked_at` | RLS; looked up by token via `invitation_lookup()` |
| `auth_tokens` | `user_id`, `purpose` (password_reset / email_verification), `token_hash`, `expires_at`, `used_at` | Single-use; newest per purpose wins |

RLS is enabled and forced on `organizations`, `memberships`, `invitations`, `audit_logs` (see SECURITY.md).

## Implemented (migration `dcaf2a468d1d`)
| Table | Key columns | Notes |
|---|---|---|
| `companies` | `name`, `domain` (normalized), `industry`, `employee_count`, `country` | Unique `(org, domain)` when set; case-insensitive name index |
| `leads` | names, `email` (lowercase), `title`, `phone`, `linkedin_url`, `source`, `status`, `tags[]`, `custom_fields` (JSONB), `company_id`, `owner_user_id`, `import_id`, `deleted_at` | Unique live email per org; soft delete only |
| `lead_imports` | `filename`, `idempotency_key`, `duplicate_policy`, `mapping`, counts, `errors` (first 100) | Unique `(org, idempotency_key)` |
| `pipeline_stages` | `name`, `position`, `kind` (open/won/lost) | Unique name per org; defaults seeded |
| `opportunities` | `name`, `stage_id`, `lead_id`, `company_id`, `owner_user_id`, `amount` (numeric 14,2), `currency`, `expected_close_date`, `closed_at` | `closed_at` set on won/lost |
| `activities` | `lead_id` and/or `opportunity_id`, `actor_user_id`, `type`, `body`, `data` | Append-only timeline |

All six have RLS enabled and forced, scoped to `app_current_org()`.

## Implemented (migration `f08206afd104`)
| Table | Key columns | Notes |
|---|---|---|
| `icp_configurations` | `version`, `criteria`, `weights` (JSONB) | Immutable: the app role can only insert. Newest version is active. Unique `(org, version)` |
| `research_evidence` | `lead_id`, `source_type`, `source_url`, `title`, `content`, `content_hash`, `status`, `screen_flags[]`, `observed_at`, reviewer | Unique `(org, lead, source_type, content_hash)`, hashed ignoring case and spacing. The app role can update only the review columns |
| `lead_scores` | `lead_id`, `icp_configuration_id`, `score` (0–100), `fit`, `components`, `reasons`, `positive_signals`, `negative_signals`, `missing_information`, `evidence_ids[]`, `model_version`, `evaluation_status`, reviewer | One row per assessment, kept as history. The app role can update only the review columns |
| `research_briefs` | `lead_id`, `status`, `model_key`, `served_by`, `prompt_version`, `summary`, `claims`, `rejected_claims`, `missing_information`, `evidence_ids[]`, `failure_category`, latency, tokens | At most one `running` per lead. Never read by scoring |

All four have RLS enabled and forced. The app role has no DELETE on any of them.

## Planned
| Phase | Tables |
|---|---|
| 3 (deferred) | `tasks`, `custom_field_definitions`, saved views |
| 6 | `workflow_runs`, `workflow_checkpoints` (LangGraph Postgres saver), `jobs` |
| 7 | `agent_definitions`, `agent_runs`, `tool_calls` |
| 8 | `outreach_drafts`, `campaigns`, `suppression_entries`, `approval_requests`, `deliveries` |
| 4/10 | `model_configurations`, `model_evaluations`, `usage_records`, `integration_connections`, `webhook_events`, `plans`, `entitlements`, `subscriptions` |

Deletion policy: tenant data cascades from `organizations`; audit logs are retained with nulled references. Hard deletion of
leads/contacts will be a soft-delete + scheduled purge job to support retention limits (Phase 10).
