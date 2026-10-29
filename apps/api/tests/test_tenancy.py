"""Tenant isolation: through the API (BOLA/IDOR) and directly at the database (RLS)."""

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import token_from


def test_creator_becomes_owner(make_org: Any) -> None:
    owner, org_id = make_org("Acme Corp")
    orgs = owner.api.get("/organizations").json()
    assert [(o["id"], o["role"]) for o in orgs] == [(org_id, "owner")]
    me = owner.api.get("/auth/me").json()
    assert me["memberships"][0]["organization_name"] == "Acme Corp"
    assert "members:invite" in me["memberships"][0]["permissions"]


def test_list_only_shows_own_orgs(make_org: Any) -> None:
    a, _ = make_org("A")
    b, _ = make_org("B")
    assert [o["name"] for o in a.api.get("/organizations").json()] == ["A"]
    assert [o["name"] for o in b.api.get("/organizations").json()] == ["B"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "", None),
        ("patch", "", {"name": "pwned"}),
        ("get", "/members", None),
        ("get", "/invitations", None),
        ("post", "/invitations", {"email": "x@example.com", "role": "owner"}),
        ("get", "/audit", None),
    ],
)
def test_non_member_gets_404_on_every_org_route(
    make_org: Any, method: str, path: str, body: Any
) -> None:
    _, org_a = make_org("A")
    outsider, _ = make_org("B")
    api = outsider.api
    call = {
        "get": lambda: api.get(f"/organizations/{org_a}{path}"),
        "patch": lambda: api.patch(f"/organizations/{org_a}{path}", body),
        "post": lambda: api.post(f"/organizations/{org_a}{path}", body),
    }[method]
    r = call()
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"


def test_unknown_org_and_foreign_org_are_indistinguishable(make_org: Any) -> None:
    _, org_a = make_org("A")
    outsider, _ = make_org("B")
    foreign = outsider.api.get(f"/organizations/{org_a}")
    missing = outsider.api.get(f"/organizations/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_idor_membership_from_other_org_via_own_org_path(make_org: Any, add_member: Any) -> None:
    owner_a, org_a = make_org("A")
    _, victim_mid = add_member(owner_a, org_a, "sales_rep")
    owner_b, org_b = make_org("B")
    # Owner of B uses B's path (where they are authorized) with A's membership ID.
    assert (
        owner_b.api.patch(
            f"/organizations/{org_b}/members/{victim_mid}", {"role": "analyst"}
        ).status_code
        == 404
    )
    assert owner_b.api.delete(f"/organizations/{org_b}/members/{victim_mid}").status_code == 404
    roles = {m["id"]: m["role"] for m in owner_a.api.get(f"/organizations/{org_a}/members").json()}
    assert roles[victim_mid] == "sales_rep"


def test_idor_invitation_from_other_org(make_org: Any) -> None:
    owner_a, org_a = make_org("A")
    inv = owner_a.api.post(
        f"/organizations/{org_a}/invitations", {"email": "p@example.com", "role": "analyst"}
    ).json()
    owner_b, org_b = make_org("B")
    r = owner_b.api.delete(f"/organizations/{org_b}/invitations/{inv['id']}")
    assert r.status_code == 404
    pending = owner_a.api.get(f"/organizations/{org_a}/invitations").json()
    assert [i["id"] for i in pending] == [inv["id"]]


def test_audit_log_is_tenant_scoped(make_org: Any) -> None:
    owner_a, org_a = make_org("A")
    owner_b, org_b = make_org("B")
    owner_b.api.patch(f"/organizations/{org_b}", {"name": "B2"})
    entries = owner_a.api.get(f"/organizations/{org_a}/audit").json()["items"]
    assert {e["action"] for e in entries} == {"org.created"}


# --- database-level row-level security --------------------------------------------------


def _ids(admin: Engine) -> dict[str, str]:
    with admin.connect() as conn:
        rows = conn.execute(text("SELECT id::text, name FROM organizations")).all()
    return {name: oid for oid, name in rows}


def test_rls_hides_everything_without_tenant_context(make_org: Any, app_engine: Engine) -> None:
    make_org("A")
    with app_engine.connect() as conn:
        for table in ("organizations", "memberships", "invitations", "audit_logs"):
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()  # noqa: S608
            assert count == 0, table


def test_rls_scopes_reads_to_current_org(
    make_org: Any, clean_db: Engine, app_engine: Engine
) -> None:
    make_org("A")
    make_org("B")
    ids = _ids(clean_db)
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": ids["B"]})
        visible = conn.execute(text("SELECT id::text FROM organizations")).scalars().all()
        leaked = conn.execute(
            text("SELECT count(*) FROM memberships WHERE organization_id = :a"), {"a": ids["A"]}
        ).scalar()
    assert visible == [ids["B"]]
    assert leaked == 0


def test_rls_blocks_cross_tenant_writes(
    make_org: Any, clean_db: Engine, app_engine: Engine
) -> None:
    owner_a, _ = make_org("A")
    make_org("B")
    ids = _ids(clean_db)
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": ids["B"]})
        conn.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (gen_random_uuid(), :a, :u, 'owner')"
            ),
            {"a": ids["A"], "u": owner_a.id},
        )


def test_rls_context_does_not_leak_across_transactions(
    make_org: Any, clean_db: Engine, app_engine: Engine
) -> None:
    make_org("A")
    ids = _ids(clean_db)
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": ids["A"]})
            assert conn.execute(text("SELECT count(*) FROM organizations")).scalar() == 1
        # Same pooled connection, new transaction: context is gone.
        assert conn.execute(text("SELECT count(*) FROM organizations")).scalar() == 0


def test_audit_log_is_append_only_for_app_role(
    make_org: Any, clean_db: Engine, app_engine: Engine
) -> None:
    make_org("A")
    ids = _ids(clean_db)
    for stmt in ("UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"):
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": ids["A"]})
            conn.execute(text(stmt))


def test_app_role_cannot_bypass_rls(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert row == (False, False)


def test_invitation_lookup_requires_exact_token(
    make_org: Any, outbox: list[Any], app_engine: Engine
) -> None:
    owner, org = make_org("A")
    owner.api.post(
        f"/organizations/{org}/invitations", {"email": "p@example.com", "role": "analyst"}
    )
    from app.core.security import token_digest

    token = token_from(outbox, "invite")
    with app_engine.connect() as conn:
        hit = conn.execute(
            text("SELECT * FROM invitation_lookup(:h)"), {"h": token_digest(token)}
        ).all()
        miss = conn.execute(text("SELECT * FROM invitation_lookup(:h)"), {"h": "%"}).all()
    assert len(hit) == 1 and miss == []
