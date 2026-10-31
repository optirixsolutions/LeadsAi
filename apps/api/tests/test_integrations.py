"""Phase 10: connections, credentials, signed webhooks, plans, and quotas.

Real database and roles, a real SMTP server on localhost, and real signed HTTP requests.
"""

import base64
import json
import socket
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.core.config import Settings, get_settings
from app.core.crypto import CredentialError, decrypt, encrypt
from app.core.db import get_sessionmaker
from app.integrations.dispatch import SmtpTarget, send_smtp, target_blocker
from app.mcp.registry import Identity, execute
from app.mcp.tools import CATALOG
from app.services.webhook_service import sign
from tests.support.smtp_sink import Sink, running_sink
from tests.test_outreach import _approved, _configure, _detail, _lead, _send
from tests.test_outreach import smtp as smtp

PASSWORD_VALUE = "a-provider-password-nobody-should-see"


@pytest.fixture
def org_sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Sink, int]]:
    """A mail server chosen by an organization, while the server's own setting points elsewhere."""
    with running_sink() as (sink, port):
        settings = get_settings()
        monkeypatch.setattr(settings, "dispatch_adapter", "smtp")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            monkeypatch.setattr(settings, "dispatch_smtp_port", probe.getsockname()[1])
        yield sink, port


def _connect(user: Any, org: str, port: int, **kw: Any) -> Any:
    body = {
        "name": "Mail",
        "host": "127.0.0.1",
        "port": port,
        "starttls": False,
        "password": PASSWORD_VALUE,
        "username": "apikey",
        **kw,
    }
    return user.api.post(f"/organizations/{org}/integrations/email", body)


def _signed(user: Any, connection: dict[str, Any], event: dict[str, Any], **kw: Any) -> Any:
    body = json.dumps(event).encode()
    timestamp = str(kw.pop("at", int(time.time())))
    secret = kw.pop("secret", connection["webhook_secret"])
    headers = {
        "content-type": "application/json",
        "x-salesiq-timestamp": timestamp,
        "x-salesiq-signature": kw.pop("signature", sign(secret, timestamp, body)),
    }
    return user.api.http.post(connection["webhook_path"], content=body, headers=headers)


def _sent_delivery(owner: Any, org: str) -> dict[str, Any]:
    detail = _approved(owner, org)
    r = _send(owner, org, detail["id"])
    assert r.json()["status"] == "accepted", r.text
    return r.json()


# --- credentials ----------------------------------------------------------------------------


def test_encryption_is_bound_to_its_place() -> None:
    sealed = encrypt("secret", context="a")
    assert "secret" not in sealed and decrypt(sealed, context="a") == "secret"
    assert encrypt("secret", context="a") != sealed
    with pytest.raises(CredentialError):
        decrypt(sealed, context="b")
    with pytest.raises(CredentialError):
        decrypt("plain text", context="a")


def test_a_changed_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    sealed = encrypt("secret", context="a")
    key = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setattr(get_settings(), "credentials_key", SecretStr(key))
    with pytest.raises(CredentialError):
        decrypt(sealed, context="a")
    monkeypatch.setattr(get_settings(), "credentials_key", SecretStr("too-short"))
    with pytest.raises(CredentialError):
        encrypt("secret", context="a")


def test_startup_outside_development_needs_a_credentials_key() -> None:
    base: dict[str, Any] = {
        "environment": "production",
        "secret_key": "x" * 40,
        "mailer": "disabled",
        "_env_file": None,
    }
    with pytest.raises(RuntimeError, match="CREDENTIALS_KEY"):
        Settings(**base).validate_for_runtime()
    Settings(**base, credentials_key=base64.b64encode(b"k" * 32).decode()).validate_for_runtime()


