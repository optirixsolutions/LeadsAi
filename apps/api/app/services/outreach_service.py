"""Drafts, approvals, suppression, and settings. Sending itself is in `dispatch_service`.

An approval is its own record instead of a paused workflow, because a person may take days and a
paused run would hold its lead and one of the organization's run slots for all of that time.
"""

import contextlib
import hashlib
import json
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.gates import _has_hidden_characters, review_unsourced
from app.core.auth import OrgContext
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    Delivery,
    DeliveryStatus,
    DraftOrigin,
    DraftStatus,
    Lead,
    OutreachDraft,
    ResearchEvidence,
)
from app.services import audit
from app.services.lead_service import get_lead
from app.services.suppression_service import find_suppression

APPROVAL_TTL = timedelta(days=7)
# A send takes seconds. One still marked as sending after this died partway through.
STALE_SENDING = timedelta(minutes=5)
_LIVE = (ApprovalStatus.pending, ApprovalStatus.approved)
_EDITABLE = (DraftStatus.draft, DraftStatus.pending_approval, DraftStatus.approved)


def _now() -> datetime:
    return datetime.now(UTC)


def content_hash(recipient: str, subject: str, body: str) -> str:
    """Fixes exactly what was approved: this text, to this address."""
    return hashlib.sha256(json.dumps([recipient, subject, body]).encode()).hexdigest()


def _record(db: Session, ctx: OrgContext, action: str, target: Any, **data: Any) -> None:
    audit.record(
        db,
        f"outreach.{action}",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type=type(target).__tablename__,
        target_id=target.id,
        data=data,
    )


def check_text(subject: str, body: str) -> None:
    """Hidden characters could show a reviewer one thing and send a reader another."""
    if _has_hidden_characters(subject) or _has_hidden_characters(body):
        raise AppError("The text contains hidden characters", code="hidden_characters")
    if any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in subject):
        raise AppError("A subject has to be one plain line", code="invalid_subject")


# --- drafts --------------------------------------------------------------------------------


def _recipient_for(db: Session, ctx: OrgContext, lead: Lead) -> str:
    if not lead.email:
        raise AppError("This lead has no email address", code="lead_has_no_email")
    if find_suppression(db, ctx.org_id, lead.email):
        raise ConflictError("This address must not be contacted", code="suppressed")
    return lead.email


def require_contactable(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> None:
    _recipient_for(db, ctx, get_lead(db, ctx, lead_id))


def create_draft(
    db: Session,
    ctx: OrgContext,
    lead_id: uuid.UUID,
    subject: str,
    body: str,
    *,
    origin: DraftOrigin = DraftOrigin.person,
) -> OutreachDraft:
    check_text(subject, body)
    recipient = _recipient_for(db, ctx, get_lead(db, ctx, lead_id))
    review = review_unsourced(subject, body) if origin != DraftOrigin.person else None
    draft = OutreachDraft(
        organization_id=ctx.org_id,
        lead_id=lead_id,
        status=DraftStatus.draft,
        origin=origin,
        recipient=recipient,
        subject=subject,
        body=body,
        content_hash=content_hash(recipient, subject, body),
        flags=review.flags if review else [],
        needs_edit=review.needs_edit if review else False,
        flagged_contacts=review.flagged_contacts if review else [],
        created_by_user_id=ctx.user_id,
        updated_by_user_id=ctx.user_id,
    )
    db.add(draft)
    db.flush()
    _record(db, ctx, "draft_created", draft, origin=draft.origin.value)
    return draft


def create_agent_draft(
    db: Session,
    ctx: OrgContext,
    lead: Lead,
    run_id: uuid.UUID,
    subject: str,
    body: str,
    *,
    flags: list[str],
    needs_edit: bool,
    flagged_contacts: list[str],
    evidence_ids: list[str],
) -> OutreachDraft:
    """Only ever a draft. Nothing a model writes can move it further than this."""
    assert lead.email is not None
    draft = OutreachDraft(
        organization_id=ctx.org_id,
        lead_id=lead.id,
        status=DraftStatus.draft,
        origin=DraftOrigin.agent,
        recipient=lead.email,
        subject=subject,
        body=body,
        content_hash=content_hash(lead.email, subject, body),
        flags=flags,
        needs_edit=needs_edit,
        flagged_contacts=flagged_contacts,
        evidence_ids=evidence_ids,
        workflow_run_id=run_id,
        created_by_user_id=ctx.user_id,
    )
    db.add(draft)
    db.flush()
    _record(db, ctx, "draft_created", draft, origin=draft.origin.value, flags=flags)
    return draft


def _live_approval(db: Session, draft: OutreachDraft) -> ApprovalRequest | None:
    return db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.draft_id == draft.id, ApprovalRequest.status.in_(_LIVE)
        )
    )


