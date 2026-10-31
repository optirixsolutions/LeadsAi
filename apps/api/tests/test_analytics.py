"""Analytics count what is stored, for one organization, and nothing else."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, text

from tests.support.smtp_sink import Sink
from tests.test_intelligence import ICP
from tests.test_outreach import _approved, _configure, _draft, _lead, _request, _send, smtp  # noqa: F401


def _report(user: Any, org: str, days: int = 30) -> dict[str, Any]:
    r = user.api.get(f"/organizations/{org}/analytics/report?days={days}")
    assert r.status_code == 200, r.text
    return r.json()


def test_an_empty_organization_reports_zeros_and_no_rates(make_org: Any) -> None:
    owner, org = make_org()
    r = _report(owner, org, 7)
    assert r["days"] == 7 and len(r["leads"]["added_by_day"]) == 7
    assert sum(d["count"] for d in r["leads"]["added_by_day"]) == 0
    assert r["pipeline"]["win_rate"] is None and r["approvals"]["median_wait_hours"] is None
    assert r["workflows"]["median_minutes"] is None and r["leads"]["by_fit"] == {}
    assert r["leads"]["added_by_day"][-1]["day"] == datetime.now(UTC).date().isoformat()


def test_only_real_windows_are_accepted(make_org: Any) -> None:
    owner, org = make_org()
    assert owner.api.get(f"/organizations/{org}/analytics/report?days=5").status_code == 422


def test_leads_are_counted_by_day_status_and_latest_fit(make_org: Any, clean_db: Engine) -> None:
    owner, org = make_org()
    first, second = _lead(owner, org, "a@example.com"), _lead(owner, org, "b@example.com")
    gone = _lead(owner, org, "c@example.com")
    assert owner.api.delete(f"/organizations/{org}/leads/{gone}").status_code == 204
    icp = owner.api.post(f"/organizations/{org}/icp", ICP).json()["id"]
    with clean_db.begin() as conn:
        for lead, fit, age in ((first, "low", "2 days"), (first, "high", "1 day")):
            conn.execute(
                text(
                    "INSERT INTO lead_scores (id, organization_id, lead_id, icp_configuration_id, "
                    "score, fit, components, reasons, positive_signals, negative_signals, "
                    "missing_information, evidence_ids, evaluation_status, model_version, "
                    "created_at) VALUES "
                    "(gen_random_uuid(), :o, :l, :i, 50, :f, '[]', '[]', '[]', '[]', '[]', "
                    "'{}', "
                    "'pending_review', 'x', now() - cast(:a as interval))"
                ),
                {"o": org, "l": lead, "i": icp, "f": fit, "a": age},
            )
    r = _report(owner, org)
    assert r["leads"]["by_status"] == {"new": 2}
    assert r["leads"]["by_fit"] == {"high": 1, "unscored": 1}
    assert r["leads"]["assessments_awaiting_review"] == 2
    # The deleted lead does not count.
    assert sum(d["count"] for d in r["leads"]["added_by_day"]) == 2

    listed = owner.api.get(f"/organizations/{org}/leads").json()["items"]
    scores = {i["id"]: (i["score"], i["fit"]) for i in listed}
    assert scores == {first: (50, "high"), second: (None, None)}
    high = owner.api.get(f"/organizations/{org}/leads?fit=high").json()
    assert [i["id"] for i in high["items"]] == [first]
    none = owner.api.get(f"/organizations/{org}/leads?fit=none").json()
    assert [i["id"] for i in none["items"]] == [second]
    assert owner.api.get(f"/organizations/{org}/leads?fit=bad").status_code == 422


def test_outreach_and_approvals_are_counted(make_org: Any, smtp: Sink) -> None:  # noqa: F811
    owner, org = make_org()
    _configure(owner, org)
    sent = _approved(owner, org)
    assert _send(owner, org, sent["id"]).json()["status"] == "accepted"
    ready = _approved(owner, org, _lead(owner, org, "ready@example.com"))
    waiting = _draft(owner, org, _lead(owner, org, "waiting@example.com"))
    _request(owner, org, waiting["id"])
    owner.api.post(f"/organizations/{org}/outreach/suppressions", {"value": "no@example.com"})

    r = _report(owner, org)
    assert r["outreach"]["deliveries_by_status"] == {"accepted": 1}
    assert r["outreach"]["drafts_by_status"] == {"sent": 1, "approved": 1, "pending_approval": 1}
    assert r["outreach"]["accepted_by_day"][-1]["count"] == 1
    assert r["outreach"]["suppressions_by_reason"] == {"manual": 1}
    assert r["approvals"]["approved"] == 2 and r["approvals"]["waiting"] == 1
    assert r["approvals"]["median_wait_hours"] is not None

    a = owner.api.get(f"/organizations/{org}/analytics/attention").json()
    assert a["approvals_waiting"] == 1 and a["drafts_ready_to_send"] == 1
    assert a["outcomes_unknown"] == 0 and a["workflows_failed_7d"] == 0
    assert ready["id"] != sent["id"]


def test_win_rate_counts_closed_deals_and_never_mixes_currencies(
    make_org: Any, clean_db: Engine
) -> None:
    owner, org = make_org()
    stages = owner.api.get(f"/organizations/{org}/pipeline/stages").json()
    lead = _lead(owner, org)
    by_kind = {s["kind"]: s["id"] for s in stages}
    for name, kind, amount, currency in (
        ("A", "won", "100.00", "USD"),
        ("B", "won", "50.00", "EUR"),
        ("C", "lost", "70.00", "USD"),
        ("D", "open", "90.00", "USD"),
    ):
        r = owner.api.post(
            f"/organizations/{org}/opportunities",
            {
                "name": name,
                "lead_id": lead,
                "stage_id": by_kind[kind],
                "amount": amount,
                "currency": currency,
            },
        )
        assert r.status_code == 201, r.text
    p = _report(owner, org)["pipeline"]
    assert p["opened"] == 4 and p["won"] == 2 and p["lost"] == 1
    assert p["win_rate"] == 0.667
    assert {k: float(v) for k, v in p["won_value"].items()} == {"USD": 100.0, "EUR": 50.0}


def test_another_organization_sees_none_of_it(make_org: Any) -> None:
    owner, org = make_org()
    _lead(owner, org)
    other, other_org = make_org("Other")
    assert other.api.get(f"/organizations/{org}/analytics/report").status_code == 404
    assert other.api.get(f"/organizations/{org}/analytics/attention").status_code == 404
    assert _report(other, other_org)["leads"]["by_status"] == {}


def test_an_analyst_can_read_analytics(make_org: Any, add_member: Any) -> None:
    owner, org = make_org()
    analyst, _ = add_member(owner, org, "analyst")
    assert analyst.api.get(f"/organizations/{org}/analytics/report").status_code == 200
