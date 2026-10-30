"""Phase 6 acceptance: a failed workflow can be diagnosed and resumed without duplicating effects.

Model failures here are real HTTP responses from a real local server, and the crash test kills a
real worker process. Nothing in the workflow code is stubbed.
"""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import ormsgpack
import pytest
from langgraph.checkpoint.serde.jsonplus import EXT_CONSTRUCTOR_SINGLE_ARG
from sqlalchemy import Engine, text

from app.services.brief_service import get_registry
from app.workflows import runner
from app.workflows.runner import drain
from tests.conftest import API_ROOT, APP_DB_URL, Api
from tests.test_intelligence import ICP, _lead, _set_company
from tests.test_llm import needs_ollama

GOOD_NOTE = "They need lead scoring and issued a request for proposals this quarter."


class ModelServer:
    """A real endpoint for the model client to talk to; its behaviour can change between calls."""

    def __init__(self) -> None:
        self.status = 404
        self.hang = threading.Event()
        self.release = threading.Event()
        self.received = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length", 0)))
                owner.received.set()
                if owner.hang.is_set():
                    owner.release.wait(60)
                body = json.dumps({"error": "from test server"}).encode()
                self.send_response(owner.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModelServer]:
    server = ModelServer()
    monkeypatch.setenv("SALESIQ_OLLAMA_BASE_URL", server.url)
    get_registry.cache_clear()
    yield server
    get_registry.cache_clear()
    server.close()


@pytest.fixture
def setup(make_org: Any, clean_db: Engine) -> tuple[Any, str, dict[str, Any]]:
    owner, org = make_org()
    assert owner.api.post(f"/organizations/{org}/icp", ICP).status_code == 201
    lead = _lead(owner, org)
    _set_company(clean_db, lead["company"]["id"])
    r = owner.api.post(f"/organizations/{org}/leads/{lead['id']}/evidence", {"content": GOOD_NOTE})
    assert r.status_code == 201
    return owner, org, lead


def _start(owner: Any, org: str, lead: dict[str, Any], **body: Any) -> dict[str, Any]:
    r = owner.api.post(f"/organizations/{org}/leads/{lead['id']}/workflows", body)
    assert r.status_code == 202, r.text
    return r.json()


def _get(owner: Any, org: str, run_id: str) -> dict[str, Any]:
    return owner.api.get(f"/organizations/{org}/workflows/{run_id}").json()


def _count(db: Engine, table: str, lead: dict[str, Any]) -> int:
    with db.begin() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE lead_id = :l"),  # noqa: S608
            {"l": lead["id"]},
        ).scalar_one()


def _steps(detail: dict[str, Any]) -> list[tuple[str, str]]:
    return [(s["name"], s["status"]) for s in detail["steps"]]


