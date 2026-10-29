"""Role permissions, privilege-escalation rules, invitations, and audit trail."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.permissions import ROLE_PERMISSIONS, Permission, can_manage_role, has_permission
from app.models import Role
from tests.conftest import token_from

# --- matrix (unit) ----------------------------------------------------------------------


def test_every_role_has_an_entry() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize("role", [Role.manager, Role.sales_rep, Role.analyst])
def test_non_admin_roles_cannot_administer(role: Role) -> None:
    for p in (
        Permission.org_update,
        Permission.members_invite,
        Permission.members_manage,
        Permission.audit_read,
    ):
        assert not has_permission(role, p)


def test_assignment_rules() -> None:
    assert can_manage_role(Role.owner, Role.owner)
    assert not can_manage_role(Role.admin, Role.owner)
    assert not can_manage_role(Role.admin, Role.admin)
    assert can_manage_role(Role.admin, Role.sales_rep)
    assert not can_manage_role(Role.manager, Role.analyst)


# --- enforcement through the API --------------------------------------------------------


def test_sales_rep_cannot_administer(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    rep, _ = add_member(owner, org, "sales_rep")
    assert rep.api.get(f"/organizations/{org}").status_code == 200
    assert rep.api.get(f"/organizations/{org}/members").status_code == 200
    forbidden = [
        rep.api.patch(f"/organizations/{org}", {"name": "x"}),
        rep.api.post(
            f"/organizations/{org}/invitations", {"email": "a@example.com", "role": "analyst"}
        ),
        rep.api.get(f"/organizations/{org}/audit"),
    ]
    assert [r.status_code for r in forbidden] == [403, 403, 403]


def test_admin_cannot_invite_owner_or_admin(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    admin, _ = add_member(owner, org, "admin")
    for role in ("owner", "admin"):
        r = admin.api.post(
            f"/organizations/{org}/invitations", {"email": f"{role}@example.com", "role": role}
        )
        assert r.status_code == 403, role
    ok = admin.api.post(
        f"/organizations/{org}/invitations", {"email": "m@example.com", "role": "manager"}
    )
    assert ok.status_code == 201


def test_admin_cannot_touch_owner_or_promote_to_admin(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    admin, _ = add_member(owner, org, "admin")
    _, rep_mid = add_member(owner, org, "sales_rep")
    owner_mid = next(
        m["id"]
        for m in owner.api.get(f"/organizations/{org}/members").json()
        if m["role"] == "owner"
    )
    assert (
        admin.api.patch(
            f"/organizations/{org}/members/{owner_mid}", {"role": "analyst"}
        ).status_code
        == 403
    )
    assert admin.api.delete(f"/organizations/{org}/members/{owner_mid}").status_code == 403
    assert (
        admin.api.patch(f"/organizations/{org}/members/{rep_mid}", {"role": "admin"}).status_code
        == 403
    )
    assert (
        admin.api.patch(f"/organizations/{org}/members/{rep_mid}", {"role": "manager"}).status_code
        == 204
    )


def test_no_one_changes_their_own_role(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    admin, admin_mid = add_member(owner, org, "admin")
    r = admin.api.patch(f"/organizations/{org}/members/{admin_mid}", {"role": "owner"})
    assert r.status_code == 403


def test_last_owner_cannot_leave(make_org: Any) -> None:
    owner, org = make_org()
    mid = owner.api.get(f"/organizations/{org}/members").json()[0]["id"]
    r = owner.api.delete(f"/organizations/{org}/members/{mid}")
    assert r.status_code == 409


def test_member_can_leave(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    rep, rep_mid = add_member(owner, org, "sales_rep")
    assert rep.api.delete(f"/organizations/{org}/members/{rep_mid}").status_code == 204
    assert rep.api.get(f"/organizations/{org}").status_code == 404


def test_removed_member_loses_access_immediately(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    rep, rep_mid = add_member(owner, org, "sales_rep")
    assert owner.api.delete(f"/organizations/{org}/members/{rep_mid}").status_code == 204
    assert rep.api.get(f"/organizations/{org}/members").status_code == 404


# --- invitations ------------------------------------------------------------------------


def test_invitation_preview_and_accept(make_org: Any, make_user: Any, outbox: list[Any]) -> None:
    owner, org = make_org("Acme")
    invitee = make_user()
    owner.api.post(f"/organizations/{org}/invitations", {"email": invitee.email, "role": "manager"})
    token = token_from(outbox, "invite")
    preview = invitee.api.post("/invitations/preview", {"token": token}).json()
    assert preview["organization_name"] == "Acme" and preview["role"] == "manager"
    r = invitee.api.post("/invitations/accept", {"token": token})
    assert r.status_code == 200 and r.json()["role"] == "manager"
    assert invitee.api.post("/invitations/accept", {"token": token}).status_code == 400


def test_invitation_must_be_redeemed_by_invited_email(
    make_org: Any, make_user: Any, outbox: list[Any]
) -> None:
    owner, org = make_org()
    owner.api.post(
        f"/organizations/{org}/invitations", {"email": "intended@example.com", "role": "admin"}
    )
    interceptor = make_user()
    r = interceptor.api.post("/invitations/accept", {"token": token_from(outbox, "invite")})
    assert r.status_code == 403
    assert interceptor.api.get(f"/organizations/{org}").status_code == 404


def test_revoked_and_expired_invitations_fail(
    make_org: Any, make_user: Any, outbox: list[Any], clean_db: Engine
) -> None:
    owner, org = make_org()
    invitee = make_user()
    inv = owner.api.post(
        f"/organizations/{org}/invitations", {"email": invitee.email, "role": "analyst"}
    ).json()
    token = token_from(outbox, "invite")
    owner.api.delete(f"/organizations/{org}/invitations/{inv['id']}")
    assert invitee.api.post("/invitations/accept", {"token": token}).status_code == 400

    owner.api.post(f"/organizations/{org}/invitations", {"email": invitee.email, "role": "analyst"})
    token2 = token_from(outbox, "invite")
    with clean_db.begin() as conn:
        conn.execute(
            text("UPDATE invitations SET expires_at = :t"),
            {"t": datetime.now(UTC) - timedelta(minutes=1)},
        )
    assert invitee.api.post("/invitations/accept", {"token": token2}).status_code == 400


def test_reinvite_replaces_pending_invitation(make_org: Any, outbox: list[Any]) -> None:
    owner, org = make_org()
    for _ in range(2):
        owner.api.post(
            f"/organizations/{org}/invitations", {"email": "p@example.com", "role": "analyst"}
        )
    assert len(owner.api.get(f"/organizations/{org}/invitations").json()) == 1


def test_inviting_existing_member_conflicts(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    rep, _ = add_member(owner, org, "sales_rep")
    r = owner.api.post(f"/organizations/{org}/invitations", {"email": rep.email, "role": "analyst"})
    assert r.status_code == 409


def test_invitation_response_never_contains_token(make_org: Any, outbox: list[Any]) -> None:
    owner, org = make_org()
    r = owner.api.post(
        f"/organizations/{org}/invitations", {"email": "p@example.com", "role": "analyst"}
    )
    assert token_from(outbox, "invite") not in r.text


# --- audit ------------------------------------------------------------------------------


def test_consequential_actions_are_audited(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    _, rep_mid = add_member(owner, org, "sales_rep")
    owner.api.patch(f"/organizations/{org}/members/{rep_mid}", {"role": "manager"})
    items = owner.api.get(f"/organizations/{org}/audit").json()["items"]
    actions = [i["action"] for i in items]
    for expected in (
        "org.created",
        "invitation.created",
        "invitation.accepted",
        "member.role_changed",
    ):
        assert expected in actions
    change = next(i for i in items if i["action"] == "member.role_changed")
    assert change["data"] == {
        "user_id": change["data"]["user_id"],
        "from": "sales_rep",
        "to": "manager",
    }
    assert change["request_id"]


def test_audit_pagination(make_org: Any) -> None:
    owner, org = make_org()
    for i in range(4):
        owner.api.patch(f"/organizations/{org}", {"name": f"Name {i}"})
    page1 = owner.api.get(f"/organizations/{org}/audit", params={"limit": 3}).json()
    assert len(page1["items"]) == 3 and page1["next_cursor"]
    page2 = owner.api.get(
        f"/organizations/{org}/audit", params={"limit": 3, "cursor": page1["next_cursor"]}
    ).json()
    ids1 = {i["id"] for i in page1["items"]}
    assert len(page2["items"]) == 2 and not ids1 & {i["id"] for i in page2["items"]}
    assert page2["next_cursor"] is None
    bad = owner.api.get(f"/organizations/{org}/audit", params={"cursor": "!!!"})
    assert bad.status_code == 400
