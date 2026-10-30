"""Typed workflow state. It is checkpointed outside row-level security, so it carries only IDs,
statuses, and counts: lead data and evidence text stay in the tenant's tables.
"""

from typing import Any, Literal, TypedDict

# Bumped when the shape changes, so a run resumed after a deploy can be recognized.
STATE_VERSION = 1
HEARTBEAT_KEY = "worker:heartbeat"

Decision = Literal["accepted", "escalated"]


class Usage(TypedDict, total=False):
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    model: str | None


class WorkflowState(TypedDict, total=False):
    state_version: int
    run_id: str
    org_id: str
    actor_id: str
    lead_id: str | None
    icp_version: int | None
    evidence_ids: list[str]
    quarantined_count: int
    fetch_problem_count: int
    assessment_id: str | None
    score: int | None
    fit: str | None
    evaluation_status: str | None
    brief_id: str | None
    brief_status: str | None
    brief_failure: str | None
    decision: Decision
    escalation_reasons: list[str]
    proposal: dict[str, Any] | None
    approval: str | None
    proposal_applied: bool
    agent_id: str | None
    agent_status: str | None
    agent_failure: str | None
    agent_notes: int
    usage: Usage