def test_acceptance_failed_run_is_diagnosed_and_resumed_without_duplicates(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.status = 503  # A transient outage: retried, then the run fails.
    run = _start(owner, org, lead)
    assert run["status"] == "queued"
    drain()

    failed = _get(owner, org, run["id"])
    # Diagnosed: what failed, why, what to do, and how far it got.
    assert failed["status"] == "failed" and failed["resumable"]
    assert failed["error_category"] == "unavailable"
    assert "could not be reached" in failed["error_message"]
    assert "from test server" not in failed["error_message"], "provider text stays in logs"
    assert failed["current_step"] == "interpret"
    steps = _steps(failed)
    assert ("score_lead", "succeeded") in steps
    assert steps.count(("interpret", "failed")) == 1
    failed_step = next(s for s in failed["steps"] if s["status"] == "failed")
    assert failed_step["detail"]["attempts"] == "3", "the client's bounded retries are visible"
    assert _count(clean_db, "lead_scores", lead) == 1

    # Resumed: from the checkpoint, so finished steps do not run again.
    model.status = 404  # The outage ends; the model is simply missing now.
    r = owner.api.post(f"/organizations/{org}/workflows/{run['id']}/resume")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    drain()

    done = _get(owner, org, run["id"])
    assert done["status"] == "succeeded", done
    steps = _steps(done)
    assert steps.count(("score_lead", "succeeded")) == 1
    assert steps.count(("gather_evidence", "succeeded")) == 1
    assert done["result"]["decision"] == "escalated"
    assert any("usable brief" in reason for reason in done["result"]["escalation_reasons"])

    assert _count(clean_db, "lead_scores", lead) == 1
    assert _count(clean_db, "research_briefs", lead) == 1
    with clean_db.begin() as conn:
        assessed = conn.execute(
            text("SELECT count(*) FROM activities WHERE lead_id = :l AND type = 'assessed'"),
            {"l": lead["id"]},
        ).scalar_one()
    assert assessed == 1
    assert owner.api.post(f"/organizations/{org}/workflows/{run['id']}/resume").status_code == 409


def test_killed_worker_is_recovered_from_its_checkpoint(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.hang.set()
    run = _start(owner, org, lead)
    env = {
        **os.environ,
        "SALESIQ_OLLAMA_BASE_URL": model.url,
        "SALESIQ_DATABASE_URL": APP_DB_URL,
        "SALESIQ_WORKER_LEASE_SECONDS": "2",
        "SALESIQ_WORKER_POLL_SECONDS": "0.2",
        "SALESIQ_WORKER_CONCURRENCY": "1",
    }
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.tasks.worker"],
        cwd=API_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = _get(owner, org, run["id"])
            if ("interpret", "running") in _steps(detail):
                break
            time.sleep(0.2)
        else:
            pytest.fail(f"worker never reached the model step: {detail}")
    finally:
        worker.kill()
        worker.wait()
    assert _get(owner, org, run["id"])["status"] == "running"
    assert _count(clean_db, "lead_scores", lead) == 1

    # Nothing renews the lease now, so another worker recovers the run once it expires.
    model.hang.clear()
    model.release.set()
    deadline = time.monotonic() + 15
    while not drain("recovery") and time.monotonic() < deadline:
        time.sleep(0.2)

    done = _get(owner, org, run["id"])
    assert done["status"] == "succeeded", done
    assert done["attempts"] == 2
    steps = _steps(done)
    assert ("interpret", "interrupted") in steps, "the trace shows the crash"
    assert steps.count(("score_lead", "succeeded")) == 1, "not repeated after recovery"
    assert _count(clean_db, "lead_scores", lead) == 1
    assert _count(clean_db, "research_briefs", lead) == 1


def test_run_that_keeps_losing_workers_stops_trying(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE workflow_runs SET status = 'running', attempts = max_attempts, "
                "lease_owner = 'gone', lease_expires_at = now() - interval '1 minute'"
            )
        )
    assert drain() == 0
    failed = _get(owner, org, run["id"])
    assert failed["status"] == "failed" and failed["error_category"] == "attempts_exhausted"
    assert failed["resumable"]


def test_lost_lease_stops_the_old_worker_from_writing(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    claim = runner.claim_next("old-worker", 60)
    assert claim is not None
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE workflow_runs SET lease_owner = 'new-worker'"))
    runner.execute(claim, "old-worker", 60)
    detail = _get(owner, org, run["id"])
    assert detail["status"] == "running", "still the new worker's to finish"
    assert detail["steps"] == []
    assert _count(clean_db, "lead_scores", lead) == 0


def test_cancel_while_queued_is_immediate(setup: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    r = owner.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert drain() == 0
    assert owner.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel").status_code == 409
    # A cancelled run no longer blocks the lead.
    _start(owner, org, lead)


def test_cancel_during_a_run_stops_before_the_next_step(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.hang.set()
    run = _start(owner, org, lead)
    worker = threading.Thread(target=drain)
    worker.start()
    deadline = time.monotonic() + 20
    while ("interpret", "running") not in _steps(_get(owner, org, run["id"])):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    r = owner.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert r.json()["cancel_requested_at"]
    model.hang.clear()
    model.release.set()
    worker.join(30)

    done = _get(owner, org, run["id"])
    assert done["status"] == "cancelled", done
    assert ("quality_review", "succeeded") not in _steps(done)


def test_brief_from_a_cancelled_run_is_not_left_running(setup: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    base = f"/organizations/{org}/leads/{lead['id']}"
    assert owner.api.post(f"{base}/briefs").status_code == 202
    run = owner.api.get(f"/organizations/{org}/workflows").json()[0]
    owner.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel")
    brief = owner.api.get(f"{base}/briefs/latest").json()
    assert brief["status"] == "failed" and brief["failure_category"] == "cancelled"


def test_escalated_result_proposes_no_status_change(setup: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead, propose_status=True)  # The model answers 404, so no brief.
    drain()
    done = _get(owner, org, run["id"])
    assert done["status"] == "succeeded", done
    assert done["result"]["decision"] == "escalated"
    assert done["approval_request"] is None
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "new"


@needs_ollama
def test_real_run_with_approval_end_to_end(setup: Any, add_member: Any, clean_db: Engine) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead, propose_status=True)
    drain()
    waiting = _get(owner, org, run["id"])
    assert waiting["status"] in ("waiting_approval", "succeeded"), waiting
    if waiting["status"] == "succeeded":
        # The real model's brief was escalated, which is a valid outcome and changes nothing.
        assert waiting["result"]["decision"] == "escalated"
        return
    assert waiting["approval_request"]["to"] == "qualified"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "new"

    rep, _ = add_member(owner, org, "sales_rep")
    url = f"/organizations/{org}/workflows/{run['id']}/decision"
    assert rep.api.post(url, {"decision": "approved"}).status_code == 403
    assert owner.api.post(url, {"decision": "approved"}).status_code == 200
    assert owner.api.post(url, {"decision": "approved"}).status_code == 409
    drain()

    done = _get(owner, org, run["id"])
    assert done["status"] == "succeeded", done
    assert done["result"]["approval"] == "approved"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "qualified"
    scores = owner.api.get(f"/organizations/{org}/leads/{lead['id']}/assessments").json()
    assert len(scores) == 1 and scores[0]["evaluation_status"] == "approved"


def _waiting_run(owner: Any, org: str, lead: dict[str, Any], db: Engine) -> str:
    """A run paused for approval, reached through the real graph with a model-free brief."""
    run = _start(owner, org, lead, propose_status=True)
    with db.begin() as conn:
        # Finish the brief up front, as a resumed run would find it, so nothing escalates.
        conn.execute(
            text(
                "INSERT INTO research_briefs (id, organization_id, lead_id, workflow_run_id, "
                "status, model_key, prompt_version) VALUES "
                "(gen_random_uuid(), :o, :l, :r, 'completed', 'm', 'p')"
            ),
            {"o": org, "l": lead["id"], "r": run["id"]},
        )
    drain()
    detail = _get(owner, org, run["id"])
    assert detail["status"] == "waiting_approval", detail
    return run["id"]


def test_approval_applies_the_change_exactly_once(
    setup: Any, add_member: Any, clean_db: Engine
) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    request = _get(owner, org, run_id)["approval_request"]
    assert request["from"] == "new" and request["to"] == "qualified"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "new"

    url = f"/organizations/{org}/workflows/{run_id}/decision"
    rep, _ = add_member(owner, org, "sales_rep")
    assert rep.api.post(url, {"decision": "approved"}).status_code == 403
    assert owner.api.post(url, {"decision": "maybe"}).status_code == 422
    assert owner.api.post(url, {"decision": "approved"}).status_code == 200
    assert owner.api.post(url, {"decision": "approved"}).status_code == 409
    drain()

    done = _get(owner, org, run_id)
    assert done["status"] == "succeeded", done
    assert done["result"]["approval"] == "approved"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "qualified"
    scores = owner.api.get(f"/organizations/{org}/leads/{lead['id']}/assessments").json()
    assert len(scores) == 1 and scores[0]["evaluation_status"] == "approved"
    with clean_db.begin() as conn:
        changes = conn.execute(
            text("SELECT count(*) FROM activities WHERE lead_id = :l AND type = 'status_changed'"),
            {"l": lead["id"]},
        ).scalar_one()
    assert changes == 1


def test_rejection_changes_nothing_on_the_lead(setup: Any, clean_db: Engine) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "rejected"})
    drain()
    assert _get(owner, org, run_id)["status"] == "succeeded"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "new"
    scores = owner.api.get(f"/organizations/{org}/leads/{lead['id']}/assessments").json()
    assert scores[0]["evaluation_status"] == "rejected"


def test_approval_does_not_overwrite_a_newer_choice(setup: Any, clean_db: Engine) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    r = owner.api.patch(f"/organizations/{org}/leads/{lead['id']}", {"status": "contacted"})
    assert r.status_code == 200
    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "approved"})
    drain()
    assert _get(owner, org, run_id)["status"] == "succeeded"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "contacted"


