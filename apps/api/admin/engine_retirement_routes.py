"""Run the adoption job (D-1019) for one client, from its voice workspace page.

`POST /v1/admin/engine-workspaces/tenants/{tenant_id}/agent-engine-retirement` with
`{"dry_run": true}` reports, per agent still holding an engine agent of its own, what the job
would do: which line or campaign adopts it, whether it is retired, or why it is held, and the
running script tests it would conclude first. `{"dry_run": false}` does it, behind step-up
(`X-Confirm-Action: retire_agent_engine_agents:<tenant_id>`): it changes what answers a
client's numbers. Every run is audited; a dry run is a recorded tenant read.

Admin realm: vendor names may appear here.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.agents import engine_retirement
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/engine-workspaces", tags=["admin"])

Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
ConfirmAction = Annotated[str | None, Header(alias="X-Confirm-Action")]


def retirement_confirmation(tenant_id: UUID) -> str:
    """The step-up string for a real run, bound to the client."""
    return f"retire_agent_engine_agents:{tenant_id}"


class RetirementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: True: report what would happen and change nothing.
    dry_run: bool = True


class AgentRetirementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    outcome: Literal["adopted_line", "adopted_campaign", "retired", "held", "waiting"]
    #: The inbound line or campaign that adopts the engine agent.
    holder_id: UUID | None
    #: Our reason code for a held or waiting agent (`runbooks/alarm-index.md`,
    #: `agent_engine_agent_held`).
    reason: str | None
    #: Running script tests concluded first, keeping the control.
    experiments_concluded: list[UUID]


class RetirementRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    dry_run: bool
    agents: list[AgentRetirementOut]


@router.post(
    "/tenants/{tenant_id}/agent-engine-retirement",
    response_model=RetirementRunOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Give this client's agents' own engine agents to their lines and campaigns",
    description=(
        "Per agent still holding an engine agent: the one draft line with numbers, or the "
        "one running campaign, that uses it adopts it in place (read back like any "
        "publish); one nothing uses is retired; anything else is held with a reason. "
        "`dry_run` (the default) changes nothing. A real run needs step-up and is refused "
        "while `agents_hold_engine_agent` is on."
    ),
)
async def run_retirement(
    tenant_id: UUID,
    payload: RetirementIn,
    session: Annotated[AsyncSession, Depends(admin_db)],
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> RetirementRunOut:
    if not payload.dry_run:
        step_up.require(x_confirm_action, retirement_confirmation(tenant_id))
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
    run = await engine_retirement.retire_for_tenant(tenant_id=tenant_id, dry_run=payload.dry_run)
    out = RetirementRunOut(
        tenant_id=tenant_id,
        dry_run=run.dry_run,
        agents=[
            AgentRetirementOut(
                agent_id=agent.agent_id,
                outcome=agent.outcome,
                holder_id=agent.holder_id,
                reason=agent.reason,
                experiments_concluded=list(agent.experiments_concluded),
            )
            for agent in run.agents
        ],
    )
    if run.dry_run:
        await record_admin_tenant_read(
            session, request=request, principal=principal, tenant_id=tenant_id
        )
        return out
    counts: dict[str, str] = {}
    for agent in run.agents:
        counts[agent.outcome] = str(int(counts.get(agent.outcome, "0")) + 1)
    async with tenant_session(tenant_id) as scoped:
        await write_audit(
            scoped,
            action="agent.engine_agents_retired",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"agents": str(len(run.agents)), **counts},
        )
    return out


__all__ = ["retirement_confirmation", "router"]
