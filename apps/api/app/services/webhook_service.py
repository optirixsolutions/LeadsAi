"""Signed events from an email provider: what happened to a message after it was accepted.

The URL names an organization and a connection, which proves nothing. The tenant is trusted only
once the signature checks out against that connection's own secret. The signature covers the time
as well as the body, and each event ID applies once, so a captured request cannot be replayed.
"""

import hashlib
import hmac
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.crypto import CredentialError
from app.core.db import set_tenant_context
from app.core.errors import AppError
from app.models import (
    Delivery,
    IntegrationConnection,
    SuppressionKind,
    SuppressionReason,
    WebhookEvent,
)
from app.services import audit, integration_service, suppression_service

MAX_AGE_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
# Later news does not undo worse news: a delivered event arriving late must not hide a bounce.
_RANK = {"deferred": 1, "delivered": 2, "bounced": 3, "complained": 4}


class WebhookRejectedError(AppError):
    """One answer for every reason, so that it cannot be used to learn what exists."""

    status_code = 401
    code = "webhook_rejected"


class EmailEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=200)
    type: Literal["delivered", "bounced", "complained", "deferred"]
    message_id: str = Field(min_length=1, max_length=255)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return (
        "v1="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )


def _timestamp_is_fresh(timestamp: str) -> bool:
    try:
        return abs(time.time() - int(timestamp)) <= MAX_AGE_SECONDS
    except ValueError:
        return False


def receive(
    db: Session,
    org_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
) -> str:
    """Returns "applied", "ignored", or "duplicate". Raises WebhookRejectedError if unsigned."""
    rejected = WebhookRejectedError("This request could not be verified")
    if not timestamp or not signature or not _timestamp_is_fresh(timestamp):
        raise rejected
    set_tenant_context(db, user_id=None, org_id=org_id)
    connection = db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.removed_at.is_(None),
        )
    )
    try:
        secret = integration_service.webhook_secret_of(connection) if connection else None
    except CredentialError:
        secret = None
    if secret is None or not hmac.compare_digest(
        sign(secret, timestamp, body).encode(), signature.encode()
    ):
        raise rejected
    try:
        event = EmailEvent.model_validate_json(body)
    except ValidationError as exc:
        raise AppError("The event could not be read", code="invalid_event") from exc

    delivery = db.scalar(
        select(Delivery)
        .where(Delivery.organization_id == org_id, Delivery.message_id == event.message_id)
        .with_for_update()
    )
    if delivery is None:
        # Not stored, so a provider's retry still counts if the delivery turns up later.
        return "ignored"
    inserted = db.execute(
        pg_insert(WebhookEvent)
        .values(
            id=uuid.uuid4(),
            organization_id=org_id,
            connection_id=connection_id,
            event_id=event.id,
            event_type=event.type,
            message_id=event.message_id,
            delivery_id=delivery.id,
        )
        .on_conflict_do_nothing(index_elements=["connection_id", "event_id"])
        .returning(WebhookEvent.id)
    ).first()
    if inserted is None:
        return "duplicate"
    if _RANK[event.type] > _RANK.get(delivery.provider_status or "", 0):
        delivery.provider_status = event.type
    if event.type == "bounced":
        suppression_service.suppress(
            db, org_id, SuppressionKind.email, delivery.recipient, SuppressionReason.bounced
        )
    elif event.type == "complained":
        # A spam complaint is the strongest opt-out there is, and is treated as one.
        suppression_service.suppress(
            db, org_id, SuppressionKind.email, delivery.recipient, SuppressionReason.opt_out
        )
    audit.record(
        db,
        "integration.webhook_applied",
        org_id=org_id,
        target_type="delivery",
        target_id=delivery.id,
        data={"type": event.type},
    )
    return "applied"
