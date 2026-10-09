"""The client's free-trial panel and its test calls (D-697).

`GET /v1/trial` is what the dashboard's Trial panel reads: days and minutes left, today's
test calls against the cap, and whether a test call can be placed now and, if not, why.
`POST /v1/trial/calls` places one test call (`agents/trial_calls.place_trial_call`).

Dates, counts and sentences only; no cost, no number of ours, no vendor name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.trial_calls import (
    NOT_READY_REASON,
    place_trial_call,
    trial_calling_ready,
)
from apps.api.compliance.outbound_pledge import pledge_blocker
from apps.api.compliance.trial_access import read_trial_access
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


class TrialPanelOut(Strict):
    """The trial as its own client reads it. `on_trial` false means none of the rest
    applies: the account has paid, or was never given a trial."""

    on_trial: bool
    #: `active`, `expired` or `stopped`; null when not on a trial.
    status: str | None = None
    ends_at: datetime | None = None
    days_remaining: int | None = None
    #: The free test-call minutes, used and left. Null on a trial with no minutes cap.
    free_minutes: int | None = None
    minutes_used: int = 0
    minutes_left: int | None = None
    calls_today: int = 0
    daily_cap: int = 0
    #: The longest one test call may run, in seconds.
    max_call_seconds: int = 0
    #: Whether the no-cold-calls pledge is accepted; a test call needs it.
    pledge_accepted: bool = False
    #: Whether a test call can be placed now, and the sentence that says why not.
    can_call: bool = False
    blocked_reason: str | None = None


class TrialCallIn(Strict):
    agent_id: UUID
    #: The number to ring, as the client typed it: an Indian number only.
    number: str = Field(min_length=8, max_length=20)


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
    now = datetime.now(UTC)
    access = await read_trial_access(session, tenant_id=principal.tenant_id, at=now)
    if access is None:
        return TrialPanelOut(on_trial=False)
    unpledged = await pledge_blocker(session, tenant_id=principal.tenant_id)
    blocked = access.blocker
    reason: str | None = None
    if not trial_calling_ready():
        reason = NOT_READY_REASON
    elif blocked is not None:
        reason = blocked[1]
    elif unpledged is not None:
        reason = unpledged[1]
    return TrialPanelOut(
        on_trial=True,
        status=access.trial.status,
        ends_at=access.trial.ends_at,
        days_remaining=access.trial.days_remaining(at=now),
        free_minutes=access.trial.free_minutes,
        minutes_used=access.minutes_used,
        minutes_left=access.minutes_left,
        calls_today=access.calls_today,
        daily_cap=access.daily_cap,
        max_call_seconds=access.call_seconds,
        pledge_accepted=unpledged is None,
        can_call=reason is None,
        blocked_reason=reason,
    )


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
    result = await place_trial_call(
        session,
        principal=principal,
        agent_id=payload.agent_id,
        number=payload.number,
        idempotency_key=idem_key,
        ip=client_request_ip(request),
    )
    return TrialCallOut(
        status=result.status,
        call_handle=result.call_handle,
        blocked_reason=result.blocked_reason,
        blocked_rule=result.blocked_rule,
    )


__all__ = ["router"]
