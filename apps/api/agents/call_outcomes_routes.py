"""Each agent's own call outcomes, as the Lead details screen reads and changes them (D-836).

    GET  /v1/call-outcomes                    every agent's outcomes and the AI draft's state
    PUT  /v1/agents/{agent_id}/call-outcomes  replace one agent's outcomes (owner)
    POST /v1/agents/{agent_id}/call-outcomes/draft  "Write them for me" (owner)

The draft is queued once per agent by its publish or its first call
(`agents/call_outcomes.queue_draft`), and again on the owner's request when it never ran, failed,
was skipped or died running (`request_draft`, D-841).
"""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from calevate_shared.business_outcomes import (
    LABEL_MAX,
    MAX_BUSINESS_OUTCOMES,
    MEANING_MAX,
    BusinessOutcome,
    LeadMove,
)
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_outcomes as service
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.billing.trials import trial_billing_active
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/call-outcomes", tags=["agents"])
agent_router = APIRouter(prefix="/v1/agents/{agent_id}/call-outcomes", tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]

#: `agents.models.BUSINESS_OUTCOMES_DRAFT_STATES`, which the column's CHECK holds.
DraftState = Literal["queued", "running", "done", "failed", "skipped"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallOutcomeOut(_Out):
    key: str
    label: str
    meaning: str
    #: How far a call with this outcome moves its lead: contacted, interested or hot.
    lead_status: LeadMove


class CallOutcomesAgentOut(_Out):
    id: UUID
    name: str
    direction: str
    status: str
    outcomes: list[CallOutcomeOut] = Field(max_length=MAX_BUSINESS_OUTCOMES)
    #: True while the agent reads the neutral starting set: nothing drafted or saved yet.
    starting: bool
    #: The one AI draft's state; None when none was ever queued.
    draft: DraftState | None


class CallOutcomesOut(_Out):
    max_outcomes: int
    agents: list[CallOutcomesAgentOut]


class CallOutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The key of an outcome the agent already has; omit for a new one.
    key: str | None = Field(default=None, max_length=40)
    label: str = Field(min_length=1, max_length=LABEL_MAX)
    meaning: str = Field(default="", max_length=MEANING_MAX)
    lead_status: LeadMove = "contacted"


class CallOutcomesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcomes: list[CallOutcomeIn] = Field(max_length=MAX_BUSINESS_OUTCOMES)


def _outcome_out(o: BusinessOutcome) -> CallOutcomeOut:
    return CallOutcomeOut(key=o.key, label=o.label, meaning=o.meaning, lead_status=o.lead_status)


def _agent_out(row: dict[str, object]) -> CallOutcomesAgentOut:
    return CallOutcomesAgentOut(
        id=cast(UUID, row["id"]),
        name=str(row["name"]),
        direction=str(row["direction"]),
        status=str(row["status"]),
        outcomes=[_outcome_out(o) for o in cast(list[BusinessOutcome], row["outcomes"])],
        starting=bool(row["starting"]),
        draft=cast(DraftState | None, row["draft"]),
    )


@router.get(
    "",
    response_model=CallOutcomesOut,
    openapi_extra=permission_meta("org:read"),
    summary="How each agent's calls can end for this business",
)
async def get_call_outcomes(session: Session, principal: Reader) -> CallOutcomesOut:
    assert principal.tenant_id is not None
    rows = await service.agents_with_outcomes(session)
    return CallOutcomesOut(max_outcomes=MAX_BUSINESS_OUTCOMES, agents=[_agent_out(r) for r in rows])


@agent_router.put(
    "",
    response_model=CallOutcomesAgentOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Replace one agent's call outcomes",
    description=(
        "Calls already read keep the outcome and name they were given; the next call is read "
        "against this list. A saved list is never replaced by the AI draft."
    ),
)
async def put_call_outcomes(
    agent_id: UUID,
    payload: CallOutcomesIn,
    session: Session,
    principal: Owner,
    request: Request,
) -> CallOutcomesAgentOut:
    assert principal.tenant_id is not None
    saved = await service.save_outcomes(
        session,
        agent_id=agent_id,
        items=[
            service.OutcomeDraft(
                key=i.key, label=i.label, meaning=i.meaning, lead_status=i.lead_status
            )
            for i in payload.outcomes
        ],
    )
    await write_audit(
        session,
        action="agent.call_outcomes_saved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"keys": [o.key for o in saved]},
    )
    return _agent_out(await service.agent_with_outcomes(session, agent_id))


@agent_router.post(
    "/draft",
    response_model=CallOutcomesAgentOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask AI to write one agent's call outcomes",
    description=(
        "Queues the AI draft for an agent with no outcomes of its own whose draft never ran, "
        "could not be written or was skipped. On a paying account it uses the monthly AI "
        "allowance; on a trial it is free. A list the owner saves meanwhile is never replaced."
    ),
)
async def draft_call_outcomes(
    agent_id: UUID,
    session: Session,
    principal: Owner,
    request: Request,
) -> CallOutcomesAgentOut:
    assert principal.tenant_id is not None
    current = await service.agent_with_outcomes(session, agent_id)
    if current["draft"] in ("queued", "running"):
        return _agent_out(current)
    if not current["starting"]:
        raise ProblemError.conflict(
            "call_outcomes_already_written",
            "This agent already has its own outcomes.",
            remediation="Change them here: the AI draft writes only for an agent with none.",
        )
    if not await trial_billing_active(session, tenant_id=principal.tenant_id):
        # The draft spends this account's AI allowance (D-827), so it is refused up front
        # rather than queued only to be skipped by the worker.
        assert_view_as_may(principal, "billing.ai_assist")
        await require_ai_assist(session, tenant_id=principal.tenant_id)
    if await service.request_draft(session, tenant_id=principal.tenant_id, agent_id=agent_id):
        await write_audit(
            session,
            action="agent.call_outcomes_draft_requested",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
        )
    return _agent_out(await service.agent_with_outcomes(session, agent_id))