def settle(db: Session, draft: OutreachDraft) -> OutreachDraft:
    """Apply what time has decided, whenever a draft is read or acted on."""
    if draft.status in (DraftStatus.pending_approval, DraftStatus.approved):
        approval = _live_approval(db, draft)
        if approval is not None and approval.expires_at <= _now():
            approval.status = ApprovalStatus.expired
            draft.status = DraftStatus.draft
            db.flush()
    elif draft.status == DraftStatus.sending:
        db.execute(
            update(Delivery)
            .where(
                Delivery.draft_id == draft.id,
                Delivery.status == DeliveryStatus.sending,
                Delivery.created_at <= _now() - STALE_SENDING,
            )
            .values(
                status=DeliveryStatus.unknown,
                error_category="interrupted",
                finished_at=_now(),
            )
        )
        still_going = db.scalar(
            select(Delivery.id).where(
                Delivery.draft_id == draft.id, Delivery.status == DeliveryStatus.sending
            )
        )
        if still_going is None:
            draft.status = DraftStatus.send_unknown
            db.flush()
    return draft


def _visible(ctx: OrgContext) -> Any:
    return (
        select(OutreachDraft)
        .join(Lead, Lead.id == OutreachDraft.lead_id)
        .where(OutreachDraft.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
    )


def list_drafts(
    db: Session,
    ctx: OrgContext,
    *,
    status: DraftStatus | None = None,
    lead_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[OutreachDraft]:
    query = _visible(ctx)
    if lead_id:
        query = query.where(OutreachDraft.lead_id == lead_id)
    rows = [
        settle(db, d)
        for d in db.scalars(query.order_by(OutreachDraft.created_at.desc()).limit(limit))
    ]
    return [d for d in rows if status is None or d.status == status]


def get_draft(
    db: Session, ctx: OrgContext, draft_id: uuid.UUID, *, lock: bool = False
) -> OutreachDraft:
    query = _visible(ctx).where(OutreachDraft.id == draft_id)
    draft = db.scalar(query.with_for_update(of=OutreachDraft) if lock else query)
    if draft is None:
        raise NotFoundError("Draft not found")
    return settle(db, draft)


def _supersede(db: Session, draft: OutreachDraft) -> None:
    db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.draft_id == draft.id, ApprovalRequest.status.in_(_LIVE))
        .values(status=ApprovalStatus.superseded)
    )


def update_draft(
    db: Session,
    ctx: OrgContext,
    draft_id: uuid.UUID,
    *,
    expected_version: int,
    subject: str | None,
    body: str | None,
) -> OutreachDraft:
    """Any edit ends an approval. The address is read again, in case the lead's has changed."""
    draft = get_draft(db, ctx, draft_id, lock=True)
    if draft.status not in _EDITABLE:
        raise ConflictError("This draft can no longer be edited", code="not_editable")
    if draft.version != expected_version:
        raise ConflictError("Someone else changed this draft. Reload it first.", code="stale")
    new_subject = subject if subject is not None else draft.subject
    new_body = body if body is not None else draft.body
    check_text(new_subject, new_body)
    recipient = _recipient_for(db, ctx, get_lead(db, ctx, draft.lead_id))
    changed = content_hash(recipient, new_subject, new_body) != draft.content_hash
    if not changed:
        return draft
    _supersede(db, draft)
    draft.subject, draft.body, draft.recipient = new_subject, new_body, recipient
    draft.content_hash = content_hash(recipient, new_subject, new_body)
    draft.version += 1
    draft.status = DraftStatus.draft
    # The flagged links have to actually go. A person can add links of their own.
    text = f"{new_subject}\n{new_body}".lower()
    draft.flagged_contacts = [c for c in draft.flagged_contacts if c in text]
    draft.needs_edit = bool(draft.flagged_contacts)
    if not draft.needs_edit:
        draft.flags = [f for f in draft.flags if f != "contains_contact"]
    draft.rejection_note = None
    draft.updated_by_user_id = ctx.user_id
    db.flush()
    _record(db, ctx, "draft_edited", draft, version=draft.version)
    return draft


def discard_draft(db: Session, ctx: OrgContext, draft_id: uuid.UUID) -> OutreachDraft:
    draft = get_draft(db, ctx, draft_id, lock=True)
    if draft.status not in _EDITABLE:
        raise ConflictError("This draft can no longer be discarded", code="not_editable")
    _supersede(db, draft)
    draft.status = DraftStatus.discarded
    draft.updated_by_user_id = ctx.user_id
    db.flush()
    _record(db, ctx, "draft_discarded", draft)
    return draft


# --- approvals -----------------------------------------------------------------------------


