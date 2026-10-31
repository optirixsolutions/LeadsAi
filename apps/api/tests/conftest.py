"""Shared fixtures.

Database tests run only against the disposable `salesiq_test` database, connecting as the
non-owner `salesiq_app` role exactly like production so row-level security is exercised.
They are skipped, not faked, when Postgres is unreachable.
"""

import contextlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

# Must be set before the app reads settings.
_HOST = os.environ.get("SALESIQ_TEST_DB_HOST", "127.0.0.1:55432")
os.environ.setdefault(
    "SALESIQ_DATABASE_URL", f"postgresql+psycopg://salesiq_app:salesiq_app@{_HOST}/salesiq_test"
)
os.environ.setdefault(
    "SALESIQ_MIGRATION_DATABASE_URL", f"postgresql+psycopg://salesiq:salesiq@{_HOST}/salesiq_test"
)
os.environ.setdefault(
    "SALESIQ_WORKER_DATABASE_URL",
    f"postgresql+psycopg://salesiq_worker:salesiq_worker@{_HOST}/salesiq_test",
)
os.environ.setdefault("SALESIQ_REDIS_URL", "redis://127.0.0.1:56379/1")
os.environ.setdefault("SALESIQ_ENVIRONMENT", "test")
os.environ.setdefault("SALESIQ_MAILER", "memory")
os.environ.setdefault("SALESIQ_DEFAULT_PLAN", "unlimited")

APP_DB_URL = os.environ["SALESIQ_DATABASE_URL"]
ADMIN_DB_URL = os.environ["SALESIQ_MIGRATION_DATABASE_URL"]
for _url in (APP_DB_URL, ADMIN_DB_URL):
    assert make_url(_url).database.endswith("_test"), "Refusing to run tests on a non-test DB"

API_ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery staple"


def _db_available() -> bool:
    try:
        engine = create_engine(ADMIN_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def ensure_app_role(admin: Engine) -> None:
    with admin.begin() as conn:
        conn.execute(
            text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salesiq_app') THEN
                CREATE ROLE salesiq_app LOGIN PASSWORD 'salesiq_app'
                  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salesiq_worker') THEN
                CREATE ROLE salesiq_worker LOGIN PASSWORD 'salesiq_worker'
                  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salesiq_definer') THEN
                CREATE ROLE salesiq_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
              END IF;
            END $$;
            """)
        )


def migrate_to_head(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.attributes["database_url"] = db_url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def db_url() -> str:
    """Admin (owner) URL of the test database; skips when Postgres is unavailable."""
    if not _db_available():
        pytest.skip("Test database unavailable; run `docker compose up -d postgres`")
    return ADMIN_DB_URL


@pytest.fixture(scope="session")
def admin_engine(db_url: str) -> Iterator[Engine]:
    engine = create_engine(db_url)
    ensure_app_role(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate_to_head(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(admin_engine: Engine) -> Engine:
    # Migration tests may rebuild the schema; make sure it is at head before truncating.
    migrate_to_head(ADMIN_DB_URL)
    with admin_engine.begin() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    return admin_engine


@pytest.fixture
def app_engine(clean_db: Engine) -> Iterator[Engine]:
    engine = create_engine(APP_DB_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def outbox() -> Iterator[list[Any]]:
    from app.integrations.mailer import get_mailer

    mailer = get_mailer()
    mailer.outbox.clear()  # type: ignore[attr-defined]
    yield mailer.outbox  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    import redis

    # Test-only Redis database (db 1); unavailable Redis just means limits fail open.
    with contextlib.suppress(redis.RedisError):
        redis.Redis.from_url(os.environ["SALESIQ_REDIS_URL"], socket_connect_timeout=1).flushdb()


@pytest.fixture
def client() -> TestClient:
    """App client that does not need the database (platform/health tests)."""
    from app.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


class Api:
    """Test client for one browser: keeps its cookies and sends the CSRF header."""

    def __init__(self) -> None:
        from app.main import create_app

        self.http = TestClient(create_app(), raise_server_exceptions=False)

    def _headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        h = {}
        if csrf := self.http.cookies.get("salesiq_csrf"):
            h["x-csrf-token"] = csrf
        return {**h, **(extra or {})}

    def get(self, path: str, **kw: Any) -> Any:
        return self.http.get(f"/api/v1{path}", **kw)

    def post(self, path: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.http.post(f"/api/v1{path}", json=json, headers=self._headers(headers))

    def patch(self, path: str, json: Any = None) -> Any:
        return self.http.patch(f"/api/v1{path}", json=json, headers=self._headers(None))

    def delete(self, path: str) -> Any:
        return self.http.request(
            "DELETE", f"/api/v1{path}", headers=self._headers({"content-type": "application/json"})
        )


@dataclass
class User:
    api: Api
    id: str
    email: str


@pytest.fixture
def make_user(clean_db: Engine, outbox: list[Any]) -> Any:
    counter = {"n": 0}

    def _make(email: str | None = None, *, verified: bool = True) -> User:
        counter["n"] += 1
        email = email or f"user{counter['n']}@example.com"
        api = Api()
        r = api.post("/auth/register", {"email": email, "password": PASSWORD})
        assert r.status_code == 201, r.text
        if verified:
            v = api.post("/auth/verify-email", {"token": token_from(outbox, "verify-email")})
            assert v.status_code == 200, v.text
        return User(api=api, id=r.json()["id"], email=email)

    return _make


@pytest.fixture
def make_org(make_user: Any) -> Any:
    """Create an owner plus organization; returns (owner, org_id)."""

    def _make(name: str = "Acme") -> tuple[User, str]:
        owner = make_user()
        r = owner.api.post("/organizations", {"name": name})
        assert r.status_code == 201, r.text
        return owner, r.json()["id"]

    return _make


def token_from(outbox: list[Any], kind: str) -> str:
    """Extract the token from the latest email whose link path matches `kind`."""
    for email in reversed(outbox):
        if m := re.search(rf"/{kind}\?token=([\w-]+)", email.body):
            return m.group(1)
    raise AssertionError(f"no {kind} email in outbox")


@pytest.fixture
def add_member(make_user: Any, outbox: list[Any]) -> Any:
    """Invite a new user into an org with `role` and accept; returns (user, membership_id)."""

    def _add(owner: User, org_id: str, role: str) -> tuple[User, str]:
        member = make_user()
        r = owner.api.post(
            f"/organizations/{org_id}/invitations", {"email": member.email, "role": role}
        )
        assert r.status_code == 201, r.text
        r = member.api.post("/invitations/accept", {"token": token_from(outbox, "invite")})
        assert r.status_code == 200, r.text
        members = owner.api.get(f"/organizations/{org_id}/members").json()
        mid = next(m["id"] for m in members if m["user_id"] == member.id)
        return member, mid

    return _add
