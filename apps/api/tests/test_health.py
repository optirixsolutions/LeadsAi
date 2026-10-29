from unittest.mock import patch

from fastapi.testclient import TestClient


def test_live_reports_service_and_version(client: TestClient) -> None:
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "salesiq-api"
    assert body["version"]


def test_ready_returns_503_and_hides_error_detail_when_dependency_down(client: TestClient) -> None:
    def boom() -> None:
        raise ConnectionError("could not connect to postgresql://u:hunter2@db:5432")

    with (
        patch("app.api.v1.health.check_database", boom),
        patch("app.api.v1.health._check_redis", lambda: None),
    ):
        r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"] == {
        "status": "error",
        "latency_ms": None,
        "error": "ConnectionError",
    }
    assert body["dependencies"]["redis"]["status"] == "ok"
    assert "hunter2" not in r.text


def test_ready_ok_against_real_dependencies(client: TestClient, db_url: str) -> None:
    import redis

    from app.core.config import get_settings

    try:
        redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1).ping()
    except Exception:
        import pytest

        pytest.skip("Redis unavailable; run `docker compose up -d redis`")
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
