"""Outreach drafts, approvals, suppression, settings, and the public opt-out route."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import DbDep, OrgContext, require
from app.core.errors import AppError
from app.core.permissions import Permission
from app.core.rate_limit import get_rate_limiter
from app.core.security import read_unsubscribe_token
from app.integrations.dispatch import unavailable_reason
from app.models import ApprovalStatus, DraftStatus, OutreachDraft
from app.schemas.outreach import (
    ApprovalDecision,
    ApprovalListItem,
    ApprovalOut,
    ApprovalRejection,
    Blocker,
    DeliveryOut,
    DeliveryResolution,
    DraftCreate,
    DraftDetail,
    DraftOut,
    DraftSource,
    DraftUpdate,
    OutreachSettingsUpdate,
    OutreachSettingsView,
    SuppressionCreate,
    SuppressionOut,
    UnsubscribeResult,
)
from app.services import dispatch_service, outreach_service, suppression_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["outreach"])
public_router = APIRouter(tags=["outreach"])

Read = Annotated[OrgContext, Depends(require(Permission.outreach_read))]
Write = Annotated[OrgContext, Depends(require(Permission.outreach_write))]
Send = Annotated[OrgContext, Depends(require(Permission.outreach_send))]
Approve = Annotated[OrgContext, Depends(require(Permission.outreach_approve))]
Configure = Annotated[OrgContext, Depends(require(Permission.outreach_configure))]

SENDS_PER_MINUTE = 30
OPT_OUTS_PER_MINUTE = 30


def _blockers(codes: list[str]) -> list[Blocker]:
    return [Blocker(code=c, message=dispatch_service.BLOCKER_MESSAGES[c]) for c in codes]


def _detail(db: DbDep, draft: OutreachDraft) -> DraftDetail:
    approval = outreach_service.latest_approval(db, draft)
    return DraftDetail(
        **DraftOut.model_validate(draft).model_dump(),
        sources=[
            DraftSource(
                id=e.id,
                source_type=e.source_type.value,
                source_url=e.source_url,
                content=e.content[:2000],
            )
            for e in outreach_service.sources_for(db, draft)
        ],
        approval=ApprovalOut.model_validate(approval) if approval else None,
        deliveries=[
            DeliveryOut.model_validate(d) for d in outreach_service.deliveries_for(db, draft)
        ],
        blockers=_blockers(dispatch_service.preflight(db, draft)),
    )


@router.get("/outreach/drafts", response_model=list[DraftOut])
def list_drafts(
    ctx: Read, db: DbDep, status: DraftStatus | None = None, lead_id: uuid.UUID | None = None
) -> list[DraftOut]:
    rows = outreach_service.list_drafts(db, ctx, status=status, lead_id=lead_id)
    out = [DraftOut.model_validate(d) for d in rows]
    db.commit()
    return out


@router.post("/outreach/drafts", status_code=201, response_model=DraftDetail)
def create_draft(body: DraftCreate, ctx: Write, db: DbDep) -> DraftDetail:
    draft = outreach_service.create_draft(db, ctx, body.lead_id, body.subject, body.body)
    out = _detail(db, draft)
    db.commit()
    return out


@router.get("/outreach/drafts/{draft_id}", response_model=DraftDetail)
def get_draft(draft_id: uuid.UUID, ctx: Read, db: DbDep) -> DraftDetail:
    out = _detail(db, outreach_service.get_draft(db, ctx, draft_id))
    db.commit()
    return out


@router.patch("/outreach/drafts/{draft_id}", response_model=DraftDetail)
def update_draft(draft_id: uuid.UUID, body: DraftUpdate, ctx: Write, db: DbDep) -> DraftDetail:
    draft = outreach_service.update_draft(
        db,
        ctx,
        draft_id,
        expected_version=body.expected_version,
        subject=body.subject,
        body=body.body,
    )
    out = _detail(db, draft)
    db.commit()
    return out


@router.post("/outreach/drafts/{draft_id}/discard", response_model=DraftDetail)
def discard_draft(draft_id: uuid.UUID, ctx: Write, db: DbDep) -> DraftDetail:
    out = _detail(db, outreach_service.discard_draft(db, ctx, draft_id))
    db.commit()
    return out


@router.post("/outreach/drafts/{draft_id}/request-approval", response_model=DraftDetail)
def request_approval(draft_id: uuid.UUID, ctx: Write, db: DbDep) -> DraftDetail:
    outreach_service.request_approval(db, ctx, draft_id)
    out = _detail(db, outreach_service.get_draft(db, ctx, draft_id))
    db.commit()
    return out


@router.post("/outreach/drafts/{draft_id}/send", response_model=DeliveryOut)
def send_draft(draft_id: uuid.UUID, ctx: Send, db: DbDep) -> DeliveryOut:
    get_rate_limiter().hit(f"outreach-send:{ctx.org_id}", SENDS_PER_MINUTE)
    delivery = dispatch_service.send(db, ctx, draft_id)
    out = DeliveryOut.model_validate(delivery)
    db.commit()
    return out


@router.post("/outreach/deliveries/{delivery_id}/resolve", response_model=DeliveryOut)
def resolve_delivery(
    delivery_id: uuid.UUID, body: DeliveryResolution, ctx: Approve, db: DbDep
) -> DeliveryOut:
    delivery = dispatch_service.resolve_unknown(db, ctx, delivery_id, sent=body.sent)
    out = DeliveryOut.model_validate(delivery)
    db.commit()
    return out


@router.get("/approvals", response_model=list[ApprovalListItem])
def list_approvals(
    ctx: Read, db: DbDep, status: ApprovalStatus | None = None
) -> list[ApprovalListItem]:
    rows = outreach_service.list_approvals(db, ctx, status=status)
    out = [
        ApprovalListItem(
            **ApprovalOut.model_validate(a).model_dump(),
            subject=d.subject,
            origin=d.origin,
            flags=d.flags,
        )
        for a, d in rows
    ]
    db.commit()
    return out


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalOut)
def approve(approval_id: uuid.UUID, body: ApprovalDecision, ctx: Approve, db: DbDep) -> ApprovalOut:
    approval = outreach_service.approve(db, ctx, approval_id, body.content_hash)
    out = ApprovalOut.model_validate(approval)
    db.commit()
    return out


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalOut)
def reject(approval_id: uuid.UUID, body: ApprovalRejection, ctx: Approve, db: DbDep) -> ApprovalOut:
    approval = outreach_service.reject(db, ctx, approval_id, body.note)
    out = ApprovalOut.model_validate(approval)
    db.commit()
    return out


@router.get("/outreach/suppressions", response_model=list[SuppressionOut])
def list_suppressions(ctx: Read, db: DbDep) -> list[SuppressionOut]:
    return [
        SuppressionOut.model_validate(e) for e in suppression_service.list_suppressions(db, ctx)
    ]


@router.post("/outreach/suppressions", status_code=201, response_model=SuppressionOut)
def add_suppression(body: SuppressionCreate, ctx: Write, db: DbDep) -> SuppressionOut:
    entry = suppression_service.add_suppression(db, ctx, body.kind, body.value, body.note)
    out = SuppressionOut.model_validate(entry)
    db.commit()
    return out


@router.delete("/outreach/suppressions/{entry_id}", status_code=204)
def remove_suppression(entry_id: uuid.UUID, ctx: Approve, db: DbDep) -> Response:
    suppression_service.remove_suppression(db, ctx, entry_id)
    db.commit()
    return Response(status_code=204)


def _settings_view(row: object) -> OutreachSettingsView:
    reason = unavailable_reason()
    data = {
        name: getattr(row, name)
        for name in OutreachSettingsView.model_fields
        if name != "server_blocker"
    }
    return OutreachSettingsView(
        **data,
        server_blocker=_blockers([reason])[0] if reason else None,
    )


@router.get("/outreach/settings", response_model=OutreachSettingsView)
def get_settings(ctx: Read, db: DbDep) -> OutreachSettingsView:
    out = _settings_view(suppression_service.get_settings_row(db, ctx.org_id))
    db.commit()
    return out


@router.put("/outreach/settings", response_model=OutreachSettingsView)
def put_settings(body: OutreachSettingsUpdate, ctx: Configure, db: DbDep) -> OutreachSettingsView:
    if body.sends_enabled and not (body.sender_name and body.sender_email and body.postal_address):
        raise AppError(
            "Sending needs a sender name, sender email, and postal address", code="sender_missing"
        )
    out = _settings_view(suppression_service.update_settings(db, ctx, body.model_dump()))
    db.commit()
    return out


@public_router.post("/unsubscribe/{token}", response_model=UnsubscribeResult)
def unsubscribe(
    token: str,
    request: Request,
    db: DbDep,
) -> UnsubscribeResult:
    """Public on purpose: a mail provider's one-click request carries no session or JSON."""
    # Counted separately, so that a flood of bad links cannot use up a real person's opt-out.
    if read_unsubscribe_token(token) is None:
        ip = request.client.host if request.client else "unknown"
        get_rate_limiter().hit(f"unsubscribe-invalid:{ip}", OPT_OUTS_PER_MINUTE)
        return UnsubscribeResult(unsubscribed=False)
    get_rate_limiter().hit(f"unsubscribe:{token[:64]}", OPT_OUTS_PER_MINUTE)
    done = dispatch_service.opt_out(db, token)
    db.commit()
    return UnsubscribeResult(unsubscribed=done)
