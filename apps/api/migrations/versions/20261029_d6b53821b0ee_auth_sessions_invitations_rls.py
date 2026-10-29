"""auth sessions invitations rls

Adds sessions, invitations, single-use auth tokens, and row-level security.

The API connects as `salesiq_app` (non-owner, non-superuser) so RLS policies apply to it.
Tenant context is set per transaction via `set_config('app.org_id', ..., true)` and
`set_config('app.user_id', ..., true)`. With no context set, tenant tables return no rows.

Revision ID: d6b53821b0ee
Revises: 625e5163de83
Create Date: 2026-10-29 23:46:40.564105

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6b53821b0ee"
down_revision: str | Sequence[str] | None = "625e5163de83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "salesiq_app"
# NOLOGIN, BYPASSRLS role that only owns invitation_lookup(); see the function comment.
DEFINER_ROLE = "salesiq_definer"
CRUD_TABLES = [
    "users",
    "memberships",
    "user_sessions",
    "invitations",
    "auth_tokens",
]
# Audit log is append-only for the application role.
APPEND_ONLY_TABLES = ["audit_logs"]
# Organizations are never deleted by the application (no endpoint; future deletion is a
# controlled job), so the app role gets no DELETE on them.
NO_DELETE_TABLES = ["organizations"]
RLS_TABLES = ["organizations", "memberships", "invitations", "audit_logs"]
POLICIES = {
    "organizations": ["org_select", "org_insert", "org_update"],
    "memberships": ["member_select", "member_insert", "member_update", "member_delete"],
    "invitations": ["tenant_isolation"],
    "audit_logs": ["tenant_isolation"],
}


def _grant_sql() -> str:
    crud = ", ".join(CRUD_TABLES)
    append = ", ".join(APPEND_ONLY_TABLES)
    no_delete = ", ".join(NO_DELETE_TABLES)
    return f"""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT USAGE ON SCHEMA public TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE, DELETE ON {crud} TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE ON {no_delete} TO {APP_ROLE};
        GRANT SELECT, INSERT ON {append} TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION invitation_lookup(text) TO {APP_ROLE};
      ELSE
        RAISE NOTICE 'role {APP_ROLE} missing; grants skipped (see docs/DEPLOYMENT.md)';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{DEFINER_ROLE}') THEN
        GRANT USAGE ON SCHEMA public TO {DEFINER_ROLE};
        GRANT SELECT ON invitations TO {DEFINER_ROLE};
        ALTER FUNCTION invitation_lookup(text) OWNER TO {DEFINER_ROLE};
      ELSE
        RAISE NOTICE 'role {DEFINER_ROLE} missing; invitation_lookup stays owned by migrator';
      END IF;
    END $$;
    """


def upgrade() -> None:
    member_role = postgresql.ENUM(name="member_role", create_type=False)

    op.create_table(
        "auth_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("password_reset", "email_verification", name="token_purpose"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index(op.f("ix_auth_tokens_user_id"), "auth_tokens", ["user_id"], unique=False)

    op.create_table(
        "invitations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", member_role, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
    )
    op.create_index(
        "ix_invitations_org_email", "invitations", ["organization_id", "email"], unique=False
    )

    op.create_table(
        "user_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)

    op.create_check_constraint("email_lowercase", "users", "email = lower(email)")

    # --- Row-level security -------------------------------------------------------------
    op.execute("""
        CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS
          $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$;
        CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS
          $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;
    """)
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Policies are per command. Reads may span the caller's own memberships (to list their
    # orgs), but every write, including DELETE, is confined to the current org context.
    op.execute("""
        CREATE POLICY org_select ON organizations FOR SELECT
          USING (
            id = app_current_org()
            OR EXISTS (
              SELECT 1 FROM memberships m
              WHERE m.organization_id = organizations.id AND m.user_id = app_current_user()
            )
          );
        CREATE POLICY org_insert ON organizations FOR INSERT
          WITH CHECK (id = app_current_org());
        CREATE POLICY org_update ON organizations FOR UPDATE
          USING (id = app_current_org()) WITH CHECK (id = app_current_org());

        CREATE POLICY member_select ON memberships FOR SELECT
          USING (organization_id = app_current_org() OR user_id = app_current_user());
        CREATE POLICY member_insert ON memberships FOR INSERT
          WITH CHECK (organization_id = app_current_org());
        CREATE POLICY member_update ON memberships FOR UPDATE
          USING (organization_id = app_current_org())
          WITH CHECK (organization_id = app_current_org());
        CREATE POLICY member_delete ON memberships FOR DELETE
          USING (organization_id = app_current_org());

        CREATE POLICY tenant_isolation ON invitations
          USING (organization_id = app_current_org())
          WITH CHECK (organization_id = app_current_org());

        CREATE POLICY tenant_isolation ON audit_logs
          USING (organization_id = app_current_org())
          WITH CHECK (organization_id = app_current_org() OR organization_id IS NULL);
    """)

    # Accepting an invitation starts with only a token, before any tenant context exists.
    # This definer function reveals the minimum needed (id, org) for one exact token hash.
    # It is owned by a dedicated NOLOGIN BYPASSRLS role (never a superuser), and its
    # search_path puts pg_temp last with a schema-qualified table, so a caller cannot
    # shadow `invitations` with a temporary table.
    op.execute("""
        CREATE FUNCTION invitation_lookup(p_token_hash text)
          RETURNS TABLE (id uuid, organization_id uuid)
          LANGUAGE sql STABLE SECURITY DEFINER
          SET search_path = pg_catalog, public, pg_temp AS
          $$ SELECT i.id, i.organization_id FROM public.invitations i
             WHERE i.token_hash = p_token_hash $$;
        REVOKE ALL ON FUNCTION invitation_lookup(text) FROM PUBLIC;
    """)
    op.execute(_grant_sql())


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS invitation_lookup(text)")
    for table, names in POLICIES.items():
        for name in names:
            op.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_current_org()")
    op.execute("DROP FUNCTION IF EXISTS app_current_user()")
    op.drop_constraint(op.f("ck_users_email_lowercase"), "users", type_="check")

    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_invitations_org_email", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index(op.f("ix_auth_tokens_user_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    sa.Enum(name="token_purpose").drop(op.get_bind(), checkfirst=True)
