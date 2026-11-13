"""Mistakes on real calls (D-949): the owner's list per agent, and the operator's board.

    GET  /v1/agents/{agent_id}/call-mistakes     what this agent got wrong on real calls
    POST /v1/agents/{agent_id}/call-mistakes/{kind}/undo   put back the script from before
                                                 our fix of that mistake (D-985)
    GET  /v1/ops/call-mistakes                   every kind across every client
    POST /v1/ops/call-mistakes/{kind}/fixed      the platform rule for a kind is fixed
    GET  /v1/ops/call-mistakes/fixes             every agent's script fixes (D-985)

The words a caller said never leave the database here: a mistake is a kind, a count, a time
and a call id (hard rule 6). The reasoning is in `agents/call_mistakes.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_mistakes, mistake_fixes
from apps.api.agents.models import MistakeFixFoundBy
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Strict
from apps.api.core.settings import get_settings
from apps.api.healer import ledger

router = APIRouter(tags=["agents"])
ops_router = APIRouter(prefix="/v1/ops/call-mistakes", tags=["ops"])

Session = Annotated[AsyncSession, Depends(db)]
GlobalSession = Annotated[AsyncSession, Depends(global_db)]
#: The tenant-directory session: `call_mistake_scan` enters each client in turn.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

MistakeState = Literal["fixing", "fixed", "back"]
FixState = Literal["fixing", "live", "fixed", "rolled_back", "needs_person"]
ScriptWriter = Annotated[Principal, Depends(requires("org:manage"))]

#: How far back the operator's list of script fixes looks, and how many it shows.
FLEET_FIXES_DAYS: Final = call_mistakes.WINDOW_DAYS
FLEET_FIXES_MAX: Final = 200


class AgentMistakeOut(Strict):
    kind: str
    label: str
    #: What a good telecaller does instead, in one line.
    instead: str
    calls: int
    calls_since_fix: int
    #: The last call that showed it; null when none did (`found_in_script`).
    last_seen_at: datetime | None
    last_call_id: UUID | None
    #: When the fix the state is about was made: the agent's script fix going live where it
    #: has one (D-985), else the platform rule's.
    fixed_at: datetime | None
    #: The platform's three where the agent's script has no fix of it: `fixing` (no fix
    #: recorded; `call_mistake_new` raised), `fixed` (not seen since), `back` (seen after).
    #: Else its script fix's (D-985): `script_fixing` (being written or waiting),
    #: `script_live` (live and watched), `script_fixed` (held), `script_rolled_back` (did not
    #: hold, the old script is back), `script_undone` (the owner put it back), `with_team`
    #: (no line of the script causes it, or the healer handed it to our team).
    state: call_mistakes.AgentState
    #: Checked calls since the script fix went live that did not show it.
    clean_calls: int
    #: The calls a script fix must stay clean for (`call_mistake_fix_clean_calls`).
    clean_calls_needed: int
    #: The owner may undo the script fix: it is live or held and the script is still it.
    can_undo: bool
    #: No call showed it: the script check found its cause in the live script and it was
    #: fixed before any call (D-989).
    found_in_script: bool


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
    #: Where in the platform prompt the fix goes; empty where no rule is known yet.
    rule: str
    #: The latest call showing it and its client, to open it as that client.
    last_call_id: UUID | None
    last_client_slug: str | None


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
                clean_calls=m.clean_calls,
                clean_calls_needed=get_settings().call_mistake_fix_clean_calls,
                can_undo=m.can_undo,
                found_in_script=m.found_in_script,
            )
            for m in found
        ],
        window_days=call_mistakes.WINDOW_DAYS,
    )


class MistakeUndoOut(Strict):
    kind: str
    #: The new version, a copy of the script from before the fix, now live.
    version: int


@router.post(
    "/v1/agents/{agent_id}/call-mistakes/{kind}/undo",
    response_model=MistakeUndoOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put back the script from before our fix of this mistake",
)
async def undo_mistake_fix(
    agent_id: UUID, kind: str, session: Session, request: Request, principal: ScriptWriter
) -> MistakeUndoOut:
    """The owner's Undo (D-985): the script from before the fix becomes a new live version
    (`prompts.rollback_prompt`, copy-forward) and the healer does not make that fix again.
    Refused once the script changed after the fix, which putting back would throw away.
    Audited with version numbers only, in this request's transaction."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    fix, version = await mistake_fixes.undo_by_owner(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        kind=kind,
        by=principal.client_user_id,
    )
    await ledger.record(
        session,
        playbook=mistake_fixes.PLAYBOOK,
        step="undo",
        outcome="ok",
        incident_id=fix.incident_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        detail=f"owner put back version {fix.version_before} as version {version}",
        actor_type="admin" if principal.is_admin else "user",
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="agent.mistake_fix_undone",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={
            "kind": kind,
            "from_version": fix.version_after,
            "to_version": fix.version_before,
            "version": version,
        },
    )
    return MistakeUndoOut(kind=kind, version=version)


class FleetFixOut(Strict):
    id: UUID
    client_slug: str
    agent_id: UUID
    agent_name: str
    kind: str
    label: str
    state: FixState
    #: Why it stopped short of `fixed`: `came_back`, `worse`, `owner`, `no_script_cause`,
    #: `waited_too_long`, `attempts_spent`, `script_changed`, `agent_gone`.
    ended_because: str | None
    attempts: int
    version_before: int | None
    version_after: int | None
    live_at: datetime | None
    settled_at: datetime | None
    created_at: datetime
    #: `call` (a real call showed it) or `script_check` (found in the live script before
    #: any call, D-989).
    found_by: MistakeFixFoundBy


class FleetFixesOut(Strict):
    items: list[FleetFixOut]
    window_days: int


@ops_router.get(
    "/fixes",
    response_model=FleetFixesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Every agent's script fixes of mistakes on real calls (D-985)",
)
async def list_fleet_fixes(
    session: AdminSession,
    _: Operator,
    limit: int = Query(100, ge=1, le=FLEET_FIXES_MAX, description="How many to return."),
) -> FleetFixesOut:
    """A read, so no step-up: ids, kinds, versions and times only."""
    found = await mistake_fixes.fleet_fixes(
        session,
        since=datetime.now(UTC) - timedelta(days=FLEET_FIXES_DAYS),
        limit=limit,
    )
    return FleetFixesOut(
        items=[
            FleetFixOut(
                id=f.id,
                client_slug=f.client_slug,
                agent_id=f.agent_id,
                agent_name=f.agent_name,
                kind=f.kind,
                label=call_mistakes.LESSONS[f.kind].label
                if f.kind in call_mistakes.LESSONS
                else f.kind,
                state=f.state,
                ended_because=f.ended_because,
                attempts=f.attempts,
                version_before=f.version_before,
                version_after=f.version_after,
                live_at=f.live_at,
                settled_at=f.settled_at,
                created_at=f.created_at,
                found_by=f.found_by,
            )
            for f in found
        ],
        window_days=FLEET_FIXES_DAYS,
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
                rule=m.rule,
                last_call_id=m.last_call_id,
                last_client_slug=m.last_client_slug,
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
