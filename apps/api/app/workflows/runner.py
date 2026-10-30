"""Claims a run, drives its graph from the last checkpoint, and records how it ended."""

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from psycopg.rows import dict_row
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from app.agents.llm import LLMError
from app.core.auth import worker_context
from app.core.config import get_settings
from app.core.db import get_sessionmaker, set_tenant_context
from app.core.errors import AppError, LeaseLostError, RequestInvalidError
from app.core.permissions import Permission, has_permission
from app.integrations.fetcher import FetchFailedError
from app.models import (
    BriefStatus,
    ImportStatus,
    LeadImport,
    ResearchBrief,
    StepStatus,
    WorkflowKind,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
)
from app.services import audit, csv_service
from app.workflows.graphs import compile_graph
from app.workflows.nodes import WorkflowStoppedError
from app.workflows.state import STATE_VERSION, WorkflowState

log = logging.getLogger(__name__)

# LangGraph ships a LangSmith client. Nothing about a run may leave this deployment.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"

CHECKPOINT_SCHEMA = "workflow_state"
RECURSION_LIMIT = 30
MAX_RUNNING_PER_ORG = 3
# An import has no heartbeat, as one transaction holds it all. This comfortably exceeds the 36 s
# measured for the largest allowed file.
IMPORT_LEASE_S = 600
# Failed runs keep their checkpoint this long so they can be resumed.
FAILED_RETENTION_DAYS = 30

# Shown to the people who run workflows. Provider error text stays in the logs, since it can
# carry hostnames and internal detail.
_DIAGNOSES = {
    "unavailable": "The model server could not be reached. Check that it is running, then resume.",
    "timeout": "The model did not answer in time. Resume to try again.",
    "model_not_found": "The configured model is not installed on the model server.",
    "unauthorized": "The model provider rejected the credentials.",
    "insufficient_resources": "The model server does not have enough memory for this model.",
    "fetch_failed": "A requested page could not be read. Resume to try again.",
    "request_invalid": "This run can no longer be carried out.",
    "deadline": "The run passed its time limit. Resume to give it more time.",
    "access_lost": "The person who started this run no longer has access. Start a new run.",
}


@dataclass(frozen=True)
class Claim:
    run_id: uuid.UUID
    org_id: uuid.UUID
    actor_id: uuid.UUID
    kind: WorkflowKind


def checkpoint_conninfo() -> str:
    """The app role's own connection, as libpq understands it, scoped to the checkpoint schema."""
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def claim_next(owner: str, lease_s: int) -> Claim | None:
    """Claim through a narrow SECURITY DEFINER function, as this needs to see every tenant."""
    with get_sessionmaker()() as db:
        row = db.execute(
            text("SELECT * FROM workflow_claim(:owner, :lease, :per_org)"),
            {"owner": owner, "lease": lease_s, "per_org": MAX_RUNNING_PER_ORG},
        ).first()
        db.commit()
    if row is None:
        return None
    return Claim(row.id, row.organization_id, row.created_by_user_id, WorkflowKind(row.kind))


class _Heartbeat(threading.Thread):
    """Extends the lease while a long step runs. A dead worker stops extending, so its run is
    picked up by another worker once the lease expires."""

    def __init__(self, claim: Claim, owner: str, lease_s: int) -> None:
        super().__init__(daemon=True)
        self._claim, self._owner, self._lease_s = claim, owner, lease_s
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(max(1.0, self._lease_s / 3)):
            try:
                with get_sessionmaker()() as db:
                    set_tenant_context(db, user_id=self._claim.actor_id, org_id=self._claim.org_id)
                    db.execute(
                        update(WorkflowRun)
                        .where(
                            WorkflowRun.id == self._claim.run_id,
                            WorkflowRun.lease_owner == self._owner,
                        )
                        .values(
                            lease_expires_at=datetime.now(UTC) + timedelta(seconds=self._lease_s)
                        )
                    )
                    db.commit()
            except Exception as exc:
                log.warning("lease_renewal_failed", extra={"error_type": type(exc).__name__})

    def stop(self) -> None:
        self._stop_event.set()


