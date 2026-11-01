"""Mistakes on real calls (D-949): the owner's list per agent, and the operator's board.

    GET  /v1/agents/{agent_id}/call-mistakes     what this agent got wrong on real calls
    GET  /v1/ops/call-mistakes                   every kind across every client
    POST /v1/ops/call-mistakes/{kind}/fixed      the platform rule for a kind is fixed

The words a caller said never leave the database here: a mistake is a kind, a count, a time
and a call id (hard rule 6). The reasoning is in `agents/call_mistakes.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_mistakes
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Strict

router = APIRouter(tags=["agents"])
ops_router = APIRouter(prefix="/v1/ops/call-mistakes", tags=["ops"])

Session = Annotated[AsyncSession, Depends(db)]
GlobalSession = Annotated[AsyncSession, Depends(global_db)]
#: The tenant-directory session: `call_mistake_scan` enters each client in turn.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

MistakeState = Literal["fixing", "fixed", "back"]


class AgentMistakeOut(Strict):
    kind: str
    label: str
    #: What a good telecaller does instead, in one line.
    instead: str
    calls: int
    calls_since_fix: int
    last_seen_at: datetime
    last_call_id: UUID
    fixed_at: datetime | None
    #: `fixing`: we know and are changing the rule. `fixed`: not seen since the fix.
    #: `back`: seen on a call that started after the fix.
    state: MistakeState


class AgentMistakesOut(Strict):
    items: list[AgentMistakeOut]
    window_days: int


class PlatformMistakeOut(Strict):
    kind: str
    label: str
    calls_7d: int
    calls_30d: int
    accounts_30d: int
    calls_since_fix: int
    last_seen_at: datetime | None
    fixed_at: datetime | None
    fix_note: str | None
    fixed_by: str | None
    state: MistakeState


class PlatformMistakesOut(Strict):
    items: list[PlatformMistakeOut]
    window_days: int


class MistakeFixIn(Strict):
    note: str = Field(min_length=1, max_length=call_mistakes.NOTE_MAX_CHARS)


class MistakeFixOut(Strict):
    kind: str
    fixed_at: datetime


@router.get(
    "/v1/agents/{agent_id}/call-mistakes",
    response_model=AgentMistakesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="What this agent got wrong on real calls, and whether it is fixed",
)
async def list_agent_mistakes(agent_id: UUID, session: Session, _: AgentReader) -> AgentMistakesOut:
    exists = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :a AND deleted_at IS NULL"), {"a": agent_id}
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Agent")
    found = await call_mistakes.agent_mistakes(session, agent_id)
    return AgentMistakesOut(
        items=[
            AgentMistakeOut(
                kind=m.kind,
                label=m.label,
                instead=m.instead,
                calls=m.calls,
                calls_since_fix=m.calls_since_fix,
                last_seen_at=m.last_seen_at,
                last_call_id=m.last_call_id,
                fixed_at=m.fixed_at,
                state=m.state,
            )
            for m in found
        ],
        window_days=call_mistakes.WINDOW_DAYS,
    )


@ops_router.get(
    "",
    response_model=PlatformMistakesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Mistakes agents made on real calls, across every client (D-949)",
)
async def list_platform_mistakes(session: AdminSession, _: Operator) -> PlatformMistakesOut:
    """A read, so no step-up: it writes nothing and shows counts, never words."""
    found = await call_mistakes.platform_mistakes(session)
    return PlatformMistakesOut(
        items=[
            PlatformMistakeOut(
                kind=m.kind,
                label=m.label,
                calls_7d=m.calls_7d,
                calls_30d=m.calls_30d,
                accounts_30d=m.accounts_30d,
                calls_since_fix=m.calls_since_fix,
                last_seen_at=m.last_seen_at,
                fixed_at=m.fixed_at,
                fix_note=m.fix_note,
                fixed_by=m.fixed_by,
                state=m.state,
            )
            for m in found
        ],
        window_days=call_mistakes.WINDOW_DAYS,
    )


@ops_router.post(
    "/{kind}/fixed",
    response_model=MistakeFixOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Say the platform rule behind a mistake is fixed, from now",
)
async def mark_mistake_fixed(
    kind: str,
    payload: MistakeFixIn,
    session: GlobalSession,
    request: Request,
    principal: Operator,
) -> MistakeFixOut:
    """No step-up: it changes no client's agent and no money, only when a recurrence counts
    as one. Audited, with the note."""
    assert principal.user_id is not None
    fixed_at = await call_mistakes.mark_fixed(
        session, kind=kind, note=payload.note, admin_id=principal.user_id
    )
    await write_audit(
        session,
        action="ops.call_mistake_fixed",
        actor=principal,
        object_type="call_mistake_kind",
        object_id=kind,
        ip=client_request_ip(request),
        summary={"kind": kind},
    )
    return MistakeFixOut(kind=kind, fixed_at=fixed_at)


__all__ = ["ops_router", "router"]