def request_approval(db: Session, ctx: OrgContext, draft_id: uuid.UUID) -> ApprovalRequest:
    draft = get_draft(db, ctx, draft_id, lock=True)
    if draft.status != DraftStatus.draft:
        raise ConflictError("Only a draft can go for approval", code="not_a_draft")
    if draft.needs_edit:
        raise ConflictError(
            "Take out the link or address the checks flagged first.",
            code="needs_edit",
        )
    recipient = _recipient_for(db, ctx, get_lead(db, ctx, draft.lead_id))
    if recipient != draft.recipient:
        raise ConflictError(
            "The lead's address has changed. Edit the draft to use the new one.",
            code="address_changed",
        )
    approval = ApprovalRequest(
        organization_id=ctx.org_id,
        draft_id=draft.id,
        status=ApprovalStatus.pending,
        draft_version=draft.version,
        content_hash=draft.content_hash,
        recipient=draft.recipient,
        requested_by_user_id=ctx.user_id,
        expires_at=_now() + APPROVAL_TTL,
    )
    db.add(approval)
    draft.status = DraftStatus.pending_approval
    draft.rejection_note = None
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("This draft is already awaiting a decision") from exc
    _record(db, ctx, "approval_requested", approval, draft_id=str(draft.id))
    return approval


def list_approvals(
    db: Session, ctx: OrgContext, *, status: ApprovalStatus | None, limit: int = 100
) -> list[tuple[ApprovalRequest, OutreachDraft]]:
    query = (
        select(ApprovalRequest, OutreachDraft)
        .join(OutreachDraft, OutreachDraft.id == ApprovalRequest.draft_id)
        .join(Lead, Lead.id == OutreachDraft.lead_id)
        .where(ApprovalRequest.organization_id == ctx.org_id, Lead.deleted_at.is_(None))
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    rows = [(a, settle(db, d)) for a, d in db.execute(query).all()]
    return [(a, d) for a, d in rows if status is None or a.status == status]


def latest_approval(db: Session, draft: OutreachDraft) -> ApprovalRequest | None:
    return db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.draft_id == draft.id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(1)
    )


def _pending_for(
    db: Session, ctx: OrgContext, approval_id: uuid.UUID
) -> tuple[ApprovalRequest, OutreachDraft]:
    found = db.execute(
        select(ApprovalRequest.draft_id).where(
            ApprovalRequest.id == approval_id, ApprovalRequest.organization_id == ctx.org_id
        )
    ).first()
    if found is None:
        raise NotFoundError("Approval request not found")
    # The draft first, in the same order as everything else that touches both.
    draft = get_draft(db, ctx, found.draft_id, lock=True)
    approval = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert approval is not None
    if approval.status != ApprovalStatus.pending:
        raise ConflictError("This request is no longer waiting for a decision", code="not_pending")
    return approval, draft


def approve(
    db: Session, ctx: OrgContext, approval_id: uuid.UUID, seen_hash: str
) -> ApprovalRequest:
    """`seen_hash` is what the approver's screen showed, so a late edit cannot slip through."""
    approval, draft = _pending_for(db, ctx, approval_id)
    if seen_hash != approval.content_hash or approval.content_hash != draft.content_hash:
        raise ConflictError(
            "This draft changed after you opened it. Read it again.", code="content_changed"
        )
    now = _now()
    approval.status = ApprovalStatus.approved
    approval.decided_by_user_id = ctx.user_id
    approval.decided_at = now
    draft.status = DraftStatus.approved
    db.flush()
    _record(
        db,
        ctx,
        "approved",
        approval,
        draft_id=str(draft.id),
        content_hash=approval.content_hash,
        own_request=approval.requested_by_user_id == ctx.user_id,
    )
    return approval


def reject(db: Session, ctx: OrgContext, approval_id: uuid.UUID, note: str) -> ApprovalRequest:
    approval, draft = _pending_for(db, ctx, approval_id)
    approval.status = ApprovalStatus.rejected
    approval.decided_by_user_id = ctx.user_id
    approval.decided_at = _now()
    approval.note = note
    draft.status = DraftStatus.draft
    draft.rejection_note = note
    db.flush()
    _record(db, ctx, "rejected", approval, draft_id=str(draft.id))
    return approval


def sources_for(db: Session, draft: OutreachDraft) -> list[ResearchEvidence]:
    """What a draft rests on, so its reviewer can compare. May itself hold hostile text."""
    ids = []
    for value in draft.evidence_ids:
        with contextlib.suppress(ValueError):
            ids.append(uuid.UUID(value))
    if not ids:
        return []
    return list(
        db.scalars(
            select(ResearchEvidence).where(
                ResearchEvidence.id.in_(ids),
                ResearchEvidence.organization_id == draft.organization_id,
                ResearchEvidence.lead_id == draft.lead_id,
            )
        )
    )


def deliveries_for(db: Session, draft: OutreachDraft) -> list[Delivery]:
    return list(
        db.scalars(
            select(Delivery).where(Delivery.draft_id == draft.id).order_by(Delivery.created_at)
        )
    )
