"""Pipeline stages, opportunities, and stored-record analytics."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import ConflictError, NotFoundError
from app.models import (
    DEFAULT_STAGES,
    Activity,
    ActivityType,
    Lead,
    LeadStatus,
    Opportunity,
    PipelineStage,
    StageKind,
)
from app.schemas.crm import (
    ActivityOut,
    OpportunityCreate,
    OpportunityUpdate,
    OverviewOut,
    StageSummary,
)
from app.services.lead_service import (
    InvalidReferenceError,
    company_ref,
    ensure_member,
    get_lead,
    record_activity,
)

MAX_BOARD_ITEMS = 500


def _now() -> datetime:
    return datetime.now(UTC)


# --- stages -----------------------------------------------------------------------------


def seed_default_stages(db: Session, org_id: uuid.UUID) -> None:
    for position, (name, kind) in enumerate(DEFAULT_STAGES):
        db.add(PipelineStage(organization_id=org_id, name=name, position=position, kind=kind))


def list_stages(db: Session, ctx: OrgContext) -> list[PipelineStage]:
    return list(
        db.scalars(
            select(PipelineStage)
            .where(PipelineStage.organization_id == ctx.org_id)
            .order_by(PipelineStage.position, PipelineStage.name)
        )
    )


def get_stage(db: Session, ctx: OrgContext, stage_id: uuid.UUID) -> PipelineStage:
    stage = db.scalar(
        select(PipelineStage).where(
            PipelineStage.id == stage_id, PipelineStage.organization_id == ctx.org_id
        )
    )
    if stage is None:
        raise NotFoundError("Stage not found")
    return stage


def _stage_ref(db: Session, ctx: OrgContext, stage_id: uuid.UUID) -> PipelineStage:
    try:
        return get_stage(db, ctx, stage_id)
    except NotFoundError as exc:
        raise InvalidReferenceError("Stage does not exist in this organization") from exc


def create_stage(db: Session, ctx: OrgContext, name: str, kind: StageKind) -> PipelineStage:
    last = db.scalar(
        select(func.max(PipelineStage.position)).where(PipelineStage.organization_id == ctx.org_id)
    )
    stage = PipelineStage(
        organization_id=ctx.org_id, name=name.strip(), kind=kind, position=(last or 0) + 1
    )
    db.add(stage)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A stage with this name already exists") from exc
    return stage


def rename_stage(db: Session, ctx: OrgContext, stage_id: uuid.UUID, name: str) -> PipelineStage:
    stage = get_stage(db, ctx, stage_id)
    stage.name = name.strip()
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("A stage with this name already exists") from exc
    return stage


# --- opportunities ----------------------------------------------------------------------


def get_opportunity(db: Session, ctx: OrgContext, opp_id: uuid.UUID) -> Opportunity:
    opp = db.scalar(
        select(Opportunity).where(
            Opportunity.id == opp_id, Opportunity.organization_id == ctx.org_id
        )
    )
    if opp is None:
        raise NotFoundError("Opportunity not found")
    return opp


def list_opportunities(
    db: Session,
    ctx: OrgContext,
    *,
    stage_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    include_closed: bool,
) -> list[Opportunity]:
    stmt = (
        select(Opportunity)
        .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
        .where(Opportunity.organization_id == ctx.org_id)
    )
    if stage_id:
        stmt = stmt.where(Opportunity.stage_id == stage_id)
    if owner_id:
        stmt = stmt.where(Opportunity.owner_user_id == owner_id)
    if not include_closed:
        stmt = stmt.where(PipelineStage.kind == StageKind.open)
    return list(db.scalars(stmt.order_by(Opportunity.updated_at.desc()).limit(MAX_BOARD_ITEMS)))


def _apply_stage(opp: Opportunity, stage: PipelineStage) -> None:
    opp.stage_id = stage.id
    opp.closed_at = _now() if stage.kind != StageKind.open else None


def create_opportunity(db: Session, ctx: OrgContext, body: OpportunityCreate) -> Opportunity:
    stage = _stage_ref(db, ctx, body.stage_id)
    company_id = company_ref(db, ctx, body.company_id).id if body.company_id else None
    if body.lead_id:
        try:
            lead = get_lead(db, ctx, body.lead_id)
        except NotFoundError as exc:
            raise InvalidReferenceError("Lead does not exist in this organization") from exc
        company_id = company_id or lead.company_id
    ensure_member(db, ctx, body.owner_user_id)
    opp = Opportunity(
        organization_id=ctx.org_id,
        name=body.name.strip(),
        lead_id=body.lead_id,
        company_id=company_id,
        owner_user_id=body.owner_user_id or ctx.user_id,
        amount=body.amount,
        currency=body.currency,
        expected_close_date=body.expected_close_date,
        stage_id=stage.id,
    )
    _apply_stage(opp, stage)
    db.add(opp)
    db.flush()
    record_activity(
        db,
        ctx,
        ActivityType.opportunity_created,
        lead_id=body.lead_id,
        opportunity_id=opp.id,
        data={"name": opp.name, "stage": stage.name},
    )
    return opp


def update_opportunity(
    db: Session, ctx: OrgContext, opp_id: uuid.UUID, body: OpportunityUpdate
) -> Opportunity:
    opp = get_opportunity(db, ctx, opp_id)
    sent = body.model_fields_set
    if "stage_id" in sent and body.stage_id and body.stage_id != opp.stage_id:
        old = get_stage(db, ctx, opp.stage_id)
        new = _stage_ref(db, ctx, body.stage_id)
        _apply_stage(opp, new)
        record_activity(
            db,
            ctx,
            ActivityType.stage_changed,
            lead_id=opp.lead_id,
            opportunity_id=opp.id,
            data={"from": old.name, "to": new.name, "kind": new.kind.value},
        )
    if "owner_user_id" in sent:
        ensure_member(db, ctx, body.owner_user_id)
        opp.owner_user_id = body.owner_user_id
    for name in ("name", "amount", "currency", "expected_close_date"):
        if name in sent:
            value = getattr(body, name)
            if name in ("name", "currency") and value is None:
                continue  # required columns; null means "unchanged"
            setattr(opp, name, value)
    db.flush()
    return opp


# --- aggregates -------------------------------------------------------------------------


def _totals(rows: list[tuple[str, Decimal | None]]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(Decimal)
    for currency, amount in rows:
        if amount is not None:
            out[currency] += amount
    return dict(out)


def pipeline_summary(db: Session, ctx: OrgContext) -> list[StageSummary]:
    rows = db.execute(
        select(
            Opportunity.stage_id, Opportunity.currency, func.count(), func.sum(Opportunity.amount)
        )
        .where(Opportunity.organization_id == ctx.org_id)
        .group_by(Opportunity.stage_id, Opportunity.currency)
    ).all()
    counts: dict[uuid.UUID, int] = defaultdict(int)
    sums: dict[uuid.UUID, list[tuple[str, Decimal | None]]] = defaultdict(list)
    for stage_id, currency, count, total in rows:
        counts[stage_id] += count
        sums[stage_id].append((currency, total))
    return [
        StageSummary(
            stage_id=s.id, name=s.name, kind=s.kind, count=counts[s.id], totals=_totals(sums[s.id])
        )
        for s in list_stages(db, ctx)
    ]


def overview(db: Session, ctx: OrgContext) -> OverviewOut:
    now = _now()
    live = (Lead.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
    by_status = dict(
        db.execute(select(Lead.status, func.count()).where(*live).group_by(Lead.status)).all()
    )
    leads_total = sum(by_status.values())
    added = (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(*live, Lead.created_at >= now - timedelta(days=30))
        )
        or 0
    )

    def opp_rows(
        kind: StageKind, since: datetime | None = None
    ) -> list[tuple[str, Decimal | None]]:
        stmt = (
            select(Opportunity.currency, Opportunity.amount)
            .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
            .where(Opportunity.organization_id == ctx.org_id, PipelineStage.kind == kind)
        )
        if since:
            stmt = stmt.where(Opportunity.closed_at >= since)
        return [(c, a) for c, a in db.execute(stmt).all()]

    open_rows = opp_rows(StageKind.open)
    won_rows = opp_rows(StageKind.won, now - timedelta(days=90))
    recent = list(
        db.scalars(
            select(Activity)
            .where(Activity.organization_id == ctx.org_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(10)
        )
    )
    return OverviewOut(
        leads_total=leads_total,
        leads_added_30d=added,
        leads_by_status={s.value: by_status.get(s, 0) for s in LeadStatus},
        open_opportunities=len(open_rows),
        open_pipeline_value=_totals(open_rows),
        won_value_90d=_totals(won_rows),
        won_count_90d=len(won_rows),
        recent_activity=[ActivityOut.model_validate(a) for a in recent],
    )
