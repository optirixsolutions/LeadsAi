"""Integrations, provider webhooks, usage, and the development-only billing adapter."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.auth import DbDep, OrgContext, require
from app.core.config import get_settings
from app.core.errors import AppError, ForbiddenError
from app.core.permissions import Permission
from app.core.rate_limit import get_rate_limiter
from app.integrations.dispatch import unavailable_reason
from app.models import IntegrationConnection, Subscription
from app.schemas.integration import (
    ConnectionCreated,
    ConnectionOut,
    DevPlanChange,
    IntegrationsOut,
    ModelServerHealth,
    PlanOut,
    SmtpConnectionCreate,
    SmtpConnectionUpdate,
    UsageMetric,
    UsageOut,
    WebhookResult,
    WebhookSecretOut,
)
from app.services import audit, integration_service, quota_service, webhook_service
from app.services.brief_service import get_registry

router = APIRouter(prefix="/organizations/{org_id}", tags=["integrations"])
public_router = APIRouter(tags=["integrations"])

Read = Annotated[OrgContext, Depends(require(Permission.integrations_read))]
Manage = Annotated[OrgContext, Depends(require(Permission.integrations_manage))]
UsageRead = Annotated[OrgContext, Depends(require(Permission.usage_read))]
Billing = Annotated[OrgContext, Depends(require(Permission.billing_manage))]

BAD_WEBHOOKS_PER_MINUTE = 30
CHECKS_PER_MINUTE = 6


def _out(c: IntegrationConnection) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        kind=c.kind,
        name=c.name,
        host=c.config.get("host"),
        port=c.config.get("port"),
        starttls=c.config.get("starttls"),
        username=c.config.get("username"),
        has_password=bool(c.encrypted_password),
        health=c.health,
        last_error_category=c.last_error_category,
        last_checked_at=c.last_checked_at,
        created_at=c.created_at,
        webhook_path=f"/api/v1/webhooks/email/{c.organization_id}/{c.id}",
    )


@router.get("/integrations", response_model=IntegrationsOut)
def list_integrations(ctx: Read, db: DbDep) -> IntegrationsOut:
    plan = quota_service.plan_for(db, ctx.org_id)
    connections = integration_service.list_connections(db, ctx)
    # Whether a model can run, and nothing about where it is: a provider's error can name hosts.
    models = [
        ModelServerHealth(model_key=m.key, available=m.available) for m in get_registry().status()
    ]
    return IntegrationsOut(
        connections=[_out(c) for c in connections],
        models=models,
        server_blocker=unavailable_reason(),
        integrations_included=plan.integrations,
    )


@router.post("/integrations/email", status_code=201, response_model=ConnectionCreated)
def connect_email(body: SmtpConnectionCreate, ctx: Manage, db: DbDep) -> ConnectionCreated:
    connection, secret = integration_service.create_smtp(
        db,
        ctx,
        name=body.name,
        host=body.host,
        port=body.port,
        starttls=body.starttls,
        username=body.username,
        password=body.password,
    )
    db.flush()
    db.refresh(connection)
    out = ConnectionCreated(**_out(connection).model_dump(), webhook_secret=secret)
    db.commit()
    return out


@router.patch("/integrations/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: uuid.UUID, body: SmtpConnectionUpdate, ctx: Manage, db: DbDep
) -> ConnectionOut:
    connection = integration_service.update_smtp(
        db, ctx, connection_id, body.model_dump(exclude_unset=True)
    )
    out = _out(connection)
    db.commit()
    return out


@router.delete("/integrations/{connection_id}", status_code=204)
def remove_connection(connection_id: uuid.UUID, ctx: Manage, db: DbDep) -> Response:
    integration_service.remove(db, ctx, connection_id)
    db.commit()
    return Response(status_code=204)


@router.post("/integrations/{connection_id}/check", response_model=ConnectionOut)
def check_connection(connection_id: uuid.UUID, ctx: Manage, db: DbDep) -> ConnectionOut:
    get_rate_limiter().hit(f"integration-check:{ctx.org_id}", CHECKS_PER_MINUTE)
    connection = integration_service.check(db, ctx, connection_id)
    out = _out(connection)
    db.commit()
    return out


@router.post("/integrations/{connection_id}/rotate-webhook-secret", response_model=WebhookSecretOut)
def rotate_secret(connection_id: uuid.UUID, ctx: Manage, db: DbDep) -> WebhookSecretOut:
    secret = integration_service.rotate_webhook_secret(db, ctx, connection_id)
    db.commit()
    return WebhookSecretOut(webhook_secret=secret)


def _development_billing() -> bool:
    return get_settings().environment in ("development", "test")


@router.get("/usage", response_model=UsageOut)
def usage(ctx: UsageRead, db: DbDep) -> UsageOut:
    view = quota_service.usage_view(db, ctx.org_id)
    plan = view["plan"]
    return UsageOut(
        plan=PlanOut(key=plan.key, label=plan.label, integrations=plan.integrations),
        source=view["source"],
        metrics=[UsageMetric(**m) for m in view["metrics"]],
        estimated_cost_usd=view["estimated_cost_usd"],
        plans=[
            PlanOut(key=p.key, label=p.label, integrations=p.integrations)
            for p in quota_service.all_plans().values()
        ],
        development_billing=_development_billing(),
    )


@router.post("/billing/development-plan", response_model=UsageOut)
def change_plan(body: DevPlanChange, ctx: Billing, db: DbDep) -> UsageOut:
    """Stands in for a payment provider, and refuses to exist anywhere but development."""
    if not _development_billing():
        raise ForbiddenError("Plans cannot be changed here", code="billing_unavailable")
    if body.plan not in quota_service.all_plans():
        raise AppError("There is no such plan", code="unknown_plan")
    statement = pg_insert(Subscription).values(
        organization_id=ctx.org_id,
        plan_key=body.plan,
        source="development",
        updated_by_user_id=ctx.user_id,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["organization_id"],
            set_={"plan_key": body.plan, "updated_by_user_id": ctx.user_id},
        )
    )
    audit.record(
        db,
        "billing.development_plan_changed",
        org_id=ctx.org_id,
        actor_id=ctx.user_id,
        target_type="organization",
        target_id=ctx.org_id,
        data={"plan": body.plan},
    )
    out = usage(ctx, db)
    db.commit()
    return out


async def _limited_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > webhook_service.MAX_BODY_BYTES:
            raise AppError("This event is too large", code="too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@public_router.post("/webhooks/email/{org_id}/{connection_id}", response_model=WebhookResult)
def email_webhook(
    org_id: uuid.UUID,
    connection_id: uuid.UUID,
    request: Request,
    db: DbDep,
    body: Annotated[bytes, Depends(_limited_body)],
    timestamp: Annotated[str | None, Header(alias="x-salesiq-timestamp", max_length=20)] = None,
    signature: Annotated[str | None, Header(alias="x-salesiq-signature", max_length=100)] = None,
) -> WebhookResult:
    """Public on purpose: a provider has no session. Only the signature lets anything through."""
    try:
        result = webhook_service.receive(
            db, org_id, connection_id, timestamp=timestamp, signature=signature, body=body
        )
    except webhook_service.WebhookRejectedError:
        # Counted only when it fails, so that a flood of forgeries cannot stop real events.
        db.rollback()
        ip = request.client.host if request.client else "unknown"
        get_rate_limiter().hit(f"webhook-rejected:{ip}", BAD_WEBHOOKS_PER_MINUTE)
        raise
    db.commit()
    return WebhookResult(result=result)
