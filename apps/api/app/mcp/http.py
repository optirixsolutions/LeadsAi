"""The MCP server for outside clients: `python -m app.mcp.http`.

Requires a bearer token on every request, and identity comes only from that token. It binds to
localhost by default; exposing it further needs TLS in front of it. See docs/DEPLOYMENT.md.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from sqlalchemy import select, update

from app.core.config import get_settings, validate_worker_runtime
from app.core.db import get_sessionmaker
from app.core.security import token_digest
from app.mcp.registry import Identity
from app.mcp.server import build_server
from app.models import McpToken, TokenScope
from app.observability.logging import configure_logging
from app.services.token_service import TOKEN_PREFIX

_LAST_USED_RESOLUTION = timedelta(minutes=5)


def _verify(token: str) -> AccessToken | None:
    now = datetime.now(UTC)
    with get_sessionmaker()() as db:
        row = db.scalar(
            select(McpToken).where(
                McpToken.token_hash == token_digest(token),
                McpToken.revoked_at.is_(None),
                McpToken.expires_at > now,
            )
        )
        if row is None:
            return None
        if row.last_used_at is None or row.last_used_at < now - _LAST_USED_RESOLUTION:
            db.execute(update(McpToken).where(McpToken.id == row.id).values(last_used_at=now))
            db.commit()
        return AccessToken(
            token=token,
            client_id=str(row.id),
            scopes=[row.scope.value],
            expires_at=int(row.expires_at.timestamp()),
            subject=str(row.user_id),
            claims={"org_id": str(row.organization_id)},
        )


class TokenAuth(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith(TOKEN_PREFIX):
            return None  # Spares the database from traffic that cannot be a token of ours.
        return await asyncio.to_thread(_verify, token)


def _identity() -> Identity:
    access = get_access_token()
    if access is None or access.subject is None or not access.claims:
        raise PermissionError("No verified token on this request")
    return Identity(
        org_id=uuid.UUID(str(access.claims["org_id"])),
        user_id=uuid.UUID(access.subject),
        scope=TokenScope(access.scopes[0]),
        token_id=uuid.UUID(access.client_id),
    )


def create_http_app(public_url: str) -> Any:
    """`public_url` is the address clients use. Only requests naming that host are served, which
    blocks DNS rebinding against a server on someone's own machine."""
    parts = urlsplit(public_url)
    host = parts.netloc
    server = build_server(
        _identity,
        get_sessionmaker(),
        token_verifier=TokenAuth(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(public_url),
            resource_server_url=AnyHttpUrl(public_url),
            # Our tokens are opaque and name no resource; they are checked against the database.
            validate_token_resource=False,
        ),
    )
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host],
            allowed_origins=[f"{parts.scheme}://{host}"],
        ),
    )


def main() -> None:
    settings = get_settings()
    validate_worker_runtime(settings)
    configure_logging(settings.log_level, f"{settings.service_name}-mcp", settings.log_json)
    public_url = settings.mcp_public_url or f"http://127.0.0.1:{settings.mcp_port}"
    if settings.environment in ("staging", "production") and not public_url.startswith("https://"):
        raise RuntimeError("SALESIQ_MCP_PUBLIC_URL must be HTTPS outside development")
    uvicorn.run(create_http_app(public_url), host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
