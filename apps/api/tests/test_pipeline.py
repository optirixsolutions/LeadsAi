"""Pipeline stages, opportunities, stage transitions, summaries, and the overview."""

from typing import Any

import pytest


@pytest.fixture
def org(make_org: Any) -> tuple[Any, str]:
    return make_org("Pipe Co")


def _stages(api: Any, oid: str) -> dict[str, dict[str, Any]]:
    return {s["name"]: s for s in api.get(f"/organizations/{oid}/pipeline/stages").json()}


def _opp(api: Any, oid: str, **fields: Any) -> dict[str, Any]:
    r = api.post(f"/organizations/{oid}/opportunities", fields)
    assert r.status_code == 201, r.text
    return r.json()


def test_new_org_has_default_stages(org: tuple[Any, str]) -> None:
    owner, oid = org
    stages = owner.api.get(f"/organizations/{oid}/pipeline/stages").json()
    assert [s["name"] for s in stages] == [
        "Qualification",
        "Discovery",
        "Proposal",
        "Negotiation",
        "Closed won",
        "Closed lost",
    ]
    assert [s["kind"] for s in stages][-2:] == ["won", "lost"]


def test_opportunity_lifecycle(org: tuple[Any, str]) -> None:
    owner, oid = org
    stages = _stages(owner.api, oid)
    lead = owner.api.post(
        f"/organizations/{oid}/leads", {"email": "buyer@acme-corp.com", "company_name": "Acme"}
    ).json()
    opp = _opp(
        owner.api,
        oid,
        name="Acme pilot",
        stage_id=stages["Discovery"]["id"],
        lead_id=lead["id"],
        amount="12500.00",
    )
    assert opp["company_id"] == lead["company"]["id"], "company is inherited from the lead"
    assert opp["owner_user_id"] == owner.id
    assert opp["closed_at"] is None

    won = owner.api.patch(
        f"/organizations/{oid}/opportunities/{opp['id']}", {"stage_id": stages["Closed won"]["id"]}
    ).json()
    assert won["closed_at"] is not None
    reopened = owner.api.patch(
        f"/organizations/{oid}/opportunities/{opp['id']}", {"stage_id": stages["Proposal"]["id"]}
    ).json()
    assert reopened["closed_at"] is None

    timeline = owner.api.get(f"/organizations/{oid}/leads/{lead['id']}").json()
    types = [a["type"] for a in timeline["activities"]]
    assert types.count("stage_changed") == 2 and "opportunity_created" in types
    assert timeline["opportunities"][0]["id"] == opp["id"]


def test_board_hides_closed_unless_requested(org: tuple[Any, str]) -> None:
    owner, oid = org
    stages = _stages(owner.api, oid)
    _opp(owner.api, oid, name="Open", stage_id=stages["Proposal"]["id"])
    _opp(owner.api, oid, name="Lost", stage_id=stages["Closed lost"]["id"])
    base = f"/organizations/{oid}/opportunities"
    assert [o["name"] for o in owner.api.get(base).json()] == ["Open"]
    assert len(owner.api.get(base, params={"include_closed": "true"}).json()) == 2


def test_summary_never_mixes_currencies(org: tuple[Any, str]) -> None:
    owner, oid = org
    stages = _stages(owner.api, oid)
    sid = stages["Proposal"]["id"]
    _opp(owner.api, oid, name="A", stage_id=sid, amount="100.50")
    _opp(owner.api, oid, name="B", stage_id=sid, amount="200.00")
    _opp(owner.api, oid, name="C", stage_id=sid, amount="50.00", currency="EUR")
    _opp(owner.api, oid, name="D", stage_id=sid)  # no amount
    summary = owner.api.get(f"/organizations/{oid}/pipeline/summary").json()["stages"]
    proposal = next(s for s in summary if s["name"] == "Proposal")
    assert proposal["count"] == 4
    assert proposal["totals"] == {"USD": "300.50", "EUR": "50.00"}


def test_overview_reflects_stored_records(org: tuple[Any, str]) -> None:
    owner, oid = org
    stages = _stages(owner.api, oid)
    for i, status in enumerate(["new", "qualified", "qualified"]):
        owner.api.post(
            f"/organizations/{oid}/leads", {"email": f"o{i}@example.com", "status": status}
        )
    _opp(owner.api, oid, name="Open", stage_id=stages["Discovery"]["id"], amount="1000")
    _opp(owner.api, oid, name="Won", stage_id=stages["Closed won"]["id"], amount="400")
    o = owner.api.get(f"/organizations/{oid}/analytics/overview").json()
    assert o["leads_total"] == 3 and o["leads_added_30d"] == 3
    assert o["leads_by_status"]["qualified"] == 2
    assert o["open_opportunities"] == 1
    assert o["open_pipeline_value"] == {"USD": "1000.00"}
    assert o["won_value_90d"] == {"USD": "400.00"} and o["won_count_90d"] == 1
    assert o["recent_activity"]


def test_empty_overview_is_all_zero(org: tuple[Any, str]) -> None:
    owner, oid = org
    o = owner.api.get(f"/organizations/{oid}/analytics/overview").json()
    assert o["leads_total"] == 0 and o["open_pipeline_value"] == {} and o["recent_activity"] == []


def test_invalid_amounts_and_currency_rejected(org: tuple[Any, str]) -> None:
    owner, oid = org
    sid = _stages(owner.api, oid)["Proposal"]["id"]
    base = f"/organizations/{oid}/opportunities"
    assert owner.api.post(base, {"name": "x", "stage_id": sid, "amount": "-1"}).status_code == 422
    assert (
        owner.api.post(base, {"name": "x", "stage_id": sid, "currency": "usd"}).status_code == 422
    )


def test_stage_configuration_permissions(org: tuple[Any, str], add_member: Any) -> None:
    owner, oid = org
    rep, _ = add_member(owner, oid, "sales_rep")
    base = f"/organizations/{oid}/pipeline/stages"
    assert rep.api.post(base, {"name": "Demo"}).status_code == 403
    created = owner.api.post(base, {"name": "Demo"})
    assert created.status_code == 201 and created.json()["position"] == 6
    assert owner.api.post(base, {"name": "Demo"}).status_code == 409
    renamed = owner.api.patch(f"{base}/{created.json()['id']}", {"name": "Live demo"})
    assert renamed.json()["name"] == "Live demo"


def test_analyst_can_read_but_not_sell(org: tuple[Any, str], add_member: Any) -> None:
    owner, oid = org
    analyst, _ = add_member(owner, oid, "analyst")
    sid = _stages(owner.api, oid)["Proposal"]["id"]
    assert analyst.api.get(f"/organizations/{oid}/analytics/overview").status_code == 200
    r = analyst.api.post(f"/organizations/{oid}/opportunities", {"name": "x", "stage_id": sid})
    assert r.status_code == 403
