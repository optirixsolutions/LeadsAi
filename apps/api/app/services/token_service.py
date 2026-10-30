"""Personal MCP tokens. The secret is shown once and only its digest is stored."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import OrgContext
from app.core.errors import ForbiddenError, NotFoundError
from app.core.rate_limit import RateLimitedError
from app.core.security import token_digest, verify_password
from app.models import McpToken, TokenScope
from app.services import audit

TOKEN_PREFIX = "siq_"  # noqa: S105
MAX_ACTIVE_PER_USER = 10


def _now() -> datetime:
    return datetime.now(UTC)


def list_tokens(db: Session, ctx: OrgContext) -> list[McpToken]:
    return list(
        db.scalars(
            select(McpToken)
            .where(McpToken.organization_id == ctx.org_id, McpToken.user_id == ctx.user_id)
            # Active ones first, so a long history cannot push one out of reach of revocation.
            .order_by(McpToken.revoked_at.is_not(None), McpToken.created_at.desc())
            .limit(50)
        )
    )


def create_token(
    db: Session,
    ctx: OrgContext,
    *,
    name: str,
    scope: TokenScope,
    expires_in_days: int,
    current_password: str | None = None,
) -> tuple[McpToken, str]:
    # A stolen session must not be able to mint lasting write access.
    if scope == TokenScope.write and not verify_password(
        current_password or "", ctx.principal.user.password_hash
    ):
        raise ForbiddenError(
            "Enter your current password to create a token that can write",
            code="password_required",
        )
    active = db.scalar(
        select(func.count())
        .select_from(McpToken)
        .where(
            McpToken.organization_id == ctx.org_id,
            McpToken.user_id == ctx.user_id,
            McpToken.revoked_at.is_(None),
            McpToken.expires_at > _now(),
        )
    )
    if (active or 0) >= MAX_ACTIVE_PER_USER:
        raise RateLimitedError("You have too many active tokens. Revoke one first.")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = McpToken(
        organization_id=ctx.org_id,
        user_id=ctx.user_id,
        name=name,
        token_hash=token_digest(secret),
        scope=scope,
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    db.add(token)
    db.flush()
    audit.record(
        db,
        "mcp_token.created",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="mcp_token",
        target_id=token.id,
        data={"scope": scope.value, "expires_in_days": expires_in_days},
    )
    return token, secret


def revoke_token(db: Session, ctx: OrgContext, token_id: uuid.UUID) -> None:
    token = db.scalar(
        select(McpToken).where(
            McpToken.id == token_id,
            McpToken.organization_id == ctx.org_id,
            McpToken.user_id == ctx.user_id,
        )
    )
    if token is None:
        raise NotFoundError("Token not found")
    if token.revoked_at is None:
        token.revoked_at = _now()
        audit.record(
            db,
            "mcp_token.revoked",
            org_id=ctx.org_id,
            actor_id=ctx.user_id,
            target_type="mcp_token",
            target_id=token.id,
        )
