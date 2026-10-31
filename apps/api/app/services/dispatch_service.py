"""The only code that sends outreach. Every rule is checked again here, just before the email goes.

A delivery row is committed before the connection opens, and no database connection is held while
it is open. A crash in between leaves `unknown`, which a person resolves. It never retries by
itself, because the one thing worse than a lost email is the same email twice.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import make_msgid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import OrgContext, restore_context
from app.core.config import get_settings
from app.core.crypto import CredentialError
from app.core.db import set_tenant_context
from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import Permission, has_permission
from app.core.security import read_unsubscribe_token, unsubscribe_token
from app.integrations.dispatch import (
    Outcome,
    OutgoingEmail,
    SmtpTarget,
    build_message,
    send_smtp,
    unavailable_reason,
)
from app.models import (
    Activity,
    ActivityType,
    ApprovalRequest,
    ApprovalStatus,
    Delivery,
    DeliveryStatus,
    DraftStatus,
    Lead,
    LeadStatus,
    Membership,
    OutreachDraft,
    OutreachSettings,
    SuppressionEntry,
    SuppressionKind,
    SuppressionReason,
    User,
)
from app.services import (
    audit,
    integration_service,
    outreach_service,
    quota_service,
    suppression_service,
)

log = logging.getLogger(__name__)

# These may have reached the person, so they count toward limits and against sending again.
_COUNTED = (DeliveryStatus.sending, DeliveryStatus.accepted, DeliveryStatus.unknown)

BLOCKER_MESSAGES = {
    "dispatch_disabled": "Sending is turned off on this server.",
    "external_not_allowed": "This server may not send beyond this machine.",
    "connection_host_refused": "The connected mail server's address or port is not allowed.",
    "connection_needs_tls": "The connected mail server has to use STARTTLS.",
    "credential_unreadable": "The connected mail server's password cannot be read. Enter it again.",
    "monthly_email_limit": "This month's email limit on your plan has been reached.",
    "integrations_not_included": "Your plan does not include the connected mail server.",
    "sends_off": "Sending is turned off for this organization. An admin can turn it on.",
    "sender_missing": "Set a sender name, sender email, and postal address in outreach settings.",
    "not_approved": "This draft has not been approved.",
    "approval_missing": "No approval is in force for this draft.",
    "approval_mismatch": "The text or address differs from what was approved.",
    "approver_lost_authority": "The person who approved this can no longer approve outreach.",
    "lead_gone": "This lead no longer exists.",
    "address_changed": "The lead's address has changed since this was approved.",
    "lead_disqualified": "This lead is disqualified.",
    "suppressed": "This address is on the suppression list.",
    "recontact_too_soon": "This address was contacted too recently.",
    "daily_limit": "Today's sending limit has been reached.",
    "quiet_hours": "It is within quiet hours.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _in_quiet_hours(settings: OutreachSettings, now: datetime) -> bool:
    start, end = settings.quiet_start_hour, settings.quiet_end_hour
    if start is None or end is None or start == end:
        return False
    hour = now.astimezone(ZoneInfo(settings.timezone)).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def _start_of_day(settings: OutreachSettings, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(settings.timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _approver_can_still_approve(db: Session, approval: ApprovalRequest) -> bool:
    if approval.decided_by_user_id is None:
        return False
    row = db.execute(
        select(Membership.role, User.disabled_at)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == approval.organization_id,
            Membership.user_id == approval.decided_by_user_id,
        )
    ).first()
    return (
        row is not None
        and row.disabled_at is None
        and has_permission(row.role, Permission.outreach_approve)
    )


def blockers(
    db: Session, draft: OutreachDraft, settings: OutreachSettings, now: datetime | None = None
) -> list[str]:
    """Everything standing in the way of sending this draft right now."""
    now = now or _now()
    found: list[str] = []
    connection = integration_service.active_smtp(db, draft.organization_id)
    if connection is None:
        reason = unavailable_reason()
    else:
        # Settings only. The password and DNS are left to the moment of sending.
        c = connection.config
        reason = unavailable_reason(
            SmtpTarget(c["host"], int(c["port"]), bool(c["starttls"]), from_connection=True)
        )
    if reason:
        found.append(reason)
    plan = quota_service.plan_for(db, draft.organization_id)
    if connection is not None and not plan.integrations:
        found.append("integrations_not_included")
    if quota_service.remaining(db, draft.organization_id, "monthly_emails") == 0:
        found.append("monthly_email_limit")
    if not settings.sends_enabled:
        found.append("sends_off")
    if not (settings.sender_name and settings.sender_email and settings.postal_address):
        found.append("sender_missing")

    if draft.status != DraftStatus.approved:
        found.append("not_approved")
    else:
        approval = db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.draft_id == draft.id,
                ApprovalRequest.status == ApprovalStatus.approved,
                ApprovalRequest.expires_at > now,
            )
        )
        if approval is None:
            found.append("approval_missing")
        else:
            actual = outreach_service.content_hash(draft.recipient, draft.subject, draft.body)
            if (
                actual != approval.content_hash
                or actual != draft.content_hash
                or draft.recipient != approval.recipient
                or draft.version != approval.draft_version
            ):
                found.append("approval_mismatch")
            if not _approver_can_still_approve(db, approval):
                found.append("approver_lost_authority")

    lead = db.scalar(select(Lead).where(Lead.id == draft.lead_id, Lead.deleted_at.is_(None)))
    if lead is None:
        found.append("lead_gone")
    else:
        if lead.email != draft.recipient:
            found.append("address_changed")
        if lead.status == LeadStatus.disqualified:
            found.append("lead_disqualified")
    if suppression_service.find_suppression(db, draft.organization_id, draft.recipient):
        found.append("suppressed")
    if settings.recontact_days > 0:
        recent = db.scalar(
            select(Delivery.id)
            .where(
                Delivery.organization_id == draft.organization_id,
                Delivery.recipient == draft.recipient,
                Delivery.status.in_(_COUNTED),
                Delivery.created_at > now - timedelta(days=settings.recontact_days),
            )
            .limit(1)
        )
        if recent is not None:
            found.append("recontact_too_soon")
    today = db.scalar(
        select(func.count())
        .select_from(Delivery)
        .where(
            Delivery.organization_id == draft.organization_id,
            Delivery.status.in_(_COUNTED),
            Delivery.created_at >= _start_of_day(settings, now),
        )
    )
    if (today or 0) >= settings.daily_limit:
        found.append("daily_limit")
    if _in_quiet_hours(settings, now):
        found.append("quiet_hours")
    return found


def preflight(db: Session, draft: OutreachDraft) -> list[str]:
    return blockers(db, draft, suppression_service.get_settings_row(db, draft.organization_id))


def _footer(settings: OutreachSettings, url: str) -> str:
    return f"\n\n--\n{settings.sender_name}\n{settings.postal_address}\nTo stop these emails: {url}"


def _unsubscribe_urls(org_id: uuid.UUID, delivery_id: uuid.UUID) -> tuple[str, str]:
    """The page a person opens, and the address a mail provider's one-click request posts to."""
    base = get_settings().web_base_url.rstrip("/")
    token = unsubscribe_token(org_id, delivery_id)
    return f"{base}/unsubscribe/{token}", f"{base}/api/v1/unsubscribe/{token}"


