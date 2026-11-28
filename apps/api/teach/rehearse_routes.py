"""Client-realm routes for a campaign's and an inbound line's Script tab: Rehearse (W3.2), a
text chat with the holder's saved script, and What it is told (W3.15), the owner's part of
the prompt, read-only.

A rehearsal line spends on the client's AI allowance the way the agent chat does (founder
decision 5), so it takes the holder's test-call permission (`leads:dispatch`, a campaign's
and a line's alike) and the view-as gate for AI help. Nothing is written but the test
holder's republish, which is the same publish a test call makes; no audit row, as the agent
chat writes none.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.owner_view import holder_told
from apps.api.core.auth import assert_view_as_may, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Strict
from apps.api.teach import try_chat

router = APIRouter(tags=["rehearse"])

Session = Annotated[AsyncSession, Depends(db)]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
CampaignReader = Annotated[Principal, Depends(requires("leads:read"))]
LineReader = Annotated[Principal, Depends(requires("agents:read"))]


class RehearseIn(Strict):
    message: str = Field(min_length=1, max_length=try_chat.MAX_MESSAGE_CHARS)
    #: The `session` a previous reply answered with, to continue the same rehearsal.
    session: str | None = Field(default=None, max_length=200)


class RehearsedActionOut(Strict):
    #: What the agent did, in the owner's words ("Would book a call-back for 5 PM").
    said: str
    #: False for every tool that acts on a call: none of them ran.
    ran: bool


class ReplyFlagOut(Strict):
    kind: str
    reason: str
    #: A line of the script can cause it, so the script can fix it.
    in_script: bool


class RehearseOut(Strict):
    session: str
    reply: str
    cut_short: bool
    actions: list[RehearsedActionOut]
    flags: list[ReplyFlagOut]
    #: "saved": the saved script on its test setup; "live": what callers hear now.
    runs: Literal["saved", "live"]
    cost_note: str


class ToldOut(Strict):
    #: The owner's part of what the agent is told; null while there is no saved script.
    told: str | None


async def _rehearse(
    session: AsyncSession,
    principal: Principal,
    kind: try_chat.HolderKind,
    holder_id: UUID,
    payload: RehearseIn,
) -> RehearseOut:
    assert principal.tenant_id is not None
    assert_view_as_may(principal, "billing.ai_assist")
    done = await try_chat.rehearse(
        session,
        tenant_id=principal.tenant_id,
        kind=kind,
        holder_id=holder_id,
        message=payload.message,
        chat_session=payload.session,
    )
    return RehearseOut(
        session=done.session,
        reply=done.reply,
        cut_short=done.cut_short,
        actions=[RehearsedActionOut(said=a.said, ran=a.ran) for a in done.actions],
        flags=[
            ReplyFlagOut(kind=f.kind, reason=f.reason, in_script=f.in_script) for f in done.flags
        ],
        runs=done.runs,
        cost_note=try_chat.REHEARSE_COST_NOTE,
    )


@router.post(
    "/v1/campaigns/{campaign_id}/rehearse",
    response_model=RehearseOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Type as a caller would, and hear how the campaign's saved script answers",
)
async def rehearse_campaign(
    campaign_id: UUID, payload: RehearseIn, session: Session, principal: Dispatcher
) -> RehearseOut:
    return await _rehearse(session, principal, "campaign", campaign_id, payload)


@router.post(
    "/v1/inbound-lines/{line_id}/rehearse",
    response_model=RehearseOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Type as a caller would, and hear how the line's saved script answers",
)
async def rehearse_line(
    line_id: UUID, payload: RehearseIn, session: Session, principal: Dispatcher
) -> RehearseOut:
    return await _rehearse(session, principal, "line", line_id, payload)


@router.get(
    "/v1/campaigns/{campaign_id}/script/told",
    response_model=ToldOut,
    openapi_extra=permission_meta("leads:read"),
    summary="What the campaign's agent is told from its saved script (the owner's part only)",
)
async def campaign_told(campaign_id: UUID, session: Session, principal: CampaignReader) -> ToldOut:
    assert principal.tenant_id is not None
    return ToldOut(
        told=await holder_told(
            session, kind="campaign", tenant_id=principal.tenant_id, holder_id=campaign_id
        )
    )


@router.get(
    "/v1/inbound-lines/{line_id}/script/told",
    response_model=ToldOut,
    openapi_extra=permission_meta("agents:read"),
    summary="What the line's agent is told from its saved script (the owner's part only)",
)
async def line_told(line_id: UUID, session: Session, principal: LineReader) -> ToldOut:
    assert principal.tenant_id is not None
    return ToldOut(
        told=await holder_told(
            session, kind="line", tenant_id=principal.tenant_id, holder_id=line_id
        )
    )


__all__ = ["router"]