def _finish(claim: Claim, owner: str, **values: Any) -> bool:
    """Write the outcome only if this worker still holds the lease. Returns whether it did."""
    with get_sessionmaker()() as db:
        set_tenant_context(db, user_id=claim.actor_id, org_id=claim.org_id)
        updated = db.scalar(
            update(WorkflowRun)
            .where(WorkflowRun.id == claim.run_id, WorkflowRun.lease_owner == owner)
            .values(lease_owner=None, lease_expires_at=None, **values)
            .returning(WorkflowRun.id)
        )
        if updated is None:
            db.rollback()
            return False
        status = values.get("status")
        requested = db.scalar(
            select(WorkflowRun.cancel_requested_at).where(WorkflowRun.id == claim.run_id)
        )
        if requested is not None and status != WorkflowStatus.succeeded:
            # Someone asked to stop this run, so it does not wait or offer to resume.
            status = WorkflowStatus.cancelled
            db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == claim.run_id)
                .values(
                    status=status,
                    error_category=None,
                    error_message=None,
                    finished_at=datetime.now(UTC),
                )
            )
            values = {**values, "status": status, "error_category": None}
        if status in (WorkflowStatus.failed, WorkflowStatus.cancelled):
            # A brief cannot outlive its run: it is failed or cancelled along with it.
            db.execute(
                update(ResearchBrief)
                .where(
                    ResearchBrief.workflow_run_id == claim.run_id,
                    ResearchBrief.status == BriefStatus.running,
                )
                .values(
                    status=BriefStatus.failed,
                    failure_category=values.get("error_category") or "cancelled",
                    completed_at=datetime.now(UTC),
                )
            )
            audit.record(
                db,
                f"workflow.{status.value}",
                org_id=claim.org_id,
                actor_id=claim.actor_id,
                target_type="workflow_run",
                target_id=claim.run_id,
                data={"category": values.get("error_category")},
            )
        db.commit()
    return True


def _mark_interrupted_steps(claim: Claim) -> None:
    """Steps still marked running were cut off by a crash; the trace should say so."""
    with get_sessionmaker()() as db:
        set_tenant_context(db, user_id=claim.actor_id, org_id=claim.org_id)
        db.execute(
            update(WorkflowStep)
            .where(WorkflowStep.run_id == claim.run_id, WorkflowStep.status == StepStatus.running)
            .values(status=StepStatus.interrupted, finished_at=datetime.now(UTC))
        )
        db.commit()


def _pending_decision(claim: Claim) -> str | None:
    with get_sessionmaker()() as db:
        set_tenant_context(db, user_id=claim.actor_id, org_id=claim.org_id)
        decision = db.scalar(
            select(WorkflowRun.approval_decision).where(WorkflowRun.id == claim.run_id)
        )
        db.commit()
    return str(decision["decision"]) if decision else None


def _initial_state(claim: Claim) -> WorkflowState:
    return {
        "state_version": STATE_VERSION,
        "run_id": str(claim.run_id),
        "org_id": str(claim.org_id),
        "actor_id": str(claim.actor_id),
        "lead_id": _lead_id(claim),
    }


def _lead_id(claim: Claim) -> str:
    with get_sessionmaker()() as db:
        set_tenant_context(db, user_id=claim.actor_id, org_id=claim.org_id)
        lead_id = db.scalar(select(WorkflowRun.lead_id).where(WorkflowRun.id == claim.run_id))
        db.commit()
    return str(lead_id)


def _classify(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, LLMError):
        category = exc.category
    elif isinstance(exc, FetchFailedError):
        category = "fetch_failed"
    elif isinstance(exc, AppError):
        return exc.code[:40], exc.message
    else:
        category = "internal_error"
    return category, _DIAGNOSES.get(
        category, "This run failed unexpectedly. The logs have details."
    )


