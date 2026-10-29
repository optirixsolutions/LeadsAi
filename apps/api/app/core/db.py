"""Database engine, sessions, and per-transaction tenant context (SQLAlchemy 2.x, psycopg 3)."""

import uuid
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        pool_size=s.database_pool_size,
        pool_pre_ping=True,
        connect_args={"connect_timeout": s.database_connect_timeout_s},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Handlers commit explicitly once their work is complete, so the client never receives a
    success response for a write that later fails to commit. Anything uncommitted is rolled back.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def set_tenant_context(
    db: Session, *, user_id: uuid.UUID | None, org_id: uuid.UUID | None = None
) -> None:
    """Scope row-level security to the current transaction.

    `is_local=true` means the values vanish at commit/rollback, so a pooled connection never
    carries one request's tenant into the next. Call again after any commit.
    """
    db.execute(
        text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
        {"u": str(user_id) if user_id else "", "o": str(org_id) if org_id else ""},
    )


def check_database() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
