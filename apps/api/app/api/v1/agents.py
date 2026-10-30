"""Agent runs, the tool catalog, and MCP tokens (all org-scoped)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.agents.roles import AGENTS
from app.core.auth import DbDep, OrgContext, require
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import get_rate_limiter
from app.mcp.tools import CATALOG
from app.models import AgentRole, AgentRun
from app.schemas.agent import (
    AgentInfo,
    AgentRunDetail,
    AgentRunOut,
    AgentStart,
    CatalogOut,
    TokenCreate,
    TokenCreated,
    TokenOut,
    ToolCallOut,
    ToolInfo,
)
from app.services import agent_service, token_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["agents"])

Read = Annotated[OrgContext, Depends(require(Permission.workflows_read))]
Run = Annotated[OrgContext, Depends(require(Permission.workflows_run))]

STARTS_PER_MINUTE = 10
TOKENS_PER_MINUTE = 10


@router.get("/agents", response_model=CatalogOut)
def catalog(_: Read) -> CatalogOut:
    return CatalogOut(
        agents=[
            AgentInfo(
                role=a.role,
                label=a.label,
                description=a.description,
                tools=sorted(a.tools),
                needs_lead=a.needs_lead,
                max_model_turns=a.max_model_turns,
                max_tool_calls=a.max_tool_calls,
            )
            for a in AGENTS.values()
        ],
        tools=[
            ToolInfo(
                name=t.name,
                description=t.description,
                side_effect=t.side_effect,
                permission=t.permission.value,
            )
            for t in CATALOG.values()
        ],
    )


def _hide_rejected(out: AgentRunOut, agent: AgentRun, ctx: OrgContext) -> None:
    """Removed claims may be hostile, so only reviewers receive the wording."""
    if not has_permission(ctx.role, Permission.intelligence_review):
        for claim in out.rejected_claims:
            claim.text = None


@router.post("/agents/{role}/runs", status_code=202, response_model=AgentRunOut)
def start_agent(role: AgentRole, body: AgentStart, ctx: Run, db: DbDep) -> AgentRunOut:
    get_rate_limiter().hit(f"workflow:{ctx.org_id}", STARTS_PER_MINUTE)
    agent = agent_service.start(db, ctx, role, body.lead_id)
    out = AgentRunOut.model_validate(agent)
    db.commit()
    return out


@router.get("/agent-runs", response_model=list[AgentRunOut])
def list_agent_runs(ctx: Read, db: DbDep, lead_id: uuid.UUID | None = None) -> list[AgentRunOut]:
    rows = agent_service.list_runs(db, ctx, lead_id=lead_id)
    out = []
    for agent in rows:
        item = AgentRunOut.model_validate(agent)
        _hide_rejected(item, agent, ctx)
        out.append(item)
    db.commit()
    return out


@router.get("/agent-runs/{agent_id}", response_model=AgentRunDetail)
def get_agent_run(agent_id: uuid.UUID, ctx: Read, db: DbDep) -> AgentRunDetail:
    agent = agent_service.get_run(db, ctx, agent_id)
    base = AgentRunOut.model_validate(agent)
    _hide_rejected(base, agent, ctx)
    calls = [ToolCallOut.model_validate(c) for c in agent_service.tool_calls(db, ctx, agent)]
    out = AgentRunDetail(**base.model_dump(), tool_calls=calls, sources=agent.sources)
    db.commit()
    return out


# Any member may hold a token: it can never do more than their role allows at the time of a call.
@router.get("/mcp-tokens", response_model=list[TokenOut])
def list_tokens(ctx: Read, db: DbDep) -> list[TokenOut]:
    return [TokenOut.model_validate(t) for t in token_service.list_tokens(db, ctx)]


@router.post("/mcp-tokens", status_code=201, response_model=TokenCreated)
def create_token(body: TokenCreate, ctx: Read, db: DbDep) -> TokenCreated:
    get_rate_limiter().hit(f"mcp-token:{ctx.user_id}", TOKENS_PER_MINUTE)
    token, secret = token_service.create_token(
        db,
        ctx,
        name=body.name,
        scope=body.scope,
        expires_in_days=body.expires_in_days,
        current_password=body.current_password,
    )
    out = TokenCreated(**TokenOut.model_validate(token).model_dump(), secret=secret)
    db.commit()
    return out


@router.delete("/mcp-tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, ctx: Read, db: DbDep) -> Response:
    token_service.revoke_token(db, ctx, token_id)
    db.commit()
    return Response(status_code=204)
