"""The owner's go-live guide after the first payment (D-859).

    GET  /v1/go-live                  the four steps, the agents' move, and whether it is due
    POST /v1/go-live/finish | /dismiss  done, or put aside for now

Reading is `org:read`: the move's progress is the account's own and names nothing outside it.
Finishing or putting it aside is the owner's (`org:manage`), as for "Meet your agent". Agent
names, our step states and counts only; no vendor name (D-679), no money, no personal data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.go_live import guide
from apps.api.go_live.moves import MAX_LISTED_AGENTS, AgentMoveView

router = APIRouter(prefix="/v1/go-live", tags=["go-live"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentMoveOut(Strict):
    agent_id: UUID
    name: str
    #: `moving`, `moved`, or `finishing` (we are finishing it; nothing for the owner to do).
    state: AgentMoveView


class MoveOut(Strict):
    #: `waiting_for_account` (the account's own calling set-up is not ready yet), `moving`,
    #: `finishing` (one or more agents is ours to finish), or `done`.
    state: Literal["waiting_for_account", "moving", "finishing", "done"]
    #: At most `MAX_LISTED_AGENTS`, oldest first; `total` counts them all.
    agents: list[AgentMoveOut]
    total: int


class GoLiveOut(Strict):
    #: Owed (the account has paid) and neither finished nor put aside.
    due: bool
    owed_at: datetime | None
    finished_at: datetime | None
    dismissed_at: datetime | None
    #: The first step not done, or `done`.
    current: guide.GuideStep
    move: MoveOut
    #: `todo`, `in_review`, `needs_attention` (rejected or expired) or `done`.
    verify: guide.VerifyState
    #: `locked` (verify first), `waiting_approval`, `todo` or `done`.
    number: guide.NumberState
    numbers: int
    #: `done` once any agent is taking calls.
    switch_on: guide.SwitchState
    live_agents: int


async def _out(session: AsyncSession, tenant_id: UUID) -> GoLiveOut:
    state = await guide.read_go_live(session, tenant_id=tenant_id)
    marker = state.marker
    return GoLiveOut(
        due=marker is not None and marker.due,
        owed_at=marker.owed_at if marker else None,
        finished_at=marker.finished_at if marker else None,
        dismissed_at=marker.dismissed_at if marker else None,
        current=state.current,
        move=MoveOut(
            state=state.move.state,
            agents=[
                AgentMoveOut(agent_id=row.agent_id, name=row.name, state=row.state)
                for row in state.move.agents[:MAX_LISTED_AGENTS]
            ],
            total=state.move.total,
        ),
        verify=state.verify,
        number=state.number,
        numbers=state.numbers,
        switch_on=state.switch_on,
        live_agents=state.live_agents,
    )


@router.get(
    "",
    response_model=GoLiveOut,
    openapi_extra=permission_meta("org:read"),
    summary="The go-live guide after the first payment: the agents' move and the next steps",
)
async def read_go_live(session: Session, principal: Reader) -> GoLiveOut:
    assert principal.tenant_id is not None
    return await _out(session, principal.tenant_id)


async def _mark(
    marker: guide.Marker, request: Request, session: AsyncSession, principal: Principal
) -> GoLiveOut:
    assert principal.tenant_id is not None
    if await guide.mark(session, tenant_id=principal.tenant_id, marker=marker):
        await write_audit(
            session,
            actor=principal,
            action=f"go_live.{marker}",
            tenant_id=principal.tenant_id,
            object_type="organization",
            object_id=str(principal.tenant_id),
            ip=client_request_ip(request),
            summary={},
        )
    return await _out(session, principal.tenant_id)


@router.post(
    "/finish",
    response_model=GoLiveOut,
    openapi_extra=permission_meta("org:manage"),
    summary="The owner has finished going live: stop sending them to the guide",
)
async def post_finish(request: Request, session: Session, principal: Owner) -> GoLiveOut:
    return await _mark("finished", request, session, principal)


@router.post(
    "/dismiss",
    response_model=GoLiveOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put the go-live guide aside for now; the dashboard still offers it",
)
async def post_dismiss(request: Request, session: Session, principal: Owner) -> GoLiveOut:
    return await _mark("dismissed", request, session, principal)


__all__ = ["router"]