def test_secrets_are_stored_encrypted_and_never_returned(
    make_org: Any, clean_db: Engine, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    r = _connect(owner, org, org_sink[1])
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["webhook_secret"].startswith("whsec_")
    assert PASSWORD_VALUE not in r.text and created["has_password"] is True

    listed = owner.api.get(f"/organizations/{org}/integrations")
    assert PASSWORD_VALUE not in listed.text and "whsec_" not in listed.text
    assert listed.json()["connections"][0]["has_password"] is True

    with clean_db.begin() as conn:
        row = conn.execute(text("SELECT * FROM integration_connections")).one()
        log = conn.execute(text("SELECT data::text FROM audit_logs")).scalars().all()
    assert row.encrypted_password.startswith("v1:") and PASSWORD_VALUE not in row.encrypted_password
    assert not any(PASSWORD_VALUE in entry or "whsec_" in entry for entry in log)
    assert PASSWORD_VALUE not in json.dumps(row.config)


def test_removing_a_connection_destroys_its_secrets(
    make_org: Any, clean_db: Engine, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    created = _connect(owner, org, org_sink[1]).json()
    url = f"/organizations/{org}/integrations/{created['id']}"
    assert owner.api.delete(url).status_code == 204
    with clean_db.begin() as conn:
        row = conn.execute(text("SELECT * FROM integration_connections")).one()
    assert row.encrypted_password is None and row.encrypted_webhook_secret is None
    assert owner.api.get(f"/organizations/{org}/integrations").json()["connections"] == []
    # And a new one can be made.
    assert _connect(owner, org, org_sink[1]).status_code == 201


def test_only_owners_and_admins_can_touch_connections(
    make_org: Any, add_member: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    created = _connect(owner, org, org_sink[1]).json()
    for role in ("manager", "sales_rep", "analyst"):
        member, _ = add_member(owner, org, role)
        assert _connect(member, org, org_sink[1]).status_code == 403
        url = f"/organizations/{org}/integrations/{created['id']}"
        assert member.api.delete(url).status_code == 403
        assert member.api.post(f"{url}/check").status_code == 403
        assert member.api.post(f"{url}/rotate-webhook-secret").status_code == 403
    admin, _ = add_member(owner, org, "admin")
    r = admin.api.post(f"/organizations/{org}/integrations/{created['id']}/check")
    assert r.status_code == 200


def test_another_organization_cannot_reach_a_connection(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    other, other_org = make_org("Other")
    created = _connect(owner, org, org_sink[1]).json()
    assert other.api.get(f"/organizations/{org}/integrations").status_code == 404
    url = f"/organizations/{other_org}/integrations/{created['id']}"
    assert other.api.delete(url).status_code == 404
    assert other.api.post(f"{url}/check").status_code == 404
    assert other.api.patch(url, {"name": "Mine"}).status_code == 404


def test_one_email_connection_at_a_time(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    assert _connect(owner, org, org_sink[1]).status_code == 201
    r = _connect(owner, org, org_sink[1])
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_connected"


# --- which servers can be reached ------------------------------------------------------------


def test_a_tenant_cannot_aim_a_connection_at_internal_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    assert target_blocker("mail.example.com", 587, True) == "external_not_allowed"
    assert target_blocker("127.0.0.1", 6379, False) is None  # Development and tests only.
    monkeypatch.setattr(settings, "environment", "production")
    assert target_blocker("127.0.0.1", 6379, False) == "connection_host_refused"
    assert target_blocker("localhost", 25, True) == "connection_host_refused"
    assert target_blocker("::1", 25, True) == "connection_host_refused"
    monkeypatch.setattr(settings, "dispatch_allow_external", True)
    assert target_blocker("mail.example.com", 587, True) is None
    assert target_blocker("mail.example.com", 6379, True) == "connection_host_refused"
    assert target_blocker("mail.example.com", 587, False) == "connection_needs_tls"


@pytest.mark.parametrize(
    "host",
    ["10.0.0.1", "169.254.169.254", "192.168.1.1", "fe80::1", "0.0.0.0"],  # noqa: S104
)
def test_private_addresses_are_refused_at_the_moment_of_connecting(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with the switch on: this is what a name resolving somewhere internal comes down to."""
    settings = get_settings()
    monkeypatch.setattr(settings, "dispatch_adapter", "smtp")
    monkeypatch.setattr(settings, "dispatch_allow_external", True)
    from app.integrations.dispatch import OutgoingEmail

    email = OutgoingEmail("a@example.com", "S", "s@example.com", "Subject", "Body", "https://x/y")
    target = SmtpTarget(host.strip("[]"), 587, True, from_connection=True)
    outcome = send_smtp(email, target)
    assert outcome.status.value == "failed" and outcome.category == "connection_host_refused"


def test_a_connection_outside_policy_cannot_be_saved(make_org: Any) -> None:
    owner, org = make_org()
    r = _connect(owner, org, 587, host="mail.example.com", starttls=True)
    assert r.status_code == 400 and r.json()["error"]["code"] == "external_not_allowed"
    assert _connect(owner, org, 25, host="bad host!").status_code == 422


# --- health ---------------------------------------------------------------------------------


def test_a_check_reports_real_health_and_sends_nothing(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    sink, port = org_sink
    owner, org = make_org()
    created = _connect(owner, org, port, username=None, password=None).json()
    assert created["health"] == "unknown"
    url = f"/organizations/{org}/integrations/{created['id']}"
    r = owner.api.post(f"{url}/check")
    assert r.json()["health"] == "ok" and r.json()["last_checked_at"]
    assert sink.messages == []

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert owner.api.patch(url, {"port": closed}).json()["health"] == "unknown"
    r = owner.api.post(f"{url}/check")
    assert r.json()["health"] == "failing"
    assert r.json()["last_error_category"] == "connection_failed"
    a = owner.api.get(f"/organizations/{org}/analytics/attention").json()
    assert a["integrations_failing"] == 1


def test_health_is_available_to_mcp_without_credentials(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    _connect(owner, org, org_sink[1])
    identity = Identity(org_id=uuid.UUID(org), user_id=uuid.UUID(owner.id))
    result = execute(CATALOG, identity, "get_integration_health", {}, get_sessionmaker())
    assert result.ok and result.output["connections"][0]["health"] == "unknown"
    assert PASSWORD_VALUE not in json.dumps(result.output) and "whsec_" not in json.dumps(
        result.output
    )
    assert "127.0.0.1" not in json.dumps(result.output)


# --- sending through a connection ------------------------------------------------------------


def test_an_organizations_connection_carries_its_email(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    sink, port = org_sink
    owner, org = make_org()
    _configure(owner, org)
    created = _connect(owner, org, port, username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    assert delivery["adapter"] == "smtp_connection" and len(sink.messages) == 1
    listed = owner.api.get(f"/organizations/{org}/integrations").json()["connections"][0]
    assert listed["id"] == created["id"] and listed["health"] == "ok"


def test_a_failing_connection_marks_itself_and_sends_nothing(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    _configure(owner, org)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    _connect(owner, org, closed, username=None, password=None)
    detail = _approved(owner, org)
    assert _send(owner, org, detail["id"]).json()["status"] == "failed"
    listed = owner.api.get(f"/organizations/{org}/integrations").json()["connections"][0]
    assert listed["health"] == "failing"
    assert org_sink[0].messages == []


def test_an_unreadable_password_stops_the_send_before_it_starts(
    make_org: Any, org_sink: tuple[Sink, int], clean_db: Engine
) -> None:
    owner, org = make_org()
    _configure(owner, org)
    _connect(owner, org, org_sink[1])
    detail = _approved(owner, org)
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE integration_connections "
                "SET encrypted_password = 'v1:AAAAAAAAAAAAAAAAAAAAAAAA'"
            )
        )
    r = _send(owner, org, detail["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "credential_unreadable"
    after = _detail(owner, org, detail["id"])
    assert after["status"] == "approved" and after["deliveries"] == []


# --- webhooks -------------------------------------------------------------------------------


def _event(message_id: str, kind: str = "delivered", event_id: str = "e1") -> dict[str, Any]:
    return {"id": event_id, "type": kind, "message_id": message_id}


def test_a_signed_event_updates_the_delivery(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    _configure(owner, org)
    connection = _connect(owner, org, org_sink[1], username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    r = _signed(owner, connection, _event(delivery["message_id"]))
    assert r.status_code == 200 and r.json() == {"result": "applied"}
    detail = _detail(owner, org, delivery["draft_id"])
    assert detail["deliveries"][0]["provider_status"] == "delivered"
    assert detail["deliveries"][0]["status"] == "accepted"


def test_forged_old_and_replayed_events_do_nothing(
    make_org: Any, org_sink: tuple[Sink, int], clean_db: Engine
) -> None:
    owner, org = make_org()
    _configure(owner, org)
    connection = _connect(owner, org, org_sink[1], username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    event = _event(delivery["message_id"], "bounced")

    assert _signed(owner, connection, event, secret="whsec_wrong").status_code == 401
    assert _signed(owner, connection, event, signature="v1=00").status_code == 401
    old = int(time.time()) - 3600
    assert _signed(owner, connection, event, at=old).status_code == 401
    assert _signed(owner, connection, event, at="soon").status_code == 401
    unsigned = owner.api.http.post(connection["webhook_path"], json=event)
    assert unsigned.status_code == 401
    # A signature for one body does not cover another.
    stamp = str(int(time.time()))
    other = sign(connection["webhook_secret"], stamp, b"{}")
    r = owner.api.http.post(
        connection["webhook_path"],
        json=event,
        headers={"x-salesiq-timestamp": stamp, "x-salesiq-signature": other},
    )
    assert r.status_code == 401
    assert owner.api.get(f"/organizations/{org}/outreach/suppressions").json() == []

    assert _signed(owner, connection, event).json() == {"result": "applied"}
    assert _signed(owner, connection, event).json() == {"result": "duplicate"}
    with clean_db.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM webhook_events")).scalar() == 1


def test_rotating_the_secret_ends_the_old_one(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    url = f"/organizations/{org}/integrations/{connection['id']}/rotate-webhook-secret"
    new = owner.api.post(url).json()["webhook_secret"]
    assert new != connection["webhook_secret"]
    event = _event("<nothing@example.com>")
    assert _signed(owner, connection, event).status_code == 401
    assert _signed(owner, connection, event, secret=new).json() == {"result": "ignored"}


def test_one_organizations_secret_cannot_touch_anothers_delivery(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    other, other_org = make_org("Other")
    _configure(owner, org)
    mine = _connect(owner, org, org_sink[1], username=None, password=None).json()
    theirs = _connect(other, other_org, org_sink[1], username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    event = _event(delivery["message_id"], "bounced")
    # Their valid event names my message, and it finds nothing.
    assert _signed(other, theirs, event).json() == {"result": "ignored"}
    assert _detail(owner, org, delivery["draft_id"])["deliveries"][0]["provider_status"] is None
    # Their secret on my address is simply wrong.
    forged = {**mine, "webhook_secret": theirs["webhook_secret"]}
    assert _signed(other, forged, event).status_code == 401
    # My secret against an organization in the path that is not mine finds no connection.
    moved = {**mine, "webhook_path": f"/api/v1/webhooks/email/{other_org}/{mine['id']}"}
    assert _signed(owner, moved, event).status_code == 401


def test_a_bounce_and_a_complaint_stop_future_email(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    _configure(owner, org)
    connection = _connect(owner, org, org_sink[1], username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    url = f"/organizations/{org}/outreach/suppressions"
    _signed(owner, connection, _event(delivery["message_id"], "bounced"))
    assert [e["reason"] for e in owner.api.get(url).json()] == ["bounced"]
    # A late delivered event does not hide the bounce.
    _signed(owner, connection, _event(delivery["message_id"], "delivered", "e2"))
    detail = _detail(owner, org, delivery["draft_id"])
    assert detail["deliveries"][0]["provider_status"] == "bounced"
    _signed(owner, connection, _event(delivery["message_id"], "complained", "e3"))
    entries = owner.api.get(url).json()
    assert [e["reason"] for e in entries] == ["opt_out"]
    assert owner.api.delete(f"{url}/{entries[0]['id']}").status_code == 409


def test_a_valid_signature_on_nonsense_is_refused(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    r = _signed(owner, connection, {"id": "x", "type": "exploded", "message_id": "m"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_event"


def test_an_oversized_event_is_refused(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    r = owner.api.http.post(connection["webhook_path"], content=b"x" * (64 * 1024 + 1))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_large"


def test_a_removed_connection_takes_no_events(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    owner.api.delete(f"/organizations/{org}/integrations/{connection['id']}")
    assert _signed(owner, connection, _event("<m@x>")).status_code == 401


def test_forgeries_cannot_block_real_events(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    codes = [
        _signed(owner, connection, _event("<m@x>"), secret="whsec_wrong").status_code
        for _ in range(32)
    ]
    assert codes[0] == 401 and codes[-1] == 429
    assert _signed(owner, connection, _event("<m@x>")).status_code == 200


# --- plans and quotas ------------------------------------------------------------------------


def _plan(owner: Any, org: str, plan: str) -> None:
    r = owner.api.post(f"/organizations/{org}/billing/development-plan", {"plan": plan})
    assert r.status_code == 200, r.text


def _quota(r: Any, metric: str) -> None:
    assert r.status_code == 402, r.text
    assert r.json()["error"]["code"] == "quota_exceeded"
    assert r.json()["error"]["details"]["metric"] == metric


def _limit(monkeypatch: pytest.MonkeyPatch, metric: str, value: int) -> None:
    from app.services import quota_service

    plan = quota_service.all_plans()["free"]
    monkeypatch.setitem(plan.limits, metric, value)


def test_usage_reports_the_plan_and_real_counts(make_org: Any) -> None:
    owner, org = make_org()
    _lead(owner, org)
    r = owner.api.get(f"/organizations/{org}/usage").json()
    assert r["plan"]["key"] == "unlimited" and r["source"] == "default"
    metrics = {m["metric"]: m for m in r["metrics"]}
    assert metrics["leads"]["used"] == 1 and metrics["leads"]["limit"] is None
    assert metrics["seats"]["used"] == 1
    assert r["development_billing"] is True and r["estimated_cost_usd"] is None
    _plan(owner, org, "free")
    r = owner.api.get(f"/organizations/{org}/usage").json()
    assert r["plan"]["key"] == "free" and r["source"] == "development"
    assert {m["metric"]: m["limit"] for m in r["metrics"]}["seats"] == 3


def test_the_development_billing_adapter_refuses_production(
    make_org: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org = make_org()
    monkeypatch.setattr(get_settings(), "environment", "staging")
    r = owner.api.post(f"/organizations/{org}/billing/development-plan", {"plan": "unlimited"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "billing_unavailable"


def test_only_an_owner_can_change_the_plan(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    admin, _ = add_member(owner, org, "admin")
    url = f"/organizations/{org}/billing/development-plan"
    assert admin.api.post(url, {"plan": "free"}).status_code == 403
    assert owner.api.post(url, {"plan": "nonsense"}).json()["error"]["code"] == "unknown_plan"
    assert admin.api.get(f"/organizations/{org}/usage").status_code == 200


def test_the_lead_limit_covers_every_way_in(make_org: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "leads", 2)
    url = f"/organizations/{org}/leads"
    assert owner.api.post(url, {"first_name": "A"}).status_code == 201
    r = owner.api.post(
        f"/organizations/{org}/lead-imports",
        {
            "filename": "x.csv",
            "content": "email\na@example.com\nb@example.com\n",
            "mapping": {"email": "email"},
            "duplicate_policy": "skip",
        },
    )
    _quota(r, "leads")
    assert owner.api.post(url, {"first_name": "B"}).status_code == 201
    _quota(owner.api.post(url, {"first_name": "C"}), "leads")
    identity = Identity(org_id=uuid.UUID(org), user_id=uuid.UUID(owner.id), scope=_write())
    result = execute(CATALOG, identity, "create_lead", {"first_name": "D"}, get_sessionmaker())
    assert result.error_category == "quota_exceeded"


def _write() -> Any:
    from app.models import TokenScope

    return TokenScope.write


def test_a_deleted_lead_frees_its_place(make_org: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "leads", 1)
    url = f"/organizations/{org}/leads"
    lead = owner.api.post(url, {"first_name": "A"}).json()["id"]
    _quota(owner.api.post(url, {"first_name": "B"}), "leads")
    owner.api.delete(f"{url}/{lead}")
    assert owner.api.post(url, {"first_name": "B"}).status_code == 201


def test_seats_count_members_and_pending_invitations(
    make_org: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "seats", 2)
    url = f"/organizations/{org}/invitations"
    assert owner.api.post(url, {"email": "a@example.com", "role": "analyst"}).status_code == 201
    # Sending it again replaces it, and takes no new seat.
    assert owner.api.post(url, {"email": "a@example.com", "role": "analyst"}).status_code == 201
    _quota(owner.api.post(url, {"email": "b@example.com", "role": "analyst"}), "seats")


def test_runs_stop_at_their_limit(make_org: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_workflow_runs", 1)
    url = f"/organizations/{org}/agents/pipeline/runs"
    assert owner.api.post(url, {}).status_code == 202
    _quota(owner.api.post(url, {}), "monthly_workflow_runs")


def test_runs_stop_when_the_token_budget_is_gone(
    make_org: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_model_tokens", 100)
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usage_records (id, organization_id, kind, quantity) "
                "VALUES (gen_random_uuid(), :o, 'model_tokens', 100)"
            ),
            {"o": org},
        )
    r = owner.api.post(f"/organizations/{org}/agents/pipeline/runs", {})
    _quota(r, "monthly_model_tokens")


def test_last_months_usage_does_not_count(
    make_org: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_model_tokens", 100)
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usage_records (id, organization_id, kind, quantity, created_at) "
                "VALUES (gen_random_uuid(), :o, 'model_tokens', 100, "
                "date_trunc('month', now()) - interval '1 day')"
            ),
            {"o": org},
        )
    assert owner.api.post(f"/organizations/{org}/agents/pipeline/runs", {}).status_code == 202


def test_the_free_plan_has_no_integrations(make_org: Any, org_sink: tuple[Sink, int]) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _quota(_connect(owner, org, org_sink[1]), "integrations")
    assert (
        owner.api.get(f"/organizations/{org}/integrations").json()["integrations_included"] is False
    )


def test_the_email_limit_is_a_send_blocker(
    make_org: Any, smtp: Sink, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_emails", 1)
    _configure(owner, org, recontact_days=0)
    first = _approved(owner, org)
    assert first["blockers"] == []
    assert _send(owner, org, first["id"]).json()["status"] == "accepted"
    second = _approved(owner, org, _lead(owner, org, "other@example.com"))
    assert [b["code"] for b in second["blockers"]] == ["monthly_email_limit"]
    r = _send(owner, org, second["id"])
    assert r.status_code == 409 and r.json()["error"]["details"][0]["code"] == "monthly_email_limit"
    assert len(smtp.messages) == 1
    used = owner.api.get(f"/organizations/{org}/usage").json()["metrics"]
    assert {m["metric"]: m["used"] for m in used}["monthly_emails"] == 1


def test_one_organizations_usage_is_its_own(make_org: Any) -> None:
    owner, org = make_org()
    other, other_org = make_org("Other")
    _lead(owner, org)
    used = other.api.get(f"/organizations/{other_org}/usage").json()["metrics"]
    assert {m["metric"]: m["used"] for m in used}["leads"] == 0
    assert other.api.get(f"/organizations/{org}/usage").status_code == 404


# --- the review's findings ------------------------------------------------------------------


def test_a_stored_password_does_not_follow_a_connection_somewhere_new(
    make_org: Any, org_sink: tuple[Sink, int], clean_db: Engine
) -> None:
    owner, org = make_org()
    created = _connect(owner, org, org_sink[1]).json()
    url = f"/organizations/{org}/integrations/{created['id']}"
    for change in ({"host": "localhost"}, {"port": 2525}, {"username": "me"}, {"starttls": True}):
        r = owner.api.patch(url, change)
        assert r.status_code == 400 and r.json()["error"]["code"] == "password_required", change
    # A name is not a destination, and knowing the password is enough for the rest.
    assert owner.api.patch(url, {"name": "Renamed"}).status_code == 200
    r = owner.api.patch(url, {"host": "localhost", "password": PASSWORD_VALUE})
    assert r.status_code == 200 and r.json()["host"] == "localhost"
    r = owner.api.patch(url, {"port": 2525, "password": None})
    assert r.status_code == 200 and r.json()["has_password"] is False
    assert owner.api.patch(url, {"port": 2526}).status_code == 200
    assert owner.api.patch(url, {"port": None}).status_code == 422


def test_a_downgraded_organization_stops_using_its_connection(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    sink, port = org_sink
    owner, org = make_org()
    _configure(owner, org)
    created = _connect(owner, org, port, username=None, password=None).json()
    detail = _approved(owner, org)
    _plan(owner, org, "free")
    url = f"/organizations/{org}/integrations/{created['id']}"
    _quota(owner.api.post(f"{url}/check"), "integrations")
    _quota(owner.api.patch(url, {"name": "New"}), "integrations")
    r = _send(owner, org, detail["id"])
    assert r.status_code == 409
    assert "integrations_not_included" in [d["code"] for d in r.json()["error"]["details"]]
    assert sink.messages == []
    # Removing it, which is the way out, still works.
    assert owner.api.delete(url).status_code == 204


def test_queued_imports_are_checked_again_when_they_run(
    make_org: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import csv_service
    from app.workflows.runner import drain

    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "leads", 1500)
    monkeypatch.setattr(csv_service, "SYNC_ROW_LIMIT", 2)
    url = f"/organizations/{org}/lead-imports"

    def file(tag: str) -> dict[str, Any]:
        rows = "\n".join(f"{tag}{n}@example.com" for n in range(1000))
        return {
            "filename": f"{tag}.csv",
            "content": f"email\n{rows}\n",
            "mapping": {"email": "email"},
            "duplicate_policy": "skip",
        }

    first = owner.api.post(url, file("a"))
    second = owner.api.post(url, file("b"))
    assert first.json()["status"] == second.json()["status"] == "queued"
    drain()
    done = [owner.api.get(f"{url}/{r.json()['id']}").json()["status"] for r in (first, second)]
    assert sorted(done) == ["completed", "failed"]
    assert owner.api.get(f"/organizations/{org}/leads?limit=1").json()["total"] == 1000


def test_a_queued_run_stops_if_the_budget_goes_while_it_waits(
    make_org: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows.runner import drain

    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_model_tokens", 100)
    r = owner.api.post(f"/organizations/{org}/agents/pipeline/runs", {})
    assert r.status_code == 202
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usage_records (id, organization_id, kind, quantity) "
                "VALUES (gen_random_uuid(), :o, 'model_tokens', 100)"
            ),
            {"o": org},
        )
    drain()
    run = r.json()["workflow_run_id"]
    detail = owner.api.get(f"/organizations/{org}/workflows/{run}").json()
    assert detail["status"] == "failed" and detail["error_category"] == "quota_exceeded"
    resumed = owner.api.post(f"/organizations/{org}/workflows/{run}/resume")
    _quota(resumed, "monthly_model_tokens")


def test_an_email_of_unknown_outcome_counts_toward_the_limit(
    make_org: Any, org_sink: tuple[Sink, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support.smtp_sink import DROP_AFTER_DATA

    port = org_sink[1]
    monkeypatch.setattr(get_settings(), "dispatch_smtp_port", port)
    owner, org = make_org()
    _plan(owner, org, "free")
    _limit(monkeypatch, "monthly_emails", 1)
    _configure(owner, org, recontact_days=0)
    first = _approved(owner, org, _lead(owner, org, f"{DROP_AFTER_DATA}example.com"))
    assert _send(owner, org, first["id"]).json()["status"] == "unknown"
    second = _approved(owner, org, _lead(owner, org, "other@example.com"))
    assert [b["code"] for b in second["blockers"]] == ["monthly_email_limit"]


def test_an_event_can_arrive_while_the_email_is_still_going_out(
    make_org: Any, org_sink: tuple[Sink, int], clean_db: Engine
) -> None:
    """The Message-ID is stored before the connection opens."""
    owner, org = make_org()
    _configure(owner, org)
    connection = _connect(owner, org, org_sink[1], username=None, password=None).json()
    delivery = _sent_delivery(owner, org)
    assert org_sink[0].messages[0]["Message-ID"] == delivery["message_id"]
    # An event for a message not known yet is not kept, so the provider's retry still counts.
    event = _event("<later@example.com>")
    assert _signed(owner, connection, event).json() == {"result": "ignored"}
    assert _signed(owner, connection, event).json() == {"result": "ignored"}
    with clean_db.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM webhook_events")).scalar() == 0


def test_a_signature_with_odd_characters_is_a_plain_refusal(
    make_org: Any, org_sink: tuple[Sink, int]
) -> None:
    owner, org = make_org()
    connection = _connect(owner, org, org_sink[1]).json()
    r = _signed(owner, connection, _event("<m@x>"), signature="v1=é".encode())
    assert r.status_code == 401


def test_startup_refuses_a_bad_plan_or_key() -> None:
    with pytest.raises(RuntimeError, match="DEFAULT_PLAN"):
        Settings(default_plan="nonsense", _env_file=None).validate_for_runtime()  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="32 bytes"):
        Settings(
            credentials_key=base64.b64encode(b"short").decode(),  # type: ignore[arg-type]
            _env_file=None,  # type: ignore[call-arg]
        ).validate_for_runtime()
    with pytest.raises(RuntimeError, match="base64"):
        Settings(credentials_key="not base64!", _env_file=None).validate_for_runtime()  # type: ignore[arg-type,call-arg]


def test_port_465_is_not_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dispatch_allow_external", True)
    assert target_blocker("mail.example.com", 465, True) == "connection_host_refused"
