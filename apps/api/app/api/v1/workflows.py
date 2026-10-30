"""Workflow runs: start, inspect the trace, cancel, resume, and decide (all org-scoped)."""

import logging
import uuid
from functools import lru_cache
from typing import Annotated

import redis
from fastapi import APIRouter, Depends

from app.core.auth import DbDep, OrgContext, PrincipalDep, require
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.rate_limit import get_rate_limiter
from app.models import WorkflowRun
from app.schemas.workflow import (
    WorkerHealthOut,
    WorkflowDecision,
    WorkflowRunDetail,
    WorkflowRunOut,
    WorkflowStart,
    WorkflowStepOut,
)
from app.services import workflow_service
from app.workflows.state import HEARTBEAT_KEY

log = logging.getLogger(__name__)

router = APIRouter(tags=["workflows"])
org = "/organizations/{org_id}"

Read = Annotated[OrgContext, Depends(require(Permission.workflows_read))]
Run = Annotated[OrgContext, Depends(require(Permission.workflows_run))]
Review = Annotated[OrgContext, Depends(require(Permission.intelligence_review))]

STARTS_PER_MINUTE = 10


@lru_cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
    )


def _detail(db: DbDep, ctx: OrgContext, run: WorkflowRun) -> WorkflowRunDetail:
    base = WorkflowRunOut.model_validate(run).model_dump(exclude={"resumable"})
    steps = workflow_service.list_steps(db, ctx, run.id)
    return WorkflowRunDetail(**base, steps=[WorkflowStepOut.model_validate(s) for s in steps])


@router.post(f"{org}/leads/{{lead_id}}/workflows", status_code=202, response_model=WorkflowRunOut)
def start_workflow(lead_id: uuid.UUID, body: WorkflowStart, ctx: Run, db: DbDep) -> WorkflowRunOut:
    get_rate_limiter().hit(f"workflow:{ctx.org_id}", STARTS_PER_MINUTE)
    out = WorkflowRunOut.model_validate(workflow_service.start(db, ctx, lead_id, body))
    db.commit()
    return out


@router.get(f"{org}/workflows", response_model=list[WorkflowRunOut])
def list_workflows(ctx: Read, db: DbDep, lead_id: uuid.UUID | None = None) -> list[WorkflowRunOut]:
    return [
        WorkflowRunOut.model_validate(r)
        for r in workflow_service.list_runs(db, ctx, lead_id=lead_id)
    ]


@router.get(f"{org}/workflows/{{run_id}}", response_model=WorkflowRunDetail)
def get_workflow(run_id: uuid.UUID, ctx: Read, db: DbDep) -> WorkflowRunDetail:
    return _detail(db, ctx, workflow_service.get_run(db, ctx, run_id))


@router.post(f"{org}/workflows/{{run_id}}/cancel", response_model=WorkflowRunOut)
def cancel_workflow(run_id: uuid.UUID, ctx: Run, db: DbDep) -> WorkflowRunOut:
    out = WorkflowRunOut.model_validate(workflow_service.cancel(db, ctx, run_id))
    db.commit()
    return out


@router.post(f"{org}/workflows/{{run_id}}/resume", response_model=WorkflowRunOut)
def resume_workflow(run_id: uuid.UUID, ctx: Run, db: DbDep) -> WorkflowRunOut:
    get_rate_limiter().hit(f"workflow:{ctx.org_id}", STARTS_PER_MINUTE)
    out = WorkflowRunOut.model_validate(workflow_service.resume(db, ctx, run_id))
    db.commit()
    return out


@router.post(f"{org}/workflows/{{run_id}}/decision", response_model=WorkflowRunOut)
def decide_workflow(
    run_id: uuid.UUID, body: WorkflowDecision, ctx: Review, db: DbDep
) -> WorkflowRunOut:
    out = WorkflowRunOut.model_validate(workflow_service.decide(db, ctx, run_id, body.decision))
    db.commit()
    return out


@router.get("/workers/health", response_model=WorkerHealthOut)
def worker_health(_: PrincipalDep) -> WorkerHealthOut:
    """Whether any worker reported in recently. It says nothing about any tenant's data."""
    try:
        return WorkerHealthOut(alive=bool(_redis().exists(HEARTBEAT_KEY)))
    except redis.RedisError as exc:
        log.warning("worker_health_unavailable", extra={"error_type": type(exc).__name__})
        return WorkerHealthOut(alive=False)