def send(db: Session, ctx: OrgContext, draft_id: uuid.UUID) -> Delivery:
    """Commits as it goes: a record that an email is leaving must exist before it leaves."""
    settings = suppression_service.get_settings_row(db, ctx.org_id, lock=True)
    draft = outreach_service.get_draft(db, ctx, draft_id, lock=True)
    found = blockers(db, draft, settings)
    if found:
        audit.record(
            db,
            "outreach.send_blocked",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="outreach_draft",
            target_id=draft.id,
            data={"reasons": found},
        )
        db.commit()
        raise ConflictError(
            BLOCKER_MESSAGES[found[0]],
            code="send_blocked",
            details=[{"code": c, "message": BLOCKER_MESSAGES[c]} for c in found],
        )
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.draft_id == draft.id, ApprovalRequest.status == ApprovalStatus.approved
        )
    )
    assert approval is not None
    connection = integration_service.active_smtp(db, ctx.org_id)
    connection_id = connection.id if connection else None
    try:
        target = integration_service.target_of(connection) if connection else None
    except CredentialError as exc:
        db.rollback()
        raise ConflictError(
            BLOCKER_MESSAGES["credential_unreadable"], code="credential_unreadable"
        ) from exc
    delivery = Delivery(
        id=uuid.uuid4(),
        organization_id=ctx.org_id,
        draft_id=draft.id,
        approval_id=approval.id,
        status=DeliveryStatus.sending,
        adapter="smtp_connection" if connection else get_settings().dispatch_adapter,
        recipient=draft.recipient,
        content_hash=draft.content_hash,
        sent_by_user_id=ctx.user_id,
    )
    db.add(delivery)
    draft.status = DraftStatus.sending
    audit.record(
        db,
        "outreach.send_started",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="delivery",
        target_id=delivery.id,
        data={"draft_id": str(draft.id), "approval_id": str(approval.id)},
    )
    # Recorded before it leaves, so a provider's event cannot arrive ahead of its delivery.
    delivery.message_id = make_msgid(domain=(settings.sender_email or "").rpartition("@")[2])
    url, one_click_url = _unsubscribe_urls(ctx.org_id, delivery.id)
    assert settings.sender_name and settings.sender_email
    email = OutgoingEmail(
        to=draft.recipient,
        sender_name=settings.sender_name,
        sender_email=settings.sender_email,
        subject=draft.subject,
        body=draft.body + _footer(settings, url),
        one_click_url=one_click_url,
        message_id=delivery.message_id,
    )
    try:
        build_message(email)
    except ValueError as exc:
        # Before anything is recorded as leaving, because nothing has.
        db.rollback()
        raise ConflictError("This email cannot be built", code="message_invalid") from exc
    db.commit()

    try:
        outcome = send_smtp(email, target)
    except Exception as exc:
        log.warning("dispatch_failed", extra={"error_type": type(exc).__name__})
        outcome = Outcome(DeliveryStatus.unknown, category="adapter_error")

    restore_context(db, ctx)
    _finish(db, ctx, draft.id, delivery.id, outcome)
    if connection_id is not None and outcome.status != DeliveryStatus.unknown:
        # The address's own refusal says the server is working.
        problem = outcome.category if outcome.status == DeliveryStatus.failed else None
        integration_service.record_health(db, ctx.org_id, connection_id, problem)
    db.commit()
    restore_context(db, ctx)
    finished = db.get(Delivery, delivery.id, populate_existing=True)
    assert finished is not None
    return finished