def test_checkpoints_hold_no_lead_data_and_are_removed_when_finished(
    setup: Any, clean_db: Engine
) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    with clean_db.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT convert_from(blob, 'latin1') FROM workflow_state.checkpoint_blobs "
                "WHERE thread_id = :t AND blob IS NOT NULL"
            ),
            {"t": run_id},
        ).all()
        rows += conn.execute(
            text("SELECT checkpoint::text FROM workflow_state.checkpoints WHERE thread_id = :t"),
            {"t": run_id},
        ).all()
    stored = " ".join(str(r[0]) for r in rows)
    assert rows, "the paused run has a checkpoint"
    assert "lead scoring" not in stored and lead["email"] not in stored

    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "rejected"})
    drain()
    with clean_db.begin() as conn:
        left = conn.execute(
            text("SELECT count(*) FROM workflow_state.checkpoints WHERE thread_id = :t"),
            {"t": run_id},
        ).scalar_one()
    assert left == 0


def test_requester_who_left_cannot_keep_acting(
    make_org: Any, add_member: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org = make_org()
    owner.api.post(f"/organizations/{org}/icp", ICP)
    rep, membership = add_member(owner, org, "sales_rep")
    lead = _lead(rep, org)
    run = _start(rep, org, lead)
    assert owner.api.delete(f"/organizations/{org}/members/{membership}").status_code < 300
    drain()
    failed = _get(owner, org, run["id"])
    assert failed["status"] == "failed", failed
    assert failed["error_category"] == "access_lost"
    assert "no longer has access" in failed["error_message"]
    assert not failed["resumable"], "no resume can bring that back"
    assert owner.api.post(f"/organizations/{org}/workflows/{run['id']}/resume").status_code == 409
    assert _count(clean_db, "lead_scores", lead) == 0


def test_deleted_lead_fails_without_reaching_a_model(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    owner.api.delete(f"/organizations/{org}/leads/{lead['id']}")
    drain()
    with clean_db.begin() as conn:
        status = conn.execute(text("SELECT status FROM workflow_runs")).scalar_one()
    assert status == "failed"
    assert _count(clean_db, "research_briefs", lead) == 0
    # A run's result goes with its lead, like the lead's other records.
    url = f"/organizations/{org}/workflows"
    assert owner.api.get(f"{url}/{run['id']}").status_code == 404
    assert owner.api.get(url).json() == []


def test_no_icp_is_a_clear_failure(make_org: Any, model: ModelServer) -> None:
    owner, org = make_org()
    lead = _lead(owner, org)
    run = _start(owner, org, lead)
    drain()
    failed = _get(owner, org, run["id"])
    assert failed["error_category"] == "request_invalid"
    assert "ideal customer profile" in failed["error_message"]


def test_one_active_run_per_lead(setup: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    _start(owner, org, lead)
    url = f"/organizations/{org}/leads/{lead['id']}/workflows"
    assert owner.api.post(url, {}).status_code == 409
    assert owner.api.post(f"/organizations/{org}/leads/{lead['id']}/briefs").status_code == 409


def test_org_limit_on_active_runs(setup: Any, clean_db: Engine) -> None:
    owner, org, _ = setup
    other = _lead(owner, org)
    with clean_db.begin() as conn:
        for _ in range(20):
            lead_id = conn.execute(
                text(
                    "INSERT INTO leads (id, organization_id, status) "
                    "VALUES (gen_random_uuid(), :o, 'new') RETURNING id"
                ),
                {"o": org},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO workflow_runs (id, organization_id, lead_id, kind, status, input, "
                    "deadline_at, created_by_user_id) VALUES (gen_random_uuid(), :o, :l, "
                    "'research', 'queued', '{}', now() + interval '1 hour', :u)"
                ),
                {"o": org, "l": lead_id, "u": owner.id},
            )
    r = owner.api.post(f"/organizations/{org}/leads/{other['id']}/workflows", {})
    assert r.status_code == 429


def test_validation_and_permissions(setup: Any, add_member: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    url = f"/organizations/{org}/leads/{lead['id']}/workflows"
    assert owner.api.post(url, {"urls": ["https://a.example"] * 4}).status_code == 422
    assert owner.api.post(url, {"unknown": 1}).status_code == 422
    analyst, _ = add_member(owner, org, "analyst")
    assert analyst.api.post(url, {}).status_code == 403
    run = _start(owner, org, lead)
    assert analyst.api.get(f"/organizations/{org}/workflows/{run['id']}").status_code == 200
    assert analyst.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel").status_code == 403
    assert analyst.api.post(f"/organizations/{org}/workflows/{run['id']}/resume").status_code == 403


def test_cross_tenant_access_is_404(setup: Any, make_org: Any, model: ModelServer) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    other, other_org = make_org("Other")
    assert other.api.get(f"/organizations/{org}/workflows/{run['id']}").status_code == 404
    theirs = f"/organizations/{other_org}/workflows/{run['id']}"
    assert other.api.get(theirs).status_code == 404
    assert other.api.post(f"{theirs}/cancel").status_code == 404
    assert other.api.post(f"{theirs}/resume").status_code == 404
    assert other.api.post(f"{theirs}/decision", {"decision": "approved"}).status_code == 404
    url = f"/organizations/{other_org}/leads/{lead['id']}/workflows"
    assert other.api.post(url, {}).status_code == 404
    assert other.api.get(f"/organizations/{other_org}/workflows").json() == []


def test_rls_hides_runs_without_tenant_context_and_claim_is_the_only_way_across(
    setup: Any, model: ModelServer, app_engine: Engine
) -> None:
    owner, org, lead = setup
    _start(owner, org, lead)
    with app_engine.connect() as conn:
        for table in ("workflow_runs", "workflow_steps"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table  # noqa: S608
        conn.rollback()
    with app_engine.begin() as conn, pytest.raises(Exception, match="permission denied"):
        conn.execute(text("DELETE FROM workflow_runs"))


def test_worker_health_needs_a_session_and_reports_no_worker(make_user: Any) -> None:
    assert Api().get("/workers/health").status_code == 401
    user = make_user()
    assert user.api.get("/workers/health").json() == {"alive": False}


@pytest.mark.parametrize(
    "variable", ["LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2"]
)
def test_tracing_stays_off_even_if_the_environment_turns_it_on(variable: str) -> None:
    code = (
        "import app.workflows.runner;"
        "from langsmith.utils import tracing_is_enabled;"
        "print(bool(tracing_is_enabled()))"
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        env={**os.environ, variable: "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert out.stdout.strip().endswith("False"), out.stdout


def test_checkpoint_reader_will_not_construct_objects_from_a_stored_blob(
    tmp_path: Path,
) -> None:
    """A row in the checkpoint tables must never be able to run code in the worker."""
    marker = tmp_path / "planted"
    payload = ormsgpack.packb(
        ormsgpack.Ext(EXT_CONSTRUCTOR_SINGLE_ARG, ormsgpack.packb(("os", "mkdir", str(marker))))
    )
    runner.checkpoint_serde().loads_typed(("msgpack", payload))
    assert not marker.exists()


def _crash_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker dies right after the graph finishes, before it records the outcome."""
    real = runner._record_outcome
    calls = {"n": 0}

    def dying(*args: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("worker died here")
        real(*args)

    monkeypatch.setattr(runner, "_record_outcome", dying)


def _expire_lease(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            text("UPDATE workflow_runs SET lease_expires_at = now() - interval '1 minute'")
        )


def test_crash_after_the_last_step_does_not_lose_a_rejection(
    setup: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "rejected"})
    _crash_once(monkeypatch)
    with pytest.raises(RuntimeError, match="worker died"):
        drain()
    _expire_lease(clean_db)
    drain()

    done = _get(owner, org, run_id)
    assert done["status"] == "succeeded", done
    assert done["result"]["approval"] == "rejected", "the decision is not asked for again"
    assert _steps(done).count(("score_lead", "succeeded")) == 1
    with clean_db.begin() as conn:
        audits = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE action = 'workflow.completed'")
        ).scalar_one()
    assert audits == 1


def test_crash_after_the_last_step_of_a_plain_run_only_records_the_outcome(
    setup: Any, model: ModelServer, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, lead = setup
    run = _start(owner, org, lead)
    _crash_once(monkeypatch)
    with pytest.raises(RuntimeError, match="worker died"):
        drain()
    _expire_lease(clean_db)
    drain()
    done = _get(owner, org, run["id"])
    assert done["status"] == "succeeded", done
    assert _steps(done).count(("score_lead", "succeeded")) == 1
    assert _steps(done).count(("finalize", "succeeded")) == 1


def test_decision_is_recorded_under_the_person_who_made_it(
    make_org: Any, add_member: Any, clean_db: Engine
) -> None:
    owner, org = make_org()
    owner.api.post(f"/organizations/{org}/icp", ICP)
    rep, _ = add_member(owner, org, "sales_rep")
    manager, _ = add_member(owner, org, "manager")
    lead = _lead(rep, org)
    _set_company(clean_db, lead["company"]["id"])
    rep.api.post(f"/organizations/{org}/leads/{lead['id']}/evidence", {"content": GOOD_NOTE})
    run_id = _waiting_run(rep, org, lead, clean_db)

    r = manager.api.post(
        f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "approved"}
    )
    assert r.status_code == 200
    drain()

    done = _get(owner, org, run_id)
    assert done["status"] == "succeeded", done
    assert done["result"]["proposal_applied"] is True
    score = owner.api.get(f"/organizations/{org}/leads/{lead['id']}/assessments").json()[0]
    assert score["reviewed_by_user_id"] == manager.id, "not the rep, who cannot review"
    with clean_db.begin() as conn:
        actor = conn.execute(
            text("SELECT actor_user_id FROM activities WHERE type = 'status_changed'")
        ).scalar_one()
    assert str(actor) == manager.id


def test_approved_change_still_applies_after_the_requester_leaves(
    make_org: Any, add_member: Any, clean_db: Engine
) -> None:
    owner, org = make_org()
    owner.api.post(f"/organizations/{org}/icp", ICP)
    rep, membership = add_member(owner, org, "sales_rep")
    lead = _lead(rep, org)
    _set_company(clean_db, lead["company"]["id"])
    rep.api.post(f"/organizations/{org}/leads/{lead['id']}/evidence", {"content": GOOD_NOTE})
    run_id = _waiting_run(rep, org, lead, clean_db)
    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "approved"})
    assert owner.api.delete(f"/organizations/{org}/members/{membership}").status_code < 300
    drain()
    assert _get(owner, org, run_id)["status"] == "succeeded"
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "qualified"


def test_approval_does_not_override_a_direct_rejection(setup: Any, clean_db: Engine) -> None:
    owner, org, lead = setup
    run_id = _waiting_run(owner, org, lead, clean_db)
    assessment = _get(owner, org, run_id)["approval_request"]["assessment_id"]
    r = owner.api.patch(
        f"/organizations/{org}/assessments/{assessment}", {"evaluation_status": "rejected"}
    )
    assert r.status_code == 200
    owner.api.post(f"/organizations/{org}/workflows/{run_id}/decision", {"decision": "approved"})
    drain()
    done = _get(owner, org, run_id)
    assert done["result"]["proposal_applied"] is False
    assert owner.api.get(f"/organizations/{org}/leads/{lead['id']}").json()["status"] == "new"


def test_demoted_requester_stops_at_the_next_step(
    make_org: Any, add_member: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org = make_org()
    owner.api.post(f"/organizations/{org}/icp", ICP)
    rep, membership = add_member(owner, org, "sales_rep")
    lead = _lead(rep, org)
    run = _start(rep, org, lead)
    r = owner.api.patch(f"/organizations/{org}/members/{membership}", {"role": "analyst"})
    assert r.status_code < 300
    drain()
    failed = _get(owner, org, run["id"])
    assert failed["status"] == "failed" and failed["error_category"] == "request_invalid"
    assert _count(clean_db, "lead_scores", lead) == 0


def test_failed_run_checkpoint_holds_neither_addresses_nor_provider_text(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    secret_path = "private-page-name"
    model.status = 503
    run = _start(owner, org, lead, urls=[f"https://blocked.example/{secret_path}?token=abc"])
    drain()
    failed = _get(owner, org, run["id"])
    assert failed["status"] == "failed", failed
    # The person running it can still see the address, in the trace, under RLS.
    gather = next(s for s in failed["steps"] if s["name"] == "gather_evidence")
    assert secret_path in gather["detail"]["fetch_problems"][0]
    with clean_db.begin() as conn:
        stored = b"".join(
            bytes(row[0])
            for table in ("checkpoint_blobs", "checkpoint_writes")
            for row in conn.execute(
                text(
                    f"SELECT blob FROM workflow_state.{table} "  # noqa: S608
                    "WHERE thread_id = :t AND blob IS NOT NULL"
                ),
                {"t": run["id"]},
            )
        )
    assert stored, "the failed run keeps a checkpoint to resume from"
    assert secret_path.encode() not in stored
    assert b"from test server" not in stored


def test_sweep_removes_only_checkpoints_nothing_will_read(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.status = 503
    run = _start(owner, org, lead)
    drain()

    def left() -> int:
        with clean_db.begin() as conn:
            return conn.execute(
                text("SELECT count(*) FROM workflow_state.checkpoints WHERE thread_id = :t"),
                {"t": run["id"]},
            ).scalar_one()

    assert left() > 0
    runner.sweep_checkpoints()
    assert left() > 0, "a recent failure can still be resumed"
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE workflow_runs SET finished_at = now() - interval '31 days'"))
    runner.sweep_checkpoints()
    assert left() == 0


def test_resume_clears_an_old_cancel_request(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.status = 404
    run = _start(owner, org, lead)
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE workflow_runs SET status = 'failed', error_category = 'timeout', "
                "cancel_requested_at = now()"
            )
        )
    assert owner.api.post(f"/organizations/{org}/workflows/{run['id']}/resume").status_code == 200
    drain()
    assert _get(owner, org, run["id"])["status"] == "succeeded"


def test_cancel_requested_during_a_failing_step_ends_as_cancelled(
    setup: Any, model: ModelServer
) -> None:
    owner, org, lead = setup
    model.status = 503
    model.hang.set()
    run = _start(owner, org, lead)
    worker = threading.Thread(target=drain)
    worker.start()
    deadline = time.monotonic() + 20
    while ("interpret", "running") not in _steps(_get(owner, org, run["id"])):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    owner.api.post(f"/organizations/{org}/workflows/{run['id']}/cancel")
    model.hang.clear()
    model.release.set()
    worker.join(60)
    done = _get(owner, org, run["id"])
    assert done["status"] == "cancelled", done
    assert not done["resumable"]


def test_late_answer_from_a_worker_that_lost_its_lease_is_dropped(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    model.hang.set()
    _start(owner, org, lead)
    worker = threading.Thread(target=drain)
    worker.start()
    assert model.received.wait(20), "the worker reached the model"
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE workflow_runs SET lease_owner = 'new-worker'"))
        conn.execute(text("UPDATE research_briefs SET status = 'completed'"))
    model.hang.clear()
    model.release.set()
    worker.join(30)
    with clean_db.begin() as conn:
        status = conn.execute(text("SELECT status FROM research_briefs")).scalar_one()
    assert status == "completed", "the new worker's result is not overwritten"


def test_brief_left_running_by_an_ended_run_does_not_block_the_lead(
    setup: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    base = f"/organizations/{org}/leads/{lead['id']}"
    assert owner.api.post(f"{base}/briefs").status_code == 202
    # A worker ran out of attempts: the claim function touches only the run, not its brief.
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE workflow_runs SET status = 'failed'"))
    assert owner.api.post(f"{base}/briefs").status_code == 202


def test_claim_prefers_organizations_with_nothing_running(
    setup: Any, make_org: Any, model: ModelServer, clean_db: Engine
) -> None:
    owner, org, lead = setup
    busy = _lead(owner, org)
    _start(owner, org, busy)
    assert runner.claim_next("first", 60) is not None
    _start(owner, org, lead)  # Older than the other organization's run, by a moment.
    other, other_org = make_org("Other")
    other.api.post(f"/organizations/{other_org}/icp", ICP)
    theirs = _lead(other, other_org)
    _start(other, other_org, theirs)
    claim = runner.claim_next("second", 60)
    assert claim is not None and str(claim.org_id) == other_org
