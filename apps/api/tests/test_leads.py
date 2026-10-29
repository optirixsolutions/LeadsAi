"""Leads and companies: CRUD, dedupe, filters, pagination, bulk actions, export."""

import csv
import io
from typing import Any

import pytest


@pytest.fixture
def org(make_org: Any) -> tuple[Any, str]:
    return make_org("Leads Co")


def _lead(api: Any, org_id: str, **fields: Any) -> dict[str, Any]:
    r = api.post(f"/organizations/{org_id}/leads", fields)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_normalizes_and_records_activity(org: tuple[Any, str]) -> None:
    owner, oid = org
    lead = _lead(
        owner.api,
        oid,
        first_name=" Ada ",
        email="Ada@Example.COM",
        company_name="Analytical Engines",
        tags=["VIP", "vip", " q4 "],
    )
    assert lead["email"] == "ada@example.com"
    assert lead["first_name"] == "Ada"
    assert lead["tags"] == ["vip", "q4"]
    assert lead["company"]["name"] == "Analytical Engines"
    assert lead["source"] == "manual"
    detail = owner.api.get(f"/organizations/{oid}/leads/{lead['id']}").json()
    assert [a["type"] for a in detail["activities"]] == ["created"]


def test_duplicate_email_is_rejected_with_existing_id(org: tuple[Any, str]) -> None:
    owner, oid = org
    first = _lead(owner.api, oid, email="dup@example.com")
    r = owner.api.post(f"/organizations/{oid}/leads", {"email": "DUP@example.com"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "duplicate_lead"
    assert err["details"]["existing_lead_id"] == first["id"]


def test_company_name_is_reused_case_insensitively(org: tuple[Any, str]) -> None:
    owner, oid = org
    a = _lead(owner.api, oid, email="a@example.com", company_name="Globex")
    b = _lead(owner.api, oid, email="b@example.com", company_name="GLOBEX")
    assert a["company"]["id"] == b["company"]["id"]


def test_unsafe_url_rejected(org: tuple[Any, str]) -> None:
    owner, oid = org
    r = owner.api.post(
        f"/organizations/{oid}/leads",
        {"email": "x@example.com", "linkedin_url": "javascript:alert(1)"},
    )
    assert r.status_code == 422


def test_filters_search_and_totals(org: tuple[Any, str]) -> None:
    owner, oid = org
    _lead(
        owner.api,
        oid,
        first_name="Grace",
        last_name="Hopper",
        email="g@example.com",
        company_name="Navy",
        tags=["cobol"],
    )
    _lead(owner.api, oid, first_name="Alan", email="alan@example.com", status="qualified")
    _lead(owner.api, oid, first_name="100%", email="pct@example.com")
    base = f"/organizations/{oid}/leads"

    by_company = owner.api.get(base, params={"q": "navy"}).json()
    assert [lead["first_name"] for lead in by_company["items"]] == ["Grace"]
    assert by_company["total"] == 1
    assert owner.api.get(base, params={"status": "qualified"}).json()["total"] == 1
    assert owner.api.get(base, params={"tag": "COBOL"}).json()["total"] == 1
    assert owner.api.get(base, params={"owner": "none"}).json()["total"] == 3
    # LIKE wildcards in the search are literal, not "match everything".
    assert owner.api.get(base, params={"q": "%"}).json()["total"] == 1
    assert owner.api.get(base, params={"sort": "password"}).status_code == 400


def test_cursor_pagination_has_no_gaps_or_overlaps(org: tuple[Any, str]) -> None:
    owner, oid = org
    names = ["delta", "alpha", "echo", "charlie", "bravo"]
    for n in names:
        _lead(owner.api, oid, last_name=n, email=f"{n}@example.com")
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"sort": "last_name", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = owner.api.get(f"/organizations/{oid}/leads", params=params).json()
        seen += [lead["last_name"] for lead in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == sorted(names)


def test_update_records_status_and_assignment(org: tuple[Any, str], add_member: Any) -> None:
    owner, oid = org
    rep, _ = add_member(owner, oid, "sales_rep")
    lead = _lead(owner.api, oid, email="u@example.com")
    r = owner.api.patch(
        f"/organizations/{oid}/leads/{lead['id']}",
        {"status": "contacted", "owner_user_id": rep.id, "title": "CTO"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["owner_user_id"] == rep.id
    types = [
        a["type"]
        for a in owner.api.get(f"/organizations/{oid}/leads/{lead['id']}").json()["activities"]
    ]
    assert {"status_changed", "assigned", "updated"} <= set(types)


def test_owner_must_be_org_member(org: tuple[Any, str], make_user: Any) -> None:
    owner, oid = org
    stranger = make_user()
    lead = _lead(owner.api, oid, email="m@example.com")
    r = owner.api.patch(f"/organizations/{oid}/leads/{lead['id']}", {"owner_user_id": stranger.id})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_reference"


def test_changing_email_to_existing_conflicts(org: tuple[Any, str]) -> None:
    owner, oid = org
    _lead(owner.api, oid, email="taken@example.com")
    other = _lead(owner.api, oid, email="free@example.com")
    r = owner.api.patch(f"/organizations/{oid}/leads/{other['id']}", {"email": "taken@example.com"})
    assert r.status_code == 409


def test_notes_append_to_timeline(org: tuple[Any, str]) -> None:
    owner, oid = org
    lead = _lead(owner.api, oid, email="n@example.com")
    r = owner.api.post(f"/organizations/{oid}/leads/{lead['id']}/notes", {"body": "Met at expo"})
    assert r.status_code == 201
    assert r.json()[0]["type"] == "note" and r.json()[0]["body"] == "Met at expo"


def test_soft_delete_hides_lead_and_frees_email(org: tuple[Any, str]) -> None:
    owner, oid = org
    lead = _lead(owner.api, oid, email="gone@example.com")
    assert owner.api.delete(f"/organizations/{oid}/leads/{lead['id']}").status_code == 204
    assert owner.api.get(f"/organizations/{oid}/leads/{lead['id']}").status_code == 404
    assert owner.api.get(f"/organizations/{oid}/leads").json()["total"] == 0
    _lead(owner.api, oid, email="gone@example.com")


def test_bulk_actions(org: tuple[Any, str], add_member: Any) -> None:
    owner, oid = org
    rep, _ = add_member(owner, oid, "sales_rep")
    ids = [_lead(owner.api, oid, email=f"b{i}@example.com")["id"] for i in range(3)]
    bulk = f"/organizations/{oid}/leads/bulk"

    def run(action: str, value: str | None = None) -> int:
        r = owner.api.post(bulk, {"ids": ids, "action": action, "value": value})
        assert r.status_code == 200, r.text
        return int(r.json()["affected"])

    assert run("assign", rep.id) == 3
    assert run("assign", rep.id) == 0, "no-op changes are not counted"
    assert run("set_status", "qualified") == 3
    assert run("add_tag", "Event") == 3
    assert (
        owner.api.get(f"/organizations/{oid}/leads", params={"tag": "event"}).json()["total"] == 3
    )
    assert run("remove_tag", "event") == 3
    assert run("delete") == 3
    assert owner.api.get(f"/organizations/{oid}/leads").json()["total"] == 0


def test_bulk_ignores_other_orgs_leads(make_org: Any) -> None:
    owner_a, org_a = make_org("A")
    owner_b, org_b = make_org("B")
    victim = _lead(owner_a.api, org_a, email="v@example.com")
    r = owner_b.api.post(
        f"/organizations/{org_b}/leads/bulk", {"ids": [victim["id"]], "action": "delete"}
    )
    assert r.json()["affected"] == 0
    assert owner_a.api.get(f"/organizations/{org_a}/leads/{victim['id']}").status_code == 200


@pytest.mark.parametrize(
    ("role", "create", "delete", "export", "import_"),
    [
        ("manager", 201, 204, 200, 200),
        ("sales_rep", 201, 403, 403, 403),
        ("analyst", 403, 403, 403, 403),
    ],
)
def test_role_permissions_on_leads(
    org: tuple[Any, str],
    add_member: Any,
    role: str,
    create: int,
    delete: int,
    export: int,
    import_: int,
) -> None:
    owner, oid = org
    member, _ = add_member(owner, oid, role)
    lead = _lead(owner.api, oid, email=f"{role}-target@example.com")
    api = member.api
    assert api.get(f"/organizations/{oid}/leads").status_code == 200
    assert (
        api.post(f"/organizations/{oid}/leads", {"email": f"{role}@example.com"}).status_code
        == create
    )
    assert api.delete(f"/organizations/{oid}/leads/{lead['id']}").status_code == delete
    assert api.get(f"/organizations/{oid}/leads/export").status_code == export
    preview = api.post(
        f"/organizations/{oid}/lead-imports/preview",
        {"filename": "x.csv", "content": "email\na@example.com\n"},
    )
    assert preview.status_code == import_


def test_export_escapes_formulas_and_is_audited(org: tuple[Any, str]) -> None:
    owner, oid = org
    _lead(owner.api, oid, first_name='=HYPERLINK("http://evil")', email="f@example.com")
    r = owner.api.get(f"/organizations/{oid}/leads/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["id", "first_name", "last_name", "email"]
    assert rows[1][1].startswith("'=")
    actions = [e["action"] for e in owner.api.get(f"/organizations/{oid}/audit").json()["items"]]
    assert "leads.exported" in actions


def test_company_crud_and_domain_uniqueness(org: tuple[Any, str]) -> None:
    owner, oid = org
    r = owner.api.post(
        f"/organizations/{oid}/companies",
        {"name": "Initech", "domain": "https://www.Initech.com/about"},
    )
    assert r.status_code == 201 and r.json()["domain"] == "initech.com"
    dup = owner.api.post(f"/organizations/{oid}/companies", {"name": "X", "domain": "initech.com"})
    assert dup.status_code == 409
    cid = r.json()["id"]
    _lead(owner.api, oid, email="p@initech.com", company_id=cid)
    detail = owner.api.get(f"/organizations/{oid}/companies/{cid}").json()
    assert detail["lead_count"] == 1
    listed = owner.api.get(f"/organizations/{oid}/companies", params={"q": "init"}).json()
    assert [c["name"] for c in listed["items"]] == ["Initech"]