def _finish(
    db: Session, ctx: OrgContext, draft_id: uuid.UUID, delivery_id: uuid.UUID, outcome: Outcome
) -> None:
    draft = db.get(OutreachDraft, draft_id, populate_existing=True, with_for_update=True)
    delivery = db.get(Delivery, delivery_id, populate_existing=True, with_for_update=True)
    assert delivery is not None and draft is not None
    if delivery.resolved_by_user_id is not None:
        # This send outlasted the point of being called interrupted, and someone has settled it.
        log.warning("dispatch_finished_after_resolution", extra={"delivery": str(delivery_id)})
        return
    delivery.status = outcome.status
    delivery.error_category = outcome.category
    delivery.finished_at = _now()
    if outcome.status == DeliveryStatus.accepted:
        draft.status = DraftStatus.sent
        db.add(
            Activity(
                organization_id=ctx.org_id,
                lead_id=draft.lead_id,
                actor_user_id=ctx.user_id,
                type=ActivityType.outreach_sent,
                data={"draft_id": str(draft.id), "delivery_id": str(delivery.id)},
            )
        )
    elif outcome.status == DeliveryStatus.rejected:
        draft.status = DraftStatus.undeliverable
        if outcome.category == "recipient_refused":
            suppression_service.suppress(
                db,
                ctx.org_id,
                SuppressionKind.email,
                draft.recipient,
                SuppressionReason.bounced,
            )
    elif outcome.status == DeliveryStatus.unknown:
        draft.status = DraftStatus.send_unknown
    else:
        draft.status = DraftStatus.approved
    audit.record(
        db,
        "outreach.send_finished",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="delivery",
        target_id=delivery.id,
        data={"status": outcome.status.value, "category": outcome.category},
    )


def resolve_unknown(
    db: Session, ctx: OrgContext, delivery_id: uuid.UUID, *, sent: bool
) -> Delivery:
    """A person checked the mail server's logs, which this system cannot do for them."""
    found = db.execute(
        select(Delivery.draft_id).where(
            Delivery.id == delivery_id, Delivery.organization_id == ctx.org_id
        )
    ).first()
    if found is None:
        raise NotFoundError("Delivery not found")
    draft = outreach_service.get_draft(db, ctx, found.draft_id, lock=True)
    delivery = db.get(Delivery, delivery_id, populate_existing=True, with_for_update=True)
    assert delivery is not None
    if delivery.status != DeliveryStatus.unknown:
        raise ConflictError("This delivery's outcome is already known", code="not_unknown")
    delivery.status = DeliveryStatus.accepted if sent else DeliveryStatus.failed
    delivery.resolved_by_user_id = ctx.user_id
    delivery.finished_at = _now()
    draft.status = DraftStatus.sent if sent else DraftStatus.approved
    db.flush()
    outreach_service.settle(db, draft)
    audit.record(
        db,
        "outreach.delivery_resolved",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="delivery",
        target_id=delivery.id,
        data={"sent": sent},
    )
    return delivery


def opt_out(db: Session, token: str) -> bool:
    """From a link in an email, so no one is signed in. The signature proves which organization
    and delivery it names, and that decides the tenant here. Only a POST reaches this, because
    mail scanners follow links and must not be able to unsubscribe anyone."""
    parsed = read_unsubscribe_token(token)
    if parsed is None:
        return False
    org_id, delivery_id = parsed
    set_tenant_context(db, user_id=None, org_id=org_id)
    row = db.execute(
        select(Delivery.recipient, OutreachDraft.lead_id)
        .join(OutreachDraft, OutreachDraft.id == Delivery.draft_id)
        .where(Delivery.id == delivery_id)
    ).first()
    if row is None:
        return False
    already = db.scalar(
        select(SuppressionEntry.id).where(
            SuppressionEntry.organization_id == org_id,
            SuppressionEntry.kind == SuppressionKind.email,
            SuppressionEntry.value == row.recipient,
            SuppressionEntry.reason == SuppressionReason.opt_out,
            SuppressionEntry.removed_at.is_(None),
        )
    )
    suppression_service.suppress(
        db, org_id, SuppressionKind.email, row.recipient, SuppressionReason.opt_out
    )
    if already is None:
        db.add(
            Activity(
                organization_id=org_id,
                lead_id=row.lead_id,
                type=ActivityType.opted_out,
                data={"delivery_id": str(delivery_id)},
            )
        )
        audit.record(
            db,
            "outreach.opted_out",
            org_id=org_id,
            target_type="delivery",
            target_id=delivery_id,
        )
    return True