def checkpoint_serde() -> JsonPlusSerializer:
    """Strict reading of checkpoints. The default can construct arbitrary Python objects from a
    stored blob, so anyone able to write these tables could run code in the worker."""
    return JsonPlusSerializer(allowed_msgpack_modules=None)


def _fetch_problems(claim: Claim) -> list[str]:
    with get_sessionmaker()() as db:
        set_tenant_context(db, user_id=claim.actor_id, org_id=claim.org_id)
        details = db.scalars(
            select(WorkflowStep.detail)
            .where(WorkflowStep.run_id == claim.run_id, WorkflowStep.name == "gather_evidence")
            .order_by(WorkflowStep.started_at.desc())
            .limit(1)
        ).all()
        db.commit()
    return list(details[0].get("fetch_problems", [])) if details else []


def sweep_checkpoints() -> int:
    """Delete working state nothing will read again. Successful runs clean up after themselves,
    but cancelled runs, old failures, and runs of deleted organizations would otherwise stay."""
    with get_sessionmaker()() as db:
        threads = db.scalars(
            text("SELECT workflow_finished_threads(:days)"), {"days": FAILED_RETENTION_DAYS}
        ).all()
        db.commit()
    if not threads:
        return 0
    with psycopg.connect(
        checkpoint_conninfo(),
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=0,
        options=f"-c search_path={CHECKPOINT_SCHEMA}",
    ) as conn:
        saver = PostgresSaver(conn, serde=checkpoint_serde())
        for thread in threads:
            saver.delete_thread(thread)
    return len(threads)


def execute(claim: Claim, owner: str, lease_s: int) -> None:
    heartbeat = _Heartbeat(claim, owner, lease_s)
    heartbeat.start()
    try:
        _mark_interrupted_steps(claim)
        with psycopg.connect(
            checkpoint_conninfo(),
            autocommit=True,
            row_factory=dict_row,
            prepare_threshold=0,
            options=f"-c search_path={CHECKPOINT_SCHEMA}",
        ) as conn:
            saver = PostgresSaver(conn, serde=checkpoint_serde())
            graph = compile_graph(claim.kind, owner, saver)
            config: Any = {
                "configurable": {"thread_id": str(claim.run_id)},
                "recursion_limit": RECURSION_LIMIT,
            }
            _drive(graph, config, claim, owner, saver)
    finally:
        heartbeat.stop()


def _drive(graph: Any, config: Any, claim: Claim, owner: str, saver: PostgresSaver) -> None:
    snapshot = graph.get_state(config)
    decision = _pending_decision(claim)
    payload: Any
    if decision and snapshot.interrupts:
        payload = Command(resume=decision)
    elif snapshot.next:
        payload = None  # Pick up after the last completed step.
    elif snapshot.values:
        # The graph finished but the worker died before recording it. Starting it again would
        # repeat every step and could throw away a person's decision.
        _record_outcome(graph, config, claim, owner, saver)
        return
    else:
        payload = _initial_state(claim)
    try:
        graph.invoke(payload, config)
    except LeaseLostError:
        return  # Another worker owns this run now.
    except WorkflowStoppedError as stop:
        if stop.reason == "lease_lost":
            return  # Another worker owns this run now.
        if stop.reason == "cancelled":
            _finish(
                claim,
                owner,
                status=WorkflowStatus.cancelled,
                current_step=None,
                finished_at=datetime.now(UTC),
            )
        else:
            _finish(
                claim,
                owner,
                status=WorkflowStatus.failed,
                error_category=stop.reason,
                error_message=_DIAGNOSES.get(stop.reason),
                finished_at=datetime.now(UTC),
            )
        return
    except Exception as exc:
        category, message = _classify(exc)
        log.warning(
            "workflow_failed",
            extra={
                "run_id": str(claim.run_id),
                "category": category,
                "error_type": type(exc).__name__,
            },
        )
        _finish(
            claim,
            owner,
            status=WorkflowStatus.failed,
            error_category=category,
            error_message=message,
            finished_at=datetime.now(UTC),
        )
        return
    _record_outcome(graph, config, claim, owner, saver)


