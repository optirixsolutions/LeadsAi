"""Regression tests for findings from the Phase 2 security review."""

import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import PASSWORD, Api, token_from


def test_unverified_account_cannot_accept_invitation(
    make_org: Any, make_user: Any, outbox: list[Any]
) -> None:
    owner, org = make_org()
    invitee = make_user(verified=False)
    owner.api.post(f"/organizations/{org}/invitations", {"email": invitee.email, "role": "admin"})
    invite_token = token_from(outbox, "invite")

    r = invitee.api.post("/invitations/accept", {"token": invite_token})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "email_unverified"
    assert invitee.api.get(f"/organizations/{org}").status_code == 404

    invitee.api.post("/auth/verify-email", {"token": token_from(outbox, "verify-email")})
    assert invitee.api.post("/invitations/accept", {"token": invite_token}).status_code == 200


def test_concurrent_mutual_owner_removal_keeps_an_owner(
    make_org: Any, add_member: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import org_service

    # Hold each request between "count owners" and "delete" long enough that, without
    # serialization, both would pass the last-owner check.
    real_count = org_service._owner_count

    def slow_count(db: Any, org_id: Any) -> int:
        n = real_count(db, org_id)
        time.sleep(0.5)
        return n

    monkeypatch.setattr(org_service, "_owner_count", slow_count)
    a, org = make_org()
    b, b_mid = add_member(a, org, "owner")
    a_mid = next(
        m["id"] for m in a.api.get(f"/organizations/{org}/members").json() if m["user_id"] == a.id
    )
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def remove(actor: Any, target: str) -> None:
        barrier.wait()
        codes.append(actor.api.delete(f"/organizations/{org}/members/{target}").status_code)

    threads = [
        threading.Thread(target=remove, args=(a, b_mid)),
        threading.Thread(target=remove, args=(b, a_mid)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with clean_db.connect() as conn:
        owners = conn.execute(
            text("SELECT count(*) FROM memberships WHERE organization_id = :o AND role = 'owner'"),
            {"o": org},
        ).scalar()
    assert owners == 1, codes
    assert sorted(codes)[0] == 204 and sorted(codes)[1] in (404, 409)


def test_rls_blocks_deleting_own_memberships_outside_org_context(
    make_org: Any, app_engine: Engine, clean_db: Engine
) -> None:
    owner, _ = make_org("A")
    owner.api.post("/organizations", {"name": "B"})
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": owner.id})
        visible = conn.execute(text("SELECT count(*) FROM memberships")).scalar()
        deleted = conn.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": owner.id})
    assert visible == 2, "user context may read own memberships"
    assert deleted.rowcount == 0, "but must not delete them without the org context"


def test_app_role_cannot_delete_organizations(make_org: Any, app_engine: Engine) -> None:
    _, org = make_org()
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": org})
        conn.execute(text("DELETE FROM organizations"))


def test_invitation_lookup_ignores_temp_table_shadowing(make_org: Any, app_engine: Engine) -> None:
    owner, org = make_org()
    owner.api.post(
        f"/organizations/{org}/invitations", {"email": "p@example.com", "role": "analyst"}
    )
    with app_engine.begin() as conn:
        conn.execute(
            text("CREATE TEMP TABLE invitations (id uuid, organization_id uuid, token_hash text)")
        )
        conn.execute(
            text("INSERT INTO pg_temp.invitations VALUES (gen_random_uuid(), :o, 'fake')"),
            {"o": org},
        )
        rows = conn.execute(text("SELECT * FROM invitation_lookup('fake')")).all()
        owner_role = conn.execute(
            text(
                "SELECT r.rolsuper FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
                "WHERE p.proname = 'invitation_lookup'"
            )
        ).scalar()
    assert rows == []
    assert owner_role is False, "definer function must not be owned by a superuser"


def test_admin_cannot_displace_owner_issued_invitation(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    admin, _ = add_member(owner, org, "admin")
    owner.api.post(
        f"/organizations/{org}/invitations", {"email": "vip@example.com", "role": "admin"}
    )
    r = admin.api.post(
        f"/organizations/{org}/invitations", {"email": "vip@example.com", "role": "analyst"}
    )
    assert r.status_code == 409
    pending = owner.api.get(f"/organizations/{org}/invitations").json()
    assert [p["role"] for p in pending] == ["admin"]


def test_relogin_revokes_previous_session(make_user: Any) -> None:
    u = make_user()
    old = u.api.http.cookies.get("salesiq_session")
    assert u.api.post("/auth/login", {"email": u.email, "password": PASSWORD}).status_code == 200
    replay = Api()
    replay.http.cookies.set("salesiq_session", old)
    assert replay.get("/auth/me").status_code == 401
    assert u.api.get("/auth/me").status_code == 200


def test_password_change_is_rate_limited(make_user: Any) -> None:
    u = make_user()
    codes = [
        u.api.post(
            "/auth/password", {"current_password": "wrong-guess-123", "new_password": "x" * 14}
        ).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]
