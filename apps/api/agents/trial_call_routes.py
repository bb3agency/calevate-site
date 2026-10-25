"""The client's free-trial panel and its test calls (D-697).

`GET /v1/trial` is what the dashboard's Trial panel reads: days and minutes left, today's
test calls against the cap, and whether a test call can be placed now and, if not, why.
`POST /v1/trial/calls` places one test call (`agents/trial_calls.place_trial_call`).
`GET /v1/trial/calls` lists today's test calls and `GET /v1/trial/calls/{call_id}` follows
one while it runs (`agents/test_call_reads`, D-885).

No cost and no vendor name. The one number of ours is the shared trial number a placed
call rings from (D-885: the owner asked where the call came from); the person rung is
never echoed back.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.test_call_reads import TestCallOut, read_test_call, recent_test_calls
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
CallReader = Annotated[Principal, Depends(requires("calls:read"))]


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
    #: Our id for the placed call (`GET /v1/trial/calls/{call_id}`); null when blocked.
    call_id: UUID | None = None
    #: The shared trial number the call rings from, E.164; null when the account's own line
    #: places it, whose number the engine picks.
    caller_number: str | None = None


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
        call_id=result.call_id,
        caller_number=result.caller_number,
    )


@router.get(
    "/calls",
    response_model=list[TestCallOut],
    openapi_extra=permission_meta("calls:read"),
    summary="Today's test calls, newest first, at most three",
)
async def list_test_calls(session: Session, principal: CallReader) -> list[TestCallOut]:
    assert principal.tenant_id is not None
    return await recent_test_calls(session, tenant_id=principal.tenant_id)


@router.get(
    "/calls/{call_id}",
    response_model=TestCallOut,
    openapi_extra=permission_meta("calls:read"),
    summary="One test call's status, asked of the voice platform while it runs",
)
async def get_test_call(call_id: UUID, session: Session, principal: CallReader) -> TestCallOut:
    assert principal.tenant_id is not None
    return await read_test_call(session, tenant_id=principal.tenant_id, call_id=call_id)


__all__ = ["router"]
