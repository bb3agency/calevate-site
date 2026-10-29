"""Pip's notes (D-936): what it noticed, read by the panel and the launcher's count.

Client routes share the assistant's door (`copilot:use`, withheld from a view-as session)
and read under the account's RLS. A note belongs to the ACCOUNT, not to one person: the
thing it is about (a waiting lead, the credit) is the account's, so one person dismissing it
puts it away for the team, the way an announcement's dismissal does.

The admin route is the operator's twin and stores nothing: it is the Client health board
(`admin/health.client_health`) said as two lines, under the board's own permission.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.health import client_health
from apps.api.copilot import notes
from apps.api.copilot.admin_screens import ADMIN_SCREENS
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import Permission, permission_meta

router = APIRouter(prefix="/v1", tags=["copilot"])

_USE: Permission = "copilot:use"
_BOARD: Permission = "org:read"

CopilotUser = Annotated[Principal, Depends(requires(_USE))]
BoardReader = Annotated[Principal, Depends(requires(_BOARD, realm="admin"))]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CopilotNoteButtonOut(_Strict):
    #: `open` moves to a screen; `ask` prefills Pip's ask box (never sends it).
    kind: Literal["open", "ask"]
    label: str
    #: For `open`: the screen's name and its route TEMPLATE (`/c/{slug}/leads`), a constant
    #: from the screen inventory. The browser substitutes the slug and checks the result
    #: against its own sidebar before it moves (`lib/copilot/navigate.ts`).
    screen: str | None
    route: str | None
    prompt: str | None


class CopilotNoteOut(_Strict):
    #: A stored note's uuid, or `linked:<kind>` for an item another screen owns.
    id: str
    kind: str
    #: `pip` — Pip noticed it (dismissible); `linked` — another screen's item in Pip's voice.
    source: Literal["pip", "linked"]
    tone: Literal["info", "success", "warning", "critical"]
    line: str
    button: CopilotNoteButtonOut
    created_at: datetime
    unread: bool
    dismissible: bool


class CopilotNotesOut(_Strict):
    notes: list[CopilotNoteOut]
    #: Pip's own notes nobody in the account has seen yet: the launcher's count. Linked items
    #: are left out of it because the bell already counts them.
    unread: int


class CopilotNoteAckOut(_Strict):
    ok: bool


def _out(view: notes.NoteView) -> CopilotNoteOut:
    b = view.button
    return CopilotNoteOut(
        id=view.id,
        kind=view.kind,
        source=view.source,
        tone=view.tone,
        line=view.line,
        button=CopilotNoteButtonOut(
            kind=b.kind, label=b.label, screen=b.screen, route=b.route, prompt=b.prompt
        ),
        created_at=view.created_at,
        unread=view.unread,
        dismissible=view.dismissible,
    )


def _not_found() -> ProblemError:
    return ProblemError(
        kind="not_found",
        code="copilot_note_not_found",
        title="That note is gone",
        detail="It was put away or what it was about has cleared.",
        remediation="Open Pip again to see the current notes.",
    )


@router.get(
    "/copilot/notes",
    response_model=CopilotNotesOut,
    openapi_extra=permission_meta(_USE),
    summary="What Pip noticed in this account, and the items it repeats from other screens",
)
async def list_copilot_notes(
    session: Annotated[AsyncSession, Depends(db)], principal: CopilotUser
) -> CopilotNotesOut:
    views = await notes.read_notes(session, role=principal.role)
    return CopilotNotesOut(
        notes=[_out(v) for v in views],
        unread=sum(1 for v in views if v.source == "pip" and v.unread),
    )


@router.post(
    "/copilot/notes/seen",
    response_model=CopilotNoteAckOut,
    openapi_extra=permission_meta(_USE),
    summary="Mark Pip's open notes as seen (the panel was opened)",
)
async def mark_copilot_notes_seen(
    session: Annotated[AsyncSession, Depends(db)], principal: CopilotUser
) -> CopilotNoteAckOut:
    del principal
    await notes.mark_seen(session)
    return CopilotNoteAckOut(ok=True)


@router.post(
    "/copilot/notes/{note_id}/dismiss",
    response_model=CopilotNoteAckOut,
    openapi_extra=permission_meta(_USE),
    summary="Put one of Pip's notes away for the account",
)
async def dismiss_copilot_note(
    note_id: UUID, session: Annotated[AsyncSession, Depends(db)], principal: CopilotUser
) -> CopilotNoteAckOut:
    if not await notes.dismiss(session, note_id=note_id, user_id=principal.client_user_id):
        raise _not_found()
    return CopilotNoteAckOut(ok=True)


@router.post(
    "/copilot/notes/{note_id}/acted",
    response_model=CopilotNoteAckOut,
    openapi_extra=permission_meta(_USE),
    summary="Record that a note's button was pressed",
)
async def mark_copilot_note_acted(
    note_id: UUID, session: Annotated[AsyncSession, Depends(db)], principal: CopilotUser
) -> CopilotNoteAckOut:
    del principal
    if not await notes.mark_acted(session, note_id=note_id):
        raise _not_found()
    return CopilotNoteAckOut(ok=True)


def _health_button() -> CopilotNoteButtonOut:
    """The board's own screen. Its permission is the route's (`org:read`), so a reader
    who got here can open it."""
    screen = next(s for s in ADMIN_SCREENS if s.name == "Client health")
    return CopilotNoteButtonOut(
        kind="open",
        label="Open client health",
        screen=screen.name,
        route=screen.route,
        prompt=None,
    )


@router.get(
    "/admin/copilot/notes",
    response_model=CopilotNotesOut,
    openapi_extra=permission_meta(_BOARD),
    summary="Fleet notes for the operator's Pip: clients at risk and failing deliveries",
)
async def list_admin_copilot_notes(
    session: Annotated[AsyncSession, Depends(admin_db)], principal: BoardReader
) -> CopilotNotesOut:
    del principal
    board = await client_health(session)
    button = _health_button()
    out: list[CopilotNoteOut] = []
    if board:
        stop = sum(1 for row in board if row.severity == "stop")
        warn = len(board) - stop
        newest = datetime.now(UTC)
        parts = [
            p for p in (f"{stop} need you now" if stop else "", f"{warn} soon" if warn else "") if p
        ]
        out.append(
            CopilotNoteOut(
                id="linked:clients_at_risk",
                kind="clients_at_risk",
                source="linked",
                tone="critical" if stop else "warning",
                line=f"{len(board)} client{'s' if len(board) != 1 else ''} at risk: "
                + ", ".join(parts)
                + ".",
                button=button,
                created_at=newest,
                unread=False,
                dismissible=False,
            )
        )
        failing = sum(
            1 for row in board if any(s.rule == "deliveries_failing" for s in row.signals)
        )
        if failing:
            out.append(
                CopilotNoteOut(
                    id="linked:deliveries_failing",
                    kind="deliveries_failing",
                    source="linked",
                    tone="warning",
                    line=f"Lead deliveries are failing for {failing} "
                    f"client{'s' if failing != 1 else ''}.",
                    button=button,
                    created_at=newest,
                    unread=False,
                    dismissible=False,
                )
            )
    return CopilotNotesOut(notes=out, unread=0)


__all__ = ["CopilotNoteOut", "CopilotNotesOut", "router"]
