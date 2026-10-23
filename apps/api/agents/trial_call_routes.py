"""The client's free-trial panel and its test calls (D-697).

`GET /v1/trial` is what the dashboard's Trial panel reads: days and minutes left, today's
test calls against the cap, and whether a test call can be placed now and, if not, why.
`POST /v1/trial/calls` places one test call (`agents/trial_calls.place_trial_call`).

Dates, counts and sentences only; no cost, no number of ours, no vendor name.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.trial_calls import attest_own_number, place_trial_call
from apps.api.agents.trial_panel import TrialPanelOut
from apps.api.agents.trial_panel import read_trial_panel as build_trial_panel
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/trial", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
TrialReader = Annotated[Principal, Depends(requires("org:read"))]
TrialCaller = Annotated[Principal, Depends(requires("leads:dispatch"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrialCallIn(Strict):
    agent_id: UUID
    #: The number to ring, as the client typed it: an Indian number only.
    number: str = Field(min_length=8, max_length=20)
    #: The caller ticked "this number is mine" (D-855). Recorded in the audit log by keyed
    #: reference, never the number itself.
    number_is_mine: bool = False


class TrialCallOut(Strict):
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None


@router.get(
    "",
    response_model=TrialPanelOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's free trial: days and minutes left, and today's test calls",
)
async def read_trial_panel(session: Session, principal: TrialReader) -> TrialPanelOut:
    assert principal.tenant_id is not None
    return await build_trial_panel(session, tenant_id=principal.tenant_id)


@router.post(
    "/calls",
    response_model=TrialCallOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Place one free-trial test call to an Indian number — gated, idempotent",
)
async def create_trial_call(
    payload: TrialCallIn,
    request: Request,
    session: Session,
    principal: TrialCaller,
) -> TrialCallOut:
    assert principal.tenant_id is not None
    # A test call rings a real phone, so a repeat of one attempt must be answered, not
    # dialled again: the key is required, as on the lead call route.
    idem_key = request.headers.get("Idempotency-Key")
    if not idem_key:
        raise ProblemError(
            kind="validation",
            status=400,
            code="idempotency_key_required",
            title="A test call needs an Idempotency-Key header",
            detail="Each test call rings a real phone, so every attempt names itself.",
            remediation="Send an `Idempotency-Key` header — one fresh value per attempt.",
        )
    if payload.number_is_mine:
        await attest_own_number(
            principal=principal, number=payload.number, ip=client_request_ip(request)
        )
    result = await place_trial_call(
        session,
        principal=principal,
        agent_id=payload.agent_id,
        number=payload.number,
        idempotency_key=idem_key,
        ip=client_request_ip(request),
        own_number_attested=payload.number_is_mine,
    )
    return TrialCallOut(
        status=result.status,
        call_handle=result.call_handle,
        blocked_reason=result.blocked_reason,
        blocked_rule=result.blocked_rule,
    )


__all__ = ["router"]
