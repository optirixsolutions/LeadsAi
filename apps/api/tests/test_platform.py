"""Cross-cutting API behavior: errors, request IDs, security headers, config guards, logging."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.observability.logging import REDACTED, JsonFormatter, redact


def _app_with_routes() -> FastAPI:
    from app.main import create_app

    app = create_app()

    class Body(BaseModel):
        count: int

    @app.get("/_test/missing")
    def missing() -> None:
        raise NotFoundError("Lead not found")

    @app.get("/_test/crash")
    def crash() -> None:
        raise RuntimeError("db password=hunter2 leaked")

    @app.post("/_test/validate")
    def validate(body: Body) -> dict[str, int]:
        return {"count": body.count}

    return app


@pytest.fixture
def tclient() -> TestClient:
    return TestClient(_app_with_routes(), raise_server_exceptions=False)


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"] == r.headers["x-request-id"]


def test_app_error_envelope(tclient: TestClient) -> None:
    r = tclient.get("/_test/missing")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Lead not found"


def test_unhandled_error_does_not_leak_internals(tclient: TestClient) -> None:
    r = tclient.get("/_test/crash")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]
    assert "hunter2" not in r.text


def test_validation_error_does_not_echo_input(tclient: TestClient) -> None:
    r = tclient.post("/_test/validate", json={"count": "sk-secret-value"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "sk-secret-value" not in r.text


def test_request_id_generated_and_propagated(client: TestClient) -> None:
    generated = client.get("/api/v1/health/live").headers["x-request-id"]
    assert len(generated) == 32
    supplied = client.get("/api/v1/health/live", headers={"x-request-id": "abc-12345678"})
    assert supplied.headers["x-request-id"] == "abc-12345678"


def test_malicious_request_id_is_replaced(client: TestClient) -> None:
    r = client.get("/api/v1/health/live", headers={"x-request-id": "bad\nid injected"})
    assert r.headers["x-request-id"] != "bad\nid injected"


def test_security_headers_present(client: TestClient) -> None:
    h = client.get("/api/v1/health/live").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"


def test_openapi_is_served_under_v1(client: TestClient) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/health/live" in r.json()["paths"]


def test_production_refuses_default_secret() -> None:
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(environment="production").validate_for_runtime()
    with pytest.raises(RuntimeError, match="32"):
        Settings(environment="production", secret_key=SecretStr("short")).validate_for_runtime()
    with pytest.raises(RuntimeError, match="MAILER"):
        Settings(
            environment="production", secret_key=SecretStr("x" * 40), mailer="log"
        ).validate_for_runtime()
    Settings(
        environment="production",
        secret_key=SecretStr("x" * 40),
        mailer="disabled",
        credentials_key=SecretStr("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="),
    ).validate_for_runtime()


def test_redaction_masks_sensitive_keys_and_url_credentials() -> None:
    out = redact({"api_key": "abc", "nested": {"password": "p"}, "url": "postgresql://u:pw@h/db"})
    assert out["api_key"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert "pw" not in out["url"]


def test_json_formatter_emits_parseable_redacted_line() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "connect redis://u:secret@h", None, None
    )
    record.authorization = "Bearer xyz"
    line = json.loads(JsonFormatter("svc").format(record))
    assert line["service"] == "svc"
    assert "secret" not in line["msg"]
    assert line["authorization"] == REDACTED