def _record_outcome(
    graph: Any, config: Any, claim: Claim, owner: str, saver: PostgresSaver
) -> None:
    final = graph.get_state(config)
    if final.interrupts:
        _finish(
            claim,
            owner,
            status=WorkflowStatus.waiting_approval,
            approval_request=final.interrupts[0].value,
            # A decision applies to the request a person saw, never to a later one.
            approval_decision=None,
        )
        return
    state: WorkflowState = final.values
    finished = _finish(
        claim,
        owner,
        status=WorkflowStatus.succeeded,
        current_step=None,
        finished_at=datetime.now(UTC),
        error_category=None,
        error_message=None,
        result={
            "decision": state.get("decision"),
            "escalation_reasons": state.get("escalation_reasons", []),
            "assessment_id": state.get("assessment_id"),
            "score": state.get("score"),
            "fit": state.get("fit"),
            "brief_id": state.get("brief_id"),
            "brief_status": state.get("brief_status"),
            "fetch_problems": _fetch_problems(claim),
            "approval": state.get("approval"),
            "proposal_applied": state.get("proposal_applied"),
            "usage": state.get("usage"),
        },
    )
    if finished:
        # Checkpoints are working state. The records above are what lasts.
        saver.delete_thread(str(claim.run_id))


def run_next_import(owner: str) -> bool:
    """Process one queued CSV import, in one transaction. A crash rolls it all back, and the
    lease lets another worker take it over."""
    with get_sessionmaker()() as db:
        row = db.execute(
            text("SELECT * FROM import_claim(:owner, :lease)"),
            {"owner": owner, "lease": IMPORT_LEASE_S},
        ).first()
        db.commit()
        if row is None:
            return False
        import_id, org_id, user_id = row.id, row.organization_id, row.created_by_user_id
        try:
            ctx = worker_context(db, org_id, user_id)
            if not has_permission(ctx.role, Permission.leads_import):
                raise RequestInvalidError("The person who started this can no longer import leads")
            record = db.get(LeadImport, import_id)
            if record is None or record.lease_owner != owner:
                db.rollback()
                return True
            csv_service.process_queued(db, ctx, record)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.warning(
                "import_failed",
                extra={"import_id": str(import_id), "error_type": type(exc).__name__},
            )
            message = (
                exc.message if isinstance(exc, AppError) else "This import failed unexpectedly."
            )
            set_tenant_context(db, user_id=user_id, org_id=org_id)
            db.execute(
                update(LeadImport)
                .where(LeadImport.id == import_id, LeadImport.lease_owner == owner)
                .values(
                    status=ImportStatus.failed,
                    error_message=message[:500],
                    payload=None,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            audit.record(
                db,
                "leads.import_failed",
                org_id=org_id,
                actor_id=user_id,
                target_type="lead_import",
                target_id=import_id,
                data={"error": type(exc).__name__},
            )
            db.commit()
    return True


def run_once(owner: str, lease_s: int | None = None, *, imports_first: bool = False) -> bool:
    """Do one unit of queued work. Returns False when nothing is waiting. Workers alternate
    `imports_first`, so steady workflow traffic cannot starve imports."""
    if imports_first and run_next_import(owner):
        return True
    lease = lease_s or get_settings().worker_lease_seconds
    claim = claim_next(owner, lease)
    if claim is not None:
        execute(claim, owner, lease)
        return True
    return run_next_import(owner)


def drain(owner: str = "inline") -> int:
    """Run everything waiting, one at a time. For tests and one-off use."""
    count = 0
    while run_once(owner):
        count += 1
    return count
