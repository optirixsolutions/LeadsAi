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

## Planned
| Phase | Tables |
|---|---|
| 2 | `sessions`, `invitations`, `password_reset_tokens`; RLS policies on tenant tables |
| 3 | `companies`, `leads`, `lead_sources`, `lead_imports`, `lead_activities`, `pipeline_stages`, `opportunities`, `tasks`, `custom_field_definitions` |
| 5 | `research_evidence`, `icp_configurations` (versioned), `lead_scores` |
| 6 | `workflow_runs`, `workflow_checkpoints` (LangGraph Postgres saver), `jobs` |
| 7 | `agent_definitions`, `agent_runs`, `tool_calls` |
| 8 | `outreach_drafts`, `campaigns`, `suppression_entries`, `approval_requests`, `deliveries` |
| 4/10 | `model_configurations`, `model_evaluations`, `usage_records`, `integration_connections`, `webhook_events`, `plans`, `entitlements`, `subscriptions` |

Deletion policy: tenant data cascades from `organizations`; audit logs are retained with nulled references. Hard deletion of
leads/contacts will be a soft-delete + scheduled purge job to support retention limits (Phase 10).
