"""How an agent should sound, taught by its owner (`agents/voice_notes`).

    GET   /v1/agents/{aid}/voice-notes                       the active notes
    POST  /v1/agents/{aid}/voice-notes                       teach one (audited)
    POST  /v1/agents/{aid}/voice-notes/{nid}/retire          stop following one (audited)

Reading is `agents:read`; teaching and retiring are `agents:write`, the permission that
edits what the agent says.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import voice_notes
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]
Writer = Annotated[Principal, Depends(requires("agents:write"))]

router = APIRouter(tags=["agents"])

_PATH = "/v1/agents/{agent_id}/voice-notes"


class VoiceNoteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    #: A language tag, or "" for every language.
    language: str
    note: str
    #: Where it was taught, e.g. "Campaign: Rytu Khata support, scenario 2.1".
    source: str
    created_at: datetime


class VoiceNotesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VoiceNoteOut]
    #: The most active notes an agent keeps.
    limit: int


class VoiceNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(default="", max_length=10)
    note: str = Field(min_length=1, max_length=voice_notes.NOTE_MAX_CHARS)
    source: str = Field(default="", max_length=voice_notes.SOURCE_MAX_CHARS)


def _out(note: voice_notes.VoiceNote) -> VoiceNoteOut:
    return VoiceNoteOut(
        id=note.id,
        language=note.language,
        note=note.note,
        source=note.source,
        created_at=note.created_at,
    )


@router.get(
    _PATH,
    response_model=VoiceNotesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="How the owner taught this agent to sound",
)
async def list_voice_notes(agent_id: UUID, session: Session, _: Reader) -> VoiceNotesOut:
    notes = await voice_notes.notes_of_agent(session, agent_id=agent_id)
    return VoiceNotesOut(items=[_out(n) for n in notes], limit=voice_notes.MAX_ACTIVE_NOTES)


@router.post(
    _PATH,
    response_model=VoiceNoteOut,
    status_code=201,
    openapi_extra=permission_meta("agents:write"),
    summary="Teach this agent how to sound on every call",
    description=(
        "Every call the agent makes follows its active notes, from the next time each of its "
        f"agents, campaigns and lines is put live. At most {voice_notes.MAX_ACTIVE_NOTES}; "
        "the same words in the same language return the note already held."
    ),
)
async def add_voice_note(
    agent_id: UUID, payload: VoiceNoteIn, session: Session, request: Request, principal: Writer
) -> VoiceNoteOut:
    assert principal.tenant_id is not None
    note = await voice_notes.add_note(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        language=payload.language,
        note=payload.note,
        source=payload.source,
        created_by=principal.user_id,
    )
    await write_audit(
        session,
        action="agent.voice_note_taught",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"note_id": str(note.id), "language": note.language},
    )
    return _out(note)


@router.post(
    f"{_PATH}/{{note_id}}/retire",
    status_code=204,
    openapi_extra=permission_meta("agents:write"),
    summary="Stop this agent following a note (kept, not deleted)",
)
async def retire_voice_note(
    agent_id: UUID, note_id: UUID, session: Session, request: Request, principal: Writer
) -> None:
    assert principal.tenant_id is not None
    if not await voice_notes.retire_note(session, agent_id=agent_id, note_id=note_id):
        raise ProblemError.not_found("Note")
    await write_audit(
        session,
        action="agent.voice_note_retired",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"note_id": str(note_id)},
    )
