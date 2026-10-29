"""Tenant isolation for every CRM route and table."""

from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

CRM_TABLES = [
    "companies",
    "leads",
    "lead_imports",
    "pipeline_stages",
    "opportunities",
    "activities",
]


@pytest.fixture
def two_orgs(make_org: Any) -> dict[str, Any]:
    owner_a, org_a = make_org("A")
    owner_b, org_b = make_org("B")
    api = owner_a.api
    stages = api.get(f"/organizations/{org_a}/pipeline/stages").json()
    lead = api.post(
        f"/organizations/{org_a}/leads", {"email": "secret@a.example.com", "company_name": "A Corp"}
    ).json()
    opp = api.post(
        f"/organizations/{org_a}/opportunities",
        {"name": "A deal", "stage_id": stages[0]["id"], "lead_id": lead["id"]},
    ).json()
    imp = api.post(
        f"/organizations/{org_a}/lead-imports",
        {"filename": "a.csv", "content": "email\nz@a.example.com\n", "mapping": {"email": "email"}},
    ).json()
    return {
        "a": owner_a,
        "org_a": org_a,
        "b": owner_b,
        "org_b": org_b,
        "lead": lead,
        "opp": opp,
        "stage": stages[0],
        "company": lead["company"],
        "import": imp,
    }


def test_b_cannot_reach_a_records_through_its_own_org(two_orgs: dict[str, Any]) -> None:
    b, ob, t = two_orgs["b"].api, two_orgs["org_b"], two_orgs
    base = f"/organizations/{ob}"
    calls = [
        b.get(f"{base}/leads/{t['lead']['id']}"),
        b.patch(f"{base}/leads/{t['lead']['id']}", {"title": "pwned"}),
        b.delete(f"{base}/leads/{t['lead']['id']}"),
        b.post(f"{base}/leads/{t['lead']['id']}/notes", {"body": "x"}),
        b.get(f"{base}/companies/{t['company']['id']}"),
        b.patch(f"{base}/companies/{t['company']['id']}", {"name": "pwned"}),
        b.get(f"{base}/opportunities/{t['opp']['id']}"),
        b.patch(f"{base}/opportunities/{t['opp']['id']}", {"name": "pwned"}),
        b.patch(f"{base}/pipeline/stages/{t['stage']['id']}", {"name": "pwned"}),
        b.get(f"{base}/lead-imports/{t['import']['id']}"),
    ]
    assert [r.status_code for r in calls] == [404] * len(calls)


def test_b_cannot_link_a_records_into_its_own_org(two_orgs: dict[str, Any]) -> None:
    b, ob, t = two_orgs["b"].api, two_orgs["org_b"], two_orgs
    own_stage = b.get(f"/organizations/{ob}/pipeline/stages").json()[0]["id"]
    base = f"/organizations/{ob}"
    refs = [
        b.post(f"{base}/opportunities", {"name": "x", "stage_id": t["stage"]["id"]}),
        b.post(
            f"{base}/opportunities",
            {"name": "x", "stage_id": own_stage, "lead_id": t["lead"]["id"]},
        ),
        b.post(
            f"{base}/opportunities",
            {"name": "x", "stage_id": own_stage, "company_id": t["company"]["id"]},
        ),
        b.post(f"{base}/leads", {"email": "n@b.example.com", "company_id": t["company"]["id"]}),
    ]
    assert [r.status_code for r in refs] == [422] * len(refs)


def test_b_lists_and_exports_only_its_own_data(two_orgs: dict[str, Any]) -> None:
    b, ob = two_orgs["b"].api, two_orgs["org_b"]
    assert b.get(f"/organizations/{ob}/leads").json()["total"] == 0
    assert b.get(f"/organizations/{ob}/companies").json()["items"] == []
    assert b.get(f"/organizations/{ob}/opportunities").json() == []
    assert "secret@a.example.com" not in b.get(f"/organizations/{ob}/leads/export").text
    assert b.get(f"/organizations/{ob}/analytics/overview").json()["leads_total"] == 0


def test_same_email_may_exist_in_two_orgs(two_orgs: dict[str, Any]) -> None:
    b, ob = two_orgs["b"].api, two_orgs["org_b"]
    r = b.post(f"/organizations/{ob}/leads", {"email": "secret@a.example.com"})
    assert r.status_code == 201, "dedupe is per organization; it must not leak existence"


def test_crm_tables_hidden_without_context(two_orgs: dict[str, Any], app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        for table in CRM_TABLES:
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()  # noqa: S608
            assert count == 0, table


@pytest.mark.parametrize(
    "stmt",
    [
        "DELETE FROM leads",
        "DELETE FROM companies",
        "DELETE FROM opportunities",
        "UPDATE activities SET body = 'x'",
        "DELETE FROM activities",
    ],
)
def test_app_role_privileges_are_minimal(
    two_orgs: dict[str, Any], app_engine: Engine, stmt: str
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": two_orgs["org_a"]})
        conn.execute(text(stmt))


def test_rls_enabled_on_crm_tables(two_orgs: dict[str, Any], clean_db: Engine) -> None:
    with clean_db.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity "
                    "AND relname = ANY(:t)"
                ),
                {"t": CRM_TABLES},
            )
            .scalars()
            .all()
        )
    assert sorted(rows) == sorted(CRM_TABLES)
