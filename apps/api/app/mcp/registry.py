"""Tool execution. Every call, from any client or agent, passes through `execute`.

A tool call is a request, never an authorization. The caller's identity comes from the server
(a verified token, or the workflow that started an agent) and never from the arguments, so a
model cannot name another tenant or user. Authority is looked up again on every call, and every
call is logged, including the ones that are refused.
"""

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import OrgContext, worker_context
from app.core.db import set_tenant_context
from app.core.errors import AccessLostError, AppError, ForbiddenError
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import RateLimitedError, get_rate_limiter
from app.models import TokenScope, ToolCall, ToolCallStatus

log = logging.getLogger(__name__)

SideEffect = Literal["read", "write"]
CALLS_PER_MINUTE = 240
DEFAULT_TIMEOUT_S = 10.0
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,80}")


@dataclass(frozen=True)
class Identity:
    """Who is calling, as established by the server."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    scope: TokenScope = TokenScope.read
    token_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    # Agents get a short list of tools, and a lead-bound agent can only touch its own lead.
    allowed_tools: frozenset[str] | None = None
    bound_lead_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission: Permission
    side_effect: SideEffect
    handler: Callable[[Session, OrgContext, Any], BaseModel]
    # The argument naming a lead, checked against an agent's bound lead.
    lead_field: str | None = None
    # Arguments safe to keep in the audit log: IDs and enums, never free text.
    audit_fields: tuple[str, ...] = ()
    # Texts in the output that an agent may cite, by a stable identifier.
    sources: Callable[[Any], dict[str, str]] | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    # Shares a counter with the REST route that does the same thing.
    limit_key: str | None = None
    limit_per_minute: int | None = None


@dataclass
class ToolResult:
    status: ToolCallStatus
    output: dict[str, Any] | None = None
    sources: dict[str, str] = field(default_factory=dict)
    error_category: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == ToolCallStatus.ok


class _RefusedError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def _authorize(spec: ToolSpec, identity: Identity, ctx: OrgContext) -> None:
    if identity.allowed_tools is not None and spec.name not in identity.allowed_tools:
        raise _RefusedError("tool_not_allowed", f"This agent may not use {spec.name}")
    if spec.side_effect == "write" and identity.scope != TokenScope.write:
        raise _RefusedError("read_only", f"{spec.name} changes data, and this access is read-only")
    if not has_permission(ctx.role, spec.permission):
        raise _RefusedError("permission_denied", f"Your role does not allow {spec.name}")


def _check_binding(spec: ToolSpec, identity: Identity, args: BaseModel) -> None:
    """A lead-bound agent works on its lead. Leaving the field out means that lead."""
    if identity.bound_lead_id is None or spec.lead_field is None:
        return
    value = getattr(args, spec.lead_field)
    if value is None:
        setattr(args, spec.lead_field, identity.bound_lead_id)
    elif value != identity.bound_lead_id:
        raise _RefusedError(
            "outside_bound_lead", "This agent may only work on the lead it was given"
        )


def _check_limit(spec: ToolSpec, identity: Identity) -> None:
    """The same limits as the matching REST routes, so MCP is not a way around them."""
    if spec.limit_key is None or spec.limit_per_minute is None:
        return
    org_wide = spec.limit_key == "workflow"
    key = f"{spec.limit_key}:{identity.org_id}"
    get_rate_limiter().hit(key if org_wide else f"{key}:{identity.user_id}", spec.limit_per_minute)


def _write_log(
    db: Session,
    identity: Identity,
    spec_name: str,
    side_effect: str,
    status: ToolCallStatus,
    arguments: dict[str, Any],
    started: float,
    category: str | None,
) -> None:
    db.add(
        ToolCall(
            organization_id=identity.org_id,
            actor_user_id=identity.user_id,
            workflow_run_id=identity.workflow_run_id,
            token_id=identity.token_id,
            tool=spec_name[:80],
            side_effect=side_effect,
            status=status,
            arguments=arguments,
            error_category=category[:40] if category else None,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    )


def _log_name(name: str) -> str:
    """A tool name can be model-chosen text. Only something shaped like a name is recorded."""
    return name if _TOOL_NAME.fullmatch(name) else "<invalid-name>"


def _audit_arguments(spec: ToolSpec, args: BaseModel) -> dict[str, Any]:
    """Validated values only, so whatever a caller sent never reaches the log as free text."""
    values = {k: getattr(args, k) for k in spec.audit_fields}
    return {k: str(v)[:200] for k, v in values.items() if v is not None}


def execute(
    specs: dict[str, ToolSpec],
    identity: Identity,
    name: str,
    raw_args: dict[str, Any],
    session_factory: sessionmaker[Session],
) -> ToolResult:
    started = time.perf_counter()
    spec = specs.get(name)
    side_effect = spec.side_effect if spec else "unknown"
    logged_name = _log_name(name)

    def failed(
        db: Session,
        status: ToolCallStatus,
        category: str,
        message: str,
        kept: dict[str, Any] | None = None,
    ) -> ToolResult:
        return _failed(
            db, identity, logged_name, side_effect, kept or {}, started, status, category, message
        )

    with session_factory() as db:
        kept: dict[str, Any] = {}
        try:
            if spec is None:
                raise _RefusedError("unknown_tool", "There is no such tool")
            get_rate_limiter().hit(f"tool:{identity.org_id}:{identity.user_id}", CALLS_PER_MINUTE)
            ctx = worker_context(db, identity.org_id, identity.user_id)
            _authorize(spec, identity, ctx)
            try:
                args = spec.input_model.model_validate(raw_args)
            except ValidationError as exc:
                fields = sorted({str(e["loc"][0])[:40] for e in exc.errors() if e["loc"]})
                detail = ", ".join(f for f in fields if _TOOL_NAME.fullmatch(f))
                return failed(
                    db,
                    ToolCallStatus.invalid,
                    "invalid",
                    f"Invalid arguments: {detail or 'the request'}",
                )
            kept = _audit_arguments(spec, args)
            _check_binding(spec, identity, args)
            _check_limit(spec, identity)
            db.execute(text(f"SET LOCAL statement_timeout = {int(spec.timeout_s * 1000)}"))
            output = spec.handler(db, ctx, args)
            checked = spec.output_model.model_validate(output.model_dump(mode="json"))
            result = ToolResult(
                ToolCallStatus.ok,
                output=checked.model_dump(mode="json"),
                sources=spec.sources(checked) if spec.sources else {},
            )
            _write_log(
                db, identity, logged_name, side_effect, ToolCallStatus.ok, kept, started, None
            )
            db.commit()
            return result
        except RateLimitedError as exc:
            # No row: a flood of refused calls must not be able to grow the log without limit.
            db.rollback()
            log.warning("tool_rate_limited", extra={"tool": logged_name})
            return ToolResult(ToolCallStatus.denied, error_category=exc.code, message=exc.message)
        except _RefusedError as exc:
            return failed(db, ToolCallStatus.denied, exc.category, exc.message, kept)
        except (AccessLostError, ForbiddenError) as exc:
            return failed(db, ToolCallStatus.denied, exc.code, exc.message, kept)
        except AppError as exc:
            return failed(db, ToolCallStatus.error, exc.code, exc.message, kept)
        except Exception as exc:
            log.warning(
                "tool_failed", extra={"tool": logged_name, "error_type": type(exc).__name__}
            )
            return failed(
                db,
                ToolCallStatus.error,
                "internal_error",
                "This tool failed unexpectedly",
                kept,
            )


def _failed(
    db: Session,
    identity: Identity,
    name: str,
    side_effect: str,
    kept: dict[str, Any],
    started: float,
    status: ToolCallStatus,
    category: str,
    message: str,
) -> ToolResult:
    """Undo whatever the tool did, then keep a record of the attempt. If the record itself cannot
    be written, the caller still gets its answer and the gap shows up in the logs."""
    try:
        db.rollback()
        set_tenant_context(db, user_id=identity.user_id, org_id=identity.org_id)
        _write_log(db, identity, name, side_effect, status, kept, started, category)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error("tool_log_failed", extra={"tool": name, "error_type": type(exc).__name__})
    return ToolResult(status, error_category=category, message=message)
