"""Plans, usage, and the limits behind them. Every limit is enforced here, on the server.

A check takes a lock per organization and metric, so that two requests cannot both use the last
unit. Tokens are different: nobody knows what a run will use until it has run, so a new run is
refused once the month's budget is gone, and one run can overshoot it by its own hard limit.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    Delivery,
    DeliveryStatus,
    Invitation,
    Lead,
    Membership,
    Subscription,
    UsageKind,
    UsageRecord,
)

PLANS_FILE = Path(__file__).resolve().parents[1] / "core" / "plans.yaml"

METRIC_LABELS = {
    "seats": "Seats",
    "leads": "Leads",
    "monthly_workflow_runs": "Workflow runs this month",
    "monthly_model_tokens": "Model tokens this month",
    "monthly_emails": "Emails this month",
}
_USAGE_KINDS = {
    "monthly_workflow_runs": UsageKind.workflow_run,
    "monthly_model_tokens": UsageKind.model_tokens,
}
# Anything that may have reached someone, including what is on its way right now.
_EMAILS_COUNTED = (DeliveryStatus.sending, DeliveryStatus.accepted, DeliveryStatus.unknown)


class QuotaExceededError(AppError):
    status_code = 402
    code = "quota_exceeded"


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    integrations: bool
    limits: dict[str, int | None]


@lru_cache
def all_plans() -> dict[str, Plan]:
    raw = yaml.safe_load(PLANS_FILE.read_text(encoding="utf-8"))["plans"]
    return {
        key: Plan(key, value["label"], bool(value["integrations"]), dict(value["limits"]))
        for key, value in raw.items()
    }


def plan_for(db: Session, org_id: uuid.UUID) -> Plan:
    key = db.scalar(select(Subscription.plan_key).where(Subscription.organization_id == org_id))
    plans = all_plans()
    # A plan removed from the file falls back, rather than locking the organization out.
    return plans.get(key or get_settings().default_plan) or plans[get_settings().default_plan]


def _month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def used(db: Session, org_id: uuid.UUID, metric: str) -> int:
    if metric == "seats":
        members = db.scalar(
            select(func.count()).select_from(Membership).where(Membership.organization_id == org_id)
        )
        pending = db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.organization_id == org_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
        )
        return (members or 0) + (pending or 0)
    if metric == "leads":
        return (
            db.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.organization_id == org_id, Lead.deleted_at.is_(None))
            )
            or 0
        )
    if metric == "monthly_emails":
        return (
            db.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(
                    Delivery.organization_id == org_id,
                    Delivery.status.in_(_EMAILS_COUNTED),
                    Delivery.created_at >= _month_start(),
                )
            )
            or 0
        )
    total = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.organization_id == org_id,
            UsageRecord.kind == _USAGE_KINDS[metric],
            UsageRecord.created_at >= _month_start(),
        )
    )
    return int(total or 0)


def _lock(db: Session, org_id: uuid.UUID, metric: str) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"quota:{org_id}:{metric}"},
    )


def _refuse(plan: Plan, metric: str, limit: int, now_used: int) -> QuotaExceededError:
    return QuotaExceededError(
        f"Your {plan.label} plan allows {limit:,} for {METRIC_LABELS[metric].lower()}.",
        details={"metric": metric, "limit": limit, "used": now_used, "plan": plan.key},
    )


def check(db: Session, org_id: uuid.UUID, metric: str, amount: int = 1) -> None:
    """Refuse if `amount` more would pass the limit. Holds until this transaction ends."""
    plan = plan_for(db, org_id)
    limit = plan.limits.get(metric)
    if limit is None:
        return
    _lock(db, org_id, metric)
    now_used = used(db, org_id, metric)
    if now_used + amount > limit:
        raise _refuse(plan, metric, limit, now_used)


def check_budget(db: Session, org_id: uuid.UUID) -> None:
    """Before anything that will call a model."""
    plan = plan_for(db, org_id)
    limit = plan.limits.get("monthly_model_tokens")
    if limit is None:
        return
    now_used = used(db, org_id, "monthly_model_tokens")
    if now_used >= limit:
        raise _refuse(plan, "monthly_model_tokens", limit, now_used)


def remaining(db: Session, org_id: uuid.UUID, metric: str) -> int | None:
    limit = plan_for(db, org_id).limits.get(metric)
    return None if limit is None else max(0, limit - used(db, org_id, metric))


def record(
    db: Session,
    org_id: uuid.UUID,
    kind: UsageKind,
    quantity: int,
    *,
    model_key: str | None = None,
    estimated_cost_usd: float | None = None,
    workflow_run_id: uuid.UUID | None = None,
) -> None:
    if quantity <= 0:
        return
    db.add(
        UsageRecord(
            organization_id=org_id,
            kind=kind,
            quantity=quantity,
            model_key=model_key,
            estimated_cost_usd=estimated_cost_usd,
            workflow_run_id=workflow_run_id,
        )
    )


def usage_view(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    plan = plan_for(db, org_id)
    cost = db.scalar(
        select(func.sum(UsageRecord.estimated_cost_usd)).where(
            UsageRecord.organization_id == org_id, UsageRecord.created_at >= _month_start()
        )
    )
    source = db.scalar(select(Subscription.source).where(Subscription.organization_id == org_id))
    return {
        "plan": plan,
        "source": source or "default",
        "metrics": [
            {
                "metric": metric,
                "label": label,
                "used": used(db, org_id, metric),
                "limit": plan.limits.get(metric),
            }
            for metric, label in METRIC_LABELS.items()
        ],
        "estimated_cost_usd": float(cost) if cost is not None else None,
    }
