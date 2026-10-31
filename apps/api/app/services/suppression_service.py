"""Who must not be contacted, and an organization's sending settings."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import (
    OutreachSettings,
    SuppressionEntry,
    SuppressionKind,
    SuppressionReason,
)
from app.services import audit
from app.services.normalize import normalize_domain, normalize_email


def _now() -> datetime:
    return datetime.now(UTC)


def _record(
    db: Session, ctx: OrgContext, action: str, target: SuppressionEntry, **data: Any
) -> None:
    audit.record(
        db,
        f"outreach.{action}",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="suppression_entries",
        target_id=target.id,
        data=data,
    )


def find_suppression(db: Session, org_id: uuid.UUID, email: str) -> SuppressionEntry | None:
    domain = email.rpartition("@")[2]
    return db.scalar(
        select(SuppressionEntry)
        .where(
            SuppressionEntry.organization_id == org_id,
            SuppressionEntry.removed_at.is_(None),
            ((SuppressionEntry.kind == SuppressionKind.email) & (SuppressionEntry.value == email))
            | (
                (SuppressionEntry.kind == SuppressionKind.domain)
                & (SuppressionEntry.value == domain)
            ),
        )
        .limit(1)
    )


def suppress(
    db: Session,
    org_id: uuid.UUID,
    kind: SuppressionKind,
    value: str,
    reason: SuppressionReason,
    *,
    note: str | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Adding what is already there changes nothing, so an opt-out link can be clicked twice. The
    exception is an opt-out landing on another kind of entry: it has to become one, or a person
    could later remove the entry and undo what the recipient asked for."""
    statement = pg_insert(SuppressionEntry).values(
        id=uuid.uuid4(),
        organization_id=org_id,
        kind=kind,
        value=value,
        reason=reason,
        note=note,
        created_by_user_id=user_id,
    )
    columns = ["organization_id", "kind", "value"]
    active = SuppressionEntry.removed_at.is_(None)
    if reason == SuppressionReason.opt_out:
        db.execute(
            statement.on_conflict_do_update(
                index_elements=columns, index_where=active, set_={"reason": reason}
            )
        )
    else:
        db.execute(statement.on_conflict_do_nothing(index_elements=columns, index_where=active))


def add_suppression(
    db: Session, ctx: OrgContext, kind: SuppressionKind, value: str, note: str | None
) -> SuppressionEntry:
    try:
        normalized = (
            normalize_email(value) if kind == SuppressionKind.email else normalize_domain(value)
        )
    except ValueError:
        normalized = None
    if not normalized:
        raise AppError("That is not a valid address or domain", code="invalid_value")
    suppress(
        db, ctx.org_id, kind, normalized, SuppressionReason.manual, note=note, user_id=ctx.user_id
    )
    entry = db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.organization_id == ctx.org_id,
            SuppressionEntry.kind == kind,
            SuppressionEntry.value == normalized,
            SuppressionEntry.removed_at.is_(None),
        )
    )
    assert entry is not None
    _record(db, ctx, "suppression_added", entry, kind=kind.value)
    return entry


def list_suppressions(db: Session, ctx: OrgContext, limit: int = 200) -> list[SuppressionEntry]:
    return list(
        db.scalars(
            select(SuppressionEntry)
            .where(
                SuppressionEntry.organization_id == ctx.org_id,
                SuppressionEntry.removed_at.is_(None),
            )
            .order_by(SuppressionEntry.created_at.desc())
            .limit(limit)
        )
    )


def remove_suppression(db: Session, ctx: OrgContext, entry_id: uuid.UUID) -> None:
    """Someone who opted out asked not to be contacted, and a person's say-so does not undo that."""
    entry = db.scalar(
        select(SuppressionEntry)
        .where(
            SuppressionEntry.id == entry_id,
            SuppressionEntry.organization_id == ctx.org_id,
            SuppressionEntry.removed_at.is_(None),
        )
        .with_for_update()
    )
    if entry is None:
        raise NotFoundError("Suppression entry not found")
    if entry.reason == SuppressionReason.opt_out:
        raise ConflictError(
            "This person opted out, so the entry cannot be removed", code="opted_out"
        )
    entry.removed_at = _now()
    entry.removed_by_user_id = ctx.user_id
    _record(db, ctx, "suppression_removed", entry, kind=entry.kind.value)


def get_settings_row(db: Session, org_id: uuid.UUID, *, lock: bool = False) -> OutreachSettings:
    """Made on first use, with sending off. Locking it serializes one organization's sends, so
    two at once cannot both squeeze under a limit or both reach the same address."""
    db.execute(
        pg_insert(OutreachSettings)
        .values(organization_id=org_id, sends_enabled=False)
        .on_conflict_do_nothing()
    )
    query = select(OutreachSettings).where(OutreachSettings.organization_id == org_id)
    row = db.scalar(query.with_for_update() if lock else query)
    assert row is not None
    return row


def update_settings(db: Session, ctx: OrgContext, values: dict[str, Any]) -> OutreachSettings:
    row = get_settings_row(db, ctx.org_id, lock=True)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by_user_id = ctx.user_id
    db.flush()
    audit.record(
        db,
        "outreach.settings_updated",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="outreach_settings",
        target_id=ctx.org_id,
        data={"fields": sorted(values), "sends_enabled": row.sends_enabled},
    )
    db.refresh(row)
    return row
