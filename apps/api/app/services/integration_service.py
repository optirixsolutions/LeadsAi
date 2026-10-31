"""Connecting a provider, checking it, and reading its secrets when they are needed."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import OrgContext, restore_context
from app.core.crypto import CredentialError, decrypt, encrypt
from app.core.errors import AppError, ConflictError, NotFoundError
from app.integrations.dispatch import SmtpTarget, probe_smtp, target_blocker
from app.models import ConnectionHealth, ConnectionKind, IntegrationConnection
from app.services import audit, quota_service


def _now() -> datetime:
    return datetime.now(UTC)


def _context(org_id: uuid.UUID, connection_id: uuid.UUID, purpose: str) -> str:
    return f"{org_id}:{connection_id}:{purpose}"


def _new_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _record(db: Session, ctx: OrgContext, action: str, connection: IntegrationConnection) -> None:
    # Never the host's password or the webhook secret.
    audit.record(
        db,
        f"integration.{action}",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="integration_connection",
        target_id=connection.id,
        data={"kind": connection.kind.value, "host": connection.config.get("host")},
    )


def _check_target(host: str, port: int, starttls: bool) -> None:
    if reason := target_blocker(host, port, starttls):
        raise AppError(_TARGET_MESSAGES[reason], code=reason)


_TARGET_MESSAGES = {
    "external_not_allowed": "This server may not send beyond this machine.",
    "connection_host_refused": "That mail server's address or port is not allowed.",
    "connection_needs_tls": "A mail server beyond this machine has to use STARTTLS.",
}


def _require_plan(db: Session, ctx: OrgContext) -> None:
    plan = quota_service.plan_for(db, ctx.org_id)
    if not plan.integrations:
        raise quota_service.QuotaExceededError(
            f"Your {plan.label} plan does not include integrations.",
            details={"metric": "integrations", "plan": plan.key},
        )


def create_smtp(
    db: Session,
    ctx: OrgContext,
    *,
    name: str,
    host: str,
    port: int,
    starttls: bool,
    username: str | None,
    password: str | None,
) -> tuple[IntegrationConnection, str]:
    """Returns the webhook secret, which is shown this one time."""
    _require_plan(db, ctx)
    _check_target(host, port, starttls)
    connection = IntegrationConnection(
        id=uuid.uuid4(),
        organization_id=ctx.org_id,
        kind=ConnectionKind.email_smtp,
        name=name,
        config={"host": host, "port": port, "starttls": starttls, "username": username},
        health=ConnectionHealth.unknown,
        created_by_user_id=ctx.user_id,
    )
    secret = _new_webhook_secret()
    connection.encrypted_webhook_secret = encrypt(
        secret, context=_context(ctx.org_id, connection.id, "webhook")
    )
    if password:
        connection.encrypted_password = encrypt(
            password, context=_context(ctx.org_id, connection.id, "password")
        )
    db.add(connection)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "An email connection already exists. Remove it first.", code="already_connected"
        ) from exc
    _record(db, ctx, "connected", connection)
    return connection, secret


def list_connections(db: Session, ctx: OrgContext) -> list[IntegrationConnection]:
    return list(
        db.scalars(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.organization_id == ctx.org_id,
                IntegrationConnection.removed_at.is_(None),
            )
            .order_by(IntegrationConnection.created_at)
        )
    )


def _get(
    db: Session, ctx: OrgContext, connection_id: uuid.UUID, *, lock: bool = False
) -> IntegrationConnection:
    query = select(IntegrationConnection).where(
        IntegrationConnection.id == connection_id,
        IntegrationConnection.organization_id == ctx.org_id,
        IntegrationConnection.removed_at.is_(None),
    )
    connection = db.scalar(query.with_for_update() if lock else query)
    if connection is None:
        raise NotFoundError("Connection not found")
    return connection


def update_smtp(
    db: Session, ctx: OrgContext, connection_id: uuid.UUID, changes: dict[str, Any]
) -> IntegrationConnection:
    """Leaving the password out keeps it. It is never sent back to be edited."""
    connection = _get(db, ctx, connection_id, lock=True)
    _require_plan(db, ctx)
    config = {**connection.config}
    for key in ("host", "port", "starttls", "username"):
        if key in changes:
            config[key] = changes[key]
    # Otherwise anyone who can edit this could aim it at their own server, press Check, and
    # receive the password. Sending it somewhere new takes knowing it.
    moved = any(
        config[k] != connection.config.get(k) for k in ("host", "port", "starttls", "username")
    )
    if moved and connection.encrypted_password and "password" not in changes:
        raise AppError(
            "Enter the password again to change where this connection goes",
            code="password_required",
        )
    _check_target(config["host"], config["port"], config["starttls"])
    connection.config = config
    if changes.get("name"):
        connection.name = changes["name"]
    if "password" in changes:
        connection.encrypted_password = (
            encrypt(changes["password"], context=_context(ctx.org_id, connection.id, "password"))
            if changes["password"]
            else None
        )
    connection.health = ConnectionHealth.unknown
    connection.last_error_category = None
    db.flush()
    _record(db, ctx, "updated", connection)
    return connection


def rotate_webhook_secret(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> str:
    connection = _get(db, ctx, connection_id, lock=True)
    secret = _new_webhook_secret()
    connection.encrypted_webhook_secret = encrypt(
        secret, context=_context(ctx.org_id, connection.id, "webhook")
    )
    _record(db, ctx, "webhook_secret_rotated", connection)
    return secret


def remove(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> None:
    """The secrets go at once. The row stays, for what the audit trail and events point to."""
    connection = _get(db, ctx, connection_id, lock=True)
    connection.removed_at = _now()
    connection.encrypted_password = None
    connection.encrypted_webhook_secret = None
    _record(db, ctx, "removed", connection)


def active_smtp(db: Session, org_id: uuid.UUID) -> IntegrationConnection | None:
    return db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.kind == ConnectionKind.email_smtp,
            IntegrationConnection.removed_at.is_(None),
        )
    )


def target_of(connection: IntegrationConnection) -> SmtpTarget:
    """Raises CredentialError if the stored password cannot be read."""
    password = None
    if connection.encrypted_password:
        password = decrypt(
            connection.encrypted_password,
            context=_context(connection.organization_id, connection.id, "password"),
        )
    config = connection.config
    return SmtpTarget(
        host=config["host"],
        port=int(config["port"]),
        starttls=bool(config["starttls"]),
        username=config.get("username"),
        password=password,
        from_connection=True,
    )


def webhook_secret_of(connection: IntegrationConnection) -> str | None:
    if not connection.encrypted_webhook_secret:
        return None
    return decrypt(
        connection.encrypted_webhook_secret,
        context=_context(connection.organization_id, connection.id, "webhook"),
    )


def record_health(
    db: Session, org_id: uuid.UUID, connection_id: uuid.UUID, category: str | None
) -> None:
    db.execute(
        update(IntegrationConnection)
        .where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.organization_id == org_id,
        )
        .values(
            health=ConnectionHealth.failing if category else ConnectionHealth.ok,
            last_error_category=category,
            last_checked_at=_now(),
        )
    )


def check(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> IntegrationConnection:
    """Connects and logs in, and sends nothing. No database connection is held meanwhile."""
    connection = _get(db, ctx, connection_id)
    _require_plan(db, ctx)
    try:
        target = target_of(connection)
    except CredentialError:
        category: str | None = "credential_unreadable"
    else:
        db.commit()
        category = probe_smtp(target)
        restore_context(db, ctx)
    record_health(db, ctx.org_id, connection_id, category)
    db.flush()
    db.refresh(connection)
    _record(db, ctx, "checked", connection)
    return connection
