"""How an agent should sound, taught a line at a time (founder, 17 Nov 2026).

An owner hears a scenario's line in the agent's voice and writes how it should sound
("slower", "warmer", "say Rytu Khata as రైతు ఖాతా"). A note on the scenario shapes that one
line; a note TAUGHT TO THE AGENT is kept here and every call the agent makes follows it: its
own, its campaigns' and its inbound lines', because each of those is built from the agent's
config (`agents/service._to_config`), where `with_voice_notes` adds them to the script.

They take effect the next time each is put live (a publish, a campaign's Start or Test
call, a line's Put live), the rule the rest of the script follows: a note never changes what
a live call says until the owner puts it live. Retired, never deleted (`retired_at`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from calevate_shared.engine import AgentConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import LANGUAGE_LABELS
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: The most active notes one agent keeps. Each is re-read on every reply, so the set stays
#: small: past this the owner retires one first.
MAX_ACTIVE_NOTES: Final = 20
NOTE_MAX_CHARS: Final = 300
SOURCE_MAX_CHARS: Final = 200

#: The block the notes are written under, inside the client's script.
VOICE_NOTES_HEADER: Final = "[HOW YOU SOUND]"
VOICE_NOTES_LEAD: Final = (
    "The owner listened to you and asked for this. Follow it on every call, in the language "
    "named or in all of them:"
)


@dataclass(frozen=True, slots=True)
class VoiceNote:
    id: UUID
    language: str
    note: str
    source: str
    created_at: datetime


def _clean(value: str, limit: int, *, what: str) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise ProblemError.business_rule(
            "voice_note_too_long", f"The {what} is at most {limit} characters."
        )
    return cleaned


async def list_notes(session: AsyncSession, *, agent_id: UUID) -> list[VoiceNote]:
    """The agent's active notes, oldest first (the order they were taught)."""
    rows = (
        await session.execute(
            text(
                "SELECT id, language, note, source, created_at FROM agent_voice_notes "
                "WHERE agent_id = :aid AND retired_at IS NULL ORDER BY created_at, id "
                "LIMIT :n"
            ),
            {"aid": agent_id, "n": MAX_ACTIVE_NOTES},
        )
    ).all()
    return [VoiceNote(r[0], str(r[1]), str(r[2]), str(r[3]), r[4]) for r in rows]


async def load(session: AsyncSession, *, agent_id: UUID) -> tuple[tuple[str, str], ...]:
    """(language, note) pairs for `agents/service._load_agent`."""
    return tuple((n.language, n.note) for n in await list_notes(session, agent_id=agent_id))


async def add_note(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    language: str,
    note: str,
    source: str,
    created_by: UUID | None,
) -> VoiceNote:
    """Teach the agent one note. The same words in the same language already active are
    that note, not a second copy."""
    words = _clean(note, NOTE_MAX_CHARS, what="note")
    if not words:
        raise ProblemError.business_rule("voice_note_empty", "Write how it should sound first.")
    if language and language not in LANGUAGE_LABELS:
        raise ProblemError.business_rule(
            "voice_note_language", "That is not a language this agent can speak."
        )
    where = _clean(source, SOURCE_MAX_CHARS, what="source")
    # Serialise per agent so the cap below holds under two saves at once.
    found = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"),
            {"aid": agent_id},
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Agent")
    active = await list_notes(session, agent_id=agent_id)
    for held in active:
        if held.language == language and held.note.casefold() == words.casefold():
            return held
    if len(active) >= MAX_ACTIVE_NOTES:
        raise ProblemError.business_rule(
            "voice_notes_full",
            f"An agent keeps {MAX_ACTIVE_NOTES} notes on how it sounds.",
            remediation="Retire one on the agent's page first.",
        )
    note_id = uuid7()
    created = (
        await session.execute(
            text(
                "INSERT INTO agent_voice_notes (id, tenant_id, agent_id, language, note, "
                "source, created_by) VALUES (:id, :tid, :aid, :lang, :note, :src, :by) "
                "RETURNING created_at"
            ),
            {
                "id": note_id,
                "tid": tenant_id,
                "aid": agent_id,
                "lang": language,
                "note": words,
                "src": where,
                "by": created_by,
            },
        )
    ).scalar_one()
    return VoiceNote(note_id, language, words, where, created)


async def retire_note(session: AsyncSession, *, agent_id: UUID, note_id: UUID) -> bool:
    """Stop the agent following a note; the row stays. False when it was not active."""
    done = (
        await session.execute(
            text(
                "UPDATE agent_voice_notes SET retired_at = now(), updated_at = now() "
                "WHERE id = :id AND agent_id = :aid AND retired_at IS NULL RETURNING id"
            ),
            {"id": note_id, "aid": agent_id},
        )
    ).first()
    return done is not None


def notes_block(notes: Sequence[tuple[str, str]]) -> str:
    """The notes as the agent reads them, or "" with none."""
    if not notes:
        return ""
    lines = [
        f"- {f'({LANGUAGE_LABELS.get(lang, lang)}) ' if lang else ''}{note}" for lang, note in notes
    ]
    return f"{VOICE_NOTES_HEADER} {VOICE_NOTES_LEAD}\n" + "\n".join(lines)


def with_voice_notes(cfg: AgentConfig, notes: Sequence[tuple[str, str]]) -> AgentConfig:
    """`cfg` with the agent's notes after its script, inside the client's fence, so they are
    the owner's words like the rest of it. A no-op with none."""
    block = notes_block(notes)
    if not block:
        return cfg
    body = (cfg.system_prompt or "").rstrip()
    return cfg.model_copy(update={"system_prompt": f"{body}\n\n{block}" if body else block})


__all__ = [
    "MAX_ACTIVE_NOTES",
    "VoiceNote",
    "add_note",
    "list_notes",
    "load",
    "notes_block",
    "retire_note",
    "with_voice_notes",
]
