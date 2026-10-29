"""Audit trail writes. Entries join the caller's transaction and commit with the change."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.observability.logging import redact, request_id_var


def record(
    db: Session,
    action: str,
    *,
    org_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=org_id,
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            request_id=request_id_var.get(),
            data=redact(data or {}),
        )
    )
