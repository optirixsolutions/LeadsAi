"""Shared fixtures.

Database tests run only against the disposable `salesiq_test` database. They are skipped,
not faked, when it is unreachable.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Must be set before the app module reads settings.
os.environ.setdefault(
    "SALESIQ_DATABASE_URL", "postgresql+psycopg://salesiq:salesiq@127.0.0.1:55432/salesiq_test"
)
os.environ.setdefault("SALESIQ_ENVIRONMENT", "test")
os.environ.setdefault("SALESIQ_LOG_JSON", "true")

TEST_DB_URL = os.environ["SALESIQ_DATABASE_URL"]
assert make_url(TEST_DB_URL).database.endswith("_test"), "Refusing to run tests on a non-test DB"


def _db_available() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_url() -> str:
    if not _db_available():
        pytest.skip("Test database unavailable; run `docker compose up -d postgres`")
    return TEST_DB_URL


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)
