"""Authentication: registration, login, sessions, CSRF, password reset, email verification."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from tests.conftest import PASSWORD, Api, token_from


def test_register_sets_secure_session_cookies(clean_db: Engine, outbox: list[Any]) -> None:
    api = Api()
    r = api.post("/auth/register", {"email": "  Ana@Example.COM ", "password": PASSWORD})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "ana@example.com"
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("salesiq_session="))
    csrf = next(c for c in cookies if c.startswith("salesiq_csrf="))
    assert "HttpOnly" in session and "SameSite=lax" in session
    assert "HttpOnly" not in csrf
    assert api.get("/auth/me").json()["user"]["email"] == "ana@example.com"


def test_duplicate_registration_conflicts_case_insensitively(make_user: Any) -> None:
    make_user("dup@example.com")
    r = Api().post("/auth/register", {"email": "DUP@example.com", "password": PASSWORD})
    assert r.status_code == 409


def test_short_password_rejected(clean_db: Engine) -> None:
    r = Api().post("/auth/register", {"email": "a@example.com", "password": "Zq9!xk"})
    assert r.status_code == 422
    assert "Zq9!xk" not in r.text


def test_registration_can_be_disabled(clean_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "registration_enabled", False)
    r = Api().post("/auth/register", {"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "registration_disabled"


def test_login_failures_do_not_reveal_which_part_was_wrong(make_user: Any) -> None:
    u = make_user()
    wrong_pw = Api().post("/auth/login", {"email": u.email, "password": "x" * 12})
    no_user = Api().post("/auth/login", {"email": "nobody@example.com", "password": "x" * 12})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


def test_login_issues_new_session_each_time(make_user: Any) -> None:
    u = make_user()
    first = u.api.http.cookies.get("salesiq_session")
    r = u.api.post("/auth/login", {"email": u.email, "password": PASSWORD})
    assert r.status_code == 200
    assert u.api.http.cookies.get("salesiq_session") != first


def test_login_rejects_form_encoded_body(make_user: Any) -> None:
    u = make_user()
    r = Api().http.post("/api/v1/auth/login", data={"email": u.email, "password": PASSWORD})
    assert r.status_code == 415


def test_login_is_rate_limited(make_user: Any) -> None:
    u = make_user()
    api = Api()
    codes = [
        api.post("/auth/login", {"email": u.email, "password": "wrong-password!"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_unauthenticated_requests_rejected(clean_db: Engine) -> None:
    api = Api()
    assert api.get("/auth/me").status_code == 401
    api.http.cookies.set("salesiq_session", "forged-token-value-1234567890")
    assert api.get("/auth/me").status_code == 401


def test_mutations_require_csrf_token(make_user: Any) -> None:
    u = make_user()
    no_header = u.api.http.post("/api/v1/organizations", json={"name": "X"})
    assert no_header.status_code == 403
    assert no_header.json()["error"]["code"] == "csrf_failed"
    wrong = u.api.http.post(
        "/api/v1/organizations", json={"name": "X"}, headers={"x-csrf-token": "0" * 64}
    )
    assert wrong.status_code == 403
    assert u.api.post("/organizations", {"name": "X"}).status_code == 201


def test_csrf_token_from_other_session_rejected(make_user: Any) -> None:
    a, b = make_user(), make_user()
    r = a.api.http.post(
        "/api/v1/organizations",
        json={"name": "X"},
        headers={"x-csrf-token": b.api.http.cookies.get("salesiq_csrf")},
    )
    assert r.status_code == 403


def test_logout_revokes_session_server_side(make_user: Any) -> None:
    u = make_user()
    stolen = u.api.http.cookies.get("salesiq_session")
    assert u.api.post("/auth/logout").status_code == 204
    replay = Api()
    replay.http.cookies.set("salesiq_session", stolen)
    assert replay.get("/auth/me").status_code == 401


def test_list_and_revoke_other_sessions(make_user: Any) -> None:
    u = make_user()
    other = Api()
    other.post("/auth/login", {"email": u.email, "password": PASSWORD})
    sessions = u.api.get("/auth/sessions").json()
    assert len(sessions) == 2
    target = next(s for s in sessions if not s["current"])
    assert u.api.delete(f"/auth/sessions/{target['id']}").status_code == 204
    assert other.get("/auth/me").status_code == 401
    assert u.api.get("/auth/me").status_code == 200


def test_cannot_revoke_another_users_session(make_user: Any) -> None:
    a, b = make_user(), make_user()
    b_session = b.api.get("/auth/sessions").json()[0]["id"]
    assert a.api.delete(f"/auth/sessions/{b_session}").status_code == 404
    assert b.api.get("/auth/me").status_code == 200


def test_idle_session_expires(make_user: Any, clean_db: Engine) -> None:
    u = make_user()
    with clean_db.begin() as conn:
        conn.execute(
            text("UPDATE user_sessions SET last_seen_at = :t"),
            {"t": datetime.now(UTC) - timedelta(days=3)},
        )
    assert u.api.get("/auth/me").status_code == 401


def test_disabled_user_session_rejected(make_user: Any, clean_db: Engine) -> None:
    u = make_user()
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE users SET disabled_at = now()"))
    assert u.api.get("/auth/me").status_code == 401
    r = Api().post("/auth/login", {"email": u.email, "password": PASSWORD})
    assert r.status_code == 401


def test_change_password_revokes_other_sessions(make_user: Any) -> None:
    u = make_user()
    other = Api()
    other.post("/auth/login", {"email": u.email, "password": PASSWORD})
    new = "a much better passphrase"
    r = u.api.post("/auth/password", {"current_password": PASSWORD, "new_password": new})
    assert r.status_code == 204
    assert u.api.get("/auth/me").status_code == 200
    assert other.get("/auth/me").status_code == 401
    assert Api().post("/auth/login", {"email": u.email, "password": new}).status_code == 200


def test_password_reset_flow(make_user: Any, outbox: list[Any]) -> None:
    u = make_user()
    r = Api().post("/auth/password-reset/request", {"email": u.email})
    assert r.status_code == 202
    token = token_from(outbox, "reset-password")

    new = "brand new passphrase!"
    r = Api().post("/auth/password-reset/confirm", {"token": token, "new_password": new})
    assert r.status_code == 204
    assert u.api.get("/auth/me").status_code == 401, "reset must revoke existing sessions"
    assert Api().post("/auth/login", {"email": u.email, "password": new}).status_code == 200

    reuse = Api().post("/auth/password-reset/confirm", {"token": token, "new_password": new})
    assert reuse.status_code == 400


def test_password_reset_for_unknown_email_is_indistinguishable(
    clean_db: Engine, outbox: list[Any]
) -> None:
    r = Api().post("/auth/password-reset/request", {"email": "ghost@example.com"})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    assert outbox == []


def test_only_latest_reset_token_is_valid(make_user: Any, outbox: list[Any]) -> None:
    u = make_user()
    Api().post("/auth/password-reset/request", {"email": u.email})
    first = token_from(outbox, "reset-password")
    Api().post("/auth/password-reset/request", {"email": u.email})
    r = Api().post("/auth/password-reset/confirm", {"token": first, "new_password": "x" * 14})
    assert r.status_code == 400


def test_email_verification(make_user: Any, outbox: list[Any]) -> None:
    u = make_user(verified=False)
    assert u.api.get("/auth/me").json()["user"]["email_verified"] is False
    token = token_from(outbox, "verify-email")
    assert Api().post("/auth/verify-email", {"token": token}).status_code == 200
    assert u.api.get("/auth/me").json()["user"]["email_verified"] is True
    assert Api().post("/auth/verify-email", {"token": token}).status_code == 400


def test_tokens_are_stored_hashed(make_user: Any, outbox: list[Any], clean_db: Engine) -> None:
    u = make_user(verified=False)
    raw_session = u.api.http.cookies.get("salesiq_session")
    raw_verify = token_from(outbox, "verify-email")
    with clean_db.connect() as conn:
        stored = (
            conn.execute(
                text(
                    "SELECT token_hash FROM user_sessions "
                    "UNION ALL SELECT token_hash FROM auth_tokens"
                )
            )
            .scalars()
            .all()
        )
    assert raw_session not in stored and raw_verify not in stored


def test_password_is_hashed_with_argon2(make_user: Any, clean_db: Engine) -> None:
    make_user()
    with clean_db.connect() as conn:
        h = conn.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert h.startswith("$argon2id$") and PASSWORD not in h


def test_cookies_use_the_host_prefix_outside_development(
    make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A browser accepts this prefix only over HTTPS, for the host, with no Domain."""
    from app.core.config import get_settings

    make_user("host-prefix@example.com")
    # The app refuses to start as staging with development secrets, so these are made first.
    api, plain, prefixed = Api(), Api(), Api()
    monkeypatch.setattr(get_settings(), "environment", "staging")
    r = api.post("/auth/login", {"email": "host-prefix@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-salesiq_session="))
    csrf = next(c for c in cookies if c.startswith("__Host-salesiq_csrf="))
    for cookie in (session, csrf):
        assert "Secure" in cookie and "Path=/" in cookie and "Domain" not in cookie
    assert "HttpOnly" in session and "HttpOnly" not in csrf
    token = session.split(";")[0].split("=", 1)[1]
    # A cookie with the plain name is not looked at, so one planted by a neighbor does nothing.
    plain.http.cookies.set("salesiq_session", token)
    assert plain.get("/auth/me").status_code == 401
    prefixed.http.cookies.set("__Host-salesiq_session", token)
    assert prefixed.get("/auth/me").status_code == 200
