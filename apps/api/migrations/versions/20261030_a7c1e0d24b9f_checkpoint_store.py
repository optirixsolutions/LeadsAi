"""checkpoint store

LangGraph's checkpoint tables, in their own schema because they are working state with no tenant
column. They hold IDs, statuses, and counts. A run's are deleted when it succeeds, and the worker's
sweep removes the rest. In its own revision because LangGraph's migrations need autocommit, and
everything here can safely run again if a deploy stops halfway.

Revision ID: a7c1e0d24b9f
Revises: 15d9ce357bc7
Create Date: 2026-10-30 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c1e0d24b9f'
down_revision: Union[str, Sequence[str], None] = '15d9ce357bc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "salesiq_app"
DEFINER_ROLE = "salesiq_definer"
SCHEMA = "workflow_state"


def upgrade() -> None:
    """Upgrade schema. A newer langgraph-checkpoint-postgres may add migrations of its own, so an
    upgrade of that package needs a new revision that runs its setup again."""
    from langgraph.checkpoint.postgres import PostgresSaver

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    with op.get_context().autocommit_block():
        raw = op.get_bind().connection.driver_connection
        raw.execute(f"SET search_path TO {SCHEMA}")
        try:
            PostgresSaver(raw).setup()
        finally:
            raw.execute("RESET search_path")

    # Failed runs stay until the retention limit, because resuming them needs the checkpoint.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION workflow_finished_threads(p_failed_retention_days int)
          RETURNS SETOF text
          LANGUAGE sql STABLE SECURITY DEFINER
          SET search_path = pg_catalog, public, pg_temp AS
          $$
            SELECT DISTINCT c.thread_id
              FROM {SCHEMA}.checkpoints c
              LEFT JOIN public.workflow_runs r ON r.id::text = c.thread_id
             WHERE r.id IS NULL
                OR r.status IN ('succeeded', 'cancelled')
                OR (r.status = 'failed'
                    AND r.finished_at < now() - make_interval(days => p_failed_retention_days))
             LIMIT 500
          $$;
        REVOKE ALL ON FUNCTION workflow_finished_threads(int) FROM PUBLIC;
    """)
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO {APP_ROLE};
            GRANT EXECUTE ON FUNCTION workflow_finished_threads(int) TO {APP_ROLE};
          ELSE
            RAISE NOTICE 'role {APP_ROLE} missing; grants skipped';
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{DEFINER_ROLE}') THEN
            GRANT USAGE ON SCHEMA {SCHEMA} TO {DEFINER_ROLE};
            GRANT SELECT ON {SCHEMA}.checkpoints TO {DEFINER_ROLE};
            ALTER FUNCTION workflow_finished_threads(int) OWNER TO {DEFINER_ROLE};
          ELSE
            RAISE NOTICE 'role {DEFINER_ROLE} missing; function stays owned by migrator';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS workflow_finished_threads(int)")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
