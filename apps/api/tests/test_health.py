import socket

import pytest
import redis
from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_live_reports_service_and_version(client: TestClient) -> None:
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "salesiq-api"
    assert body["version"]


def test_ready_returns_503_and_hides_detail_when_dependency_is_really_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real failure: Redis is pointed at a port with nothing listening.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(get_settings(), "redis_url", f"redis://u:hunter2@127.0.0.1:{port}/0")

    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"]["status"] == "error"
    assert body["dependencies"]["redis"]["latency_ms"] is None
    assert "hunter2" not in r.text


def test_ready_ok_against_real_dependencies(client: TestClient, db_url: str) -> None:
    try:
        redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1).ping()
    except Exception:
        pytest.skip("Redis unavailable; run `docker compose up -d redis`")
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
