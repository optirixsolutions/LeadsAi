"""Migrations apply cleanly, round-trip, and match the ORM models."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import Base

API_ROOT = Path(__file__).resolve().parents[1]


def _config(db_url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.attributes["database_url"] = db_url
    return cfg


def _reset(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()


def test_upgrade_downgrade_roundtrip(db_url: str) -> None:
    _reset(db_url)
    cfg = _config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert {"organizations", "users", "memberships", "audit_logs"} <= tables

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    engine.dispose()


def test_models_match_migrations(db_url: str) -> None:
    _reset(db_url)
    command.upgrade(_config(db_url), "head")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"Models and migrations differ; run alembic revision --autogenerate: {diff}"
