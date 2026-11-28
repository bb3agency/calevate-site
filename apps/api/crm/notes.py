"""Notes the team leaves on a lead or one of its calls (W7.2).

The words live in `lead_notes`; the lead's timeline gets one `note` row per note whose payload
is `{kind: "owner_note", note_id}` and nothing else, so `lead_events` keeps holding no prose
(its erasure exemption rests on that). The timeline reads the words back through
`note_bodies` at render time, so an edit or a removal shows on the history at once.

A note is changed in place under a version CAS and removed with a DELETE. Who may change one:
the person who wrote it, or the account's owner. An operator in a view-as session may add
notes (attributed to no member) but changes only the ones that carry no author.

Note text is never logged (hard rule 6); every log or error here names ids only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: The `kind` a note's timeline row carries; `crm.service._project_event` reads it.
OWNER_NOTE_KIND: Final = "owner_note"

#: The most notes one call page lists. A call is a few minutes; more than this is a thread,
#: and the lead's own history holds every one.
MAX_CALL_NOTES: Final = 50

_NOTE_SELECT = (
    "SELECT n.id, n.lead_id, n.call_id, n.author_user_id, u.name AS author_name, n.body, "
    "n.version, n.created_at, n.edited_at FROM lead_notes n "
    # Through `memberships` (RLS'd), so a person no longer on this account is not named.
    "LEFT JOIN memberships m ON m.user_id = n.author_user_id "
    "LEFT JOIN users u ON u.id = m.user_id "
)


@dataclass(frozen=True, slots=True)
class Note:
    id: UUID
    lead_id: UUID
    call_id: UUID | None
    author_user_id: UUID | None
    author_name: str | None
    body: str
    version: int
    created_at: datetime
    edited_at: datetime | None


def _note(row: Any) -> Note:
    return Note(
        id=row.id,
        lead_id=row.lead_id,
        call_id=row.call_id,
        author_user_id=row.author_user_id,
        author_name=row.author_name,
        body=row.body,
        version=int(row.version),
        created_at=row.created_at,
        edited_at=row.edited_at,
    )


_CALL_NOT_ON_LEAD = ProblemError.business_rule(
    "note_call_not_on_lead",
    "That call is not one of this person's calls, so the note cannot be filed under it.",
    remediation="Write the note from the call's own page, or on the person's page.",
)

_NOT_YOURS = ProblemError(
    kind="permission",
    code="note_not_yours",
    title="Only the writer can change this note",
    detail="A note can be changed or removed by the person who wrote it, or by the owner.",
    remediation="Add a new note instead, or ask the account owner.",
)

_CHANGED_MEANWHILE = ProblemError.conflict(
    "note_changed",
    "Someone changed this note while you were editing it.",
    remediation="Reload to see their version, then make your change again.",
)


async def _lead_is_open(session: AsyncSession, lead_id: UUID) -> None:
    found = (
        await session.execute(
            text("SELECT 1 FROM leads WHERE id = :lid AND deleted_at IS NULL"), {"lid": lead_id}
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Lead")


async def add_note(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    body: str,
    call_id: UUID | None,
    author_user_id: UUID | None,
    actor: str,
) -> Note:
    """Write a note and its timeline row in the caller's transaction."""
    await _lead_is_open(session, lead_id)
    if call_id is not None:
        on_lead = (
            await session.execute(
                text(
                    "SELECT 1 FROM calls WHERE id = :cid AND lead_id = :lid "
                    "AND erased_subject_ref IS NULL"
                ),
                {"cid": call_id, "lid": lead_id},
            )
        ).first()
        if on_lead is None:
            raise _CALL_NOT_ON_LEAD
    note_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO lead_notes (id, tenant_id, lead_id, call_id, author_user_id, body) "
            "VALUES (:id, :tid, :lid, :cid, :author, :body)"
        ),
        {
            "id": note_id,
            "tid": tenant_id,
            "lid": lead_id,
            "cid": call_id,
            "author": author_user_id,
            "body": body,
        },
    )
    payload: dict[str, str] = {"kind": OWNER_NOTE_KIND, "note_id": str(note_id)}
    if call_id is not None:
        payload["call_id"] = str(call_id)
    await session.execute(
        text(
            "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
            "created_at, updated_at) VALUES (:id, :tid, :lid, 'note', "
            "CAST(:payload AS jsonb), :actor, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "lid": lead_id,
            "payload": _json(payload),
            "actor": actor,
        },
    )
    return await _one(session, note_id)


def _json(payload: dict[str, str]) -> str:
    return json.dumps(payload, separators=(",", ":"))


async def _one(session: AsyncSession, note_id: UUID) -> Note:
    row = (await session.execute(text(_NOTE_SELECT + "WHERE n.id = :id"), {"id": note_id})).first()
    if row is None:
        raise ProblemError.not_found("Note")
    return _note(row)


async def _may_change(
    session: AsyncSession, *, lead_id: UUID, note_id: UUID, editor: UUID | None, is_owner: bool
) -> None:
    """404 for a note this lead does not hold, 403 for a note the editor may not change."""
    row = (
        await session.execute(
            text("SELECT author_user_id FROM lead_notes WHERE id = :id AND lead_id = :lid"),
            {"id": note_id, "lid": lead_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Note")
    if not is_owner and row.author_user_id != editor:
        raise _NOT_YOURS


async def edit_note(
    session: AsyncSession,
    *,
    lead_id: UUID,
    note_id: UUID,
    body: str,
    expected_version: int,
    editor: UUID | None,
    is_owner: bool,
) -> Note:
    """Replace a note's words, only if nobody changed it since `expected_version` (CAS)."""
    await _lead_is_open(session, lead_id)
    await _may_change(session, lead_id=lead_id, note_id=note_id, editor=editor, is_owner=is_owner)
    changed = (
        await session.execute(
            text(
                "UPDATE lead_notes SET body = :body, version = version + 1, edited_at = now(), "
                "updated_at = now() WHERE id = :id AND lead_id = :lid AND version = :v "
                "RETURNING id"
            ),
            {"body": body, "id": note_id, "lid": lead_id, "v": expected_version},
        )
    ).first()
    if changed is None:
        raise _CHANGED_MEANWHILE
    return await _one(session, note_id)


async def remove_note(
    session: AsyncSession, *, lead_id: UUID, note_id: UUID, editor: UUID | None, is_owner: bool
) -> None:
    """Delete a note. Its timeline row stays and reads "Note removed"."""
    await _lead_is_open(session, lead_id)
    await _may_change(session, lead_id=lead_id, note_id=note_id, editor=editor, is_owner=is_owner)
    await session.execute(
        text("DELETE FROM lead_notes WHERE id = :id AND lead_id = :lid"),
        {"id": note_id, "lid": lead_id},
    )


async def call_notes(session: AsyncSession, call_id: UUID, *, limit: int) -> tuple[list[Note], int]:
    """The notes written from one call, oldest first, and how many there are in all."""
    exists = (
        await session.execute(
            text("SELECT lead_id FROM calls WHERE id = :cid AND erased_subject_ref IS NULL"),
            {"cid": call_id},
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Call")
    rows = (
        await session.execute(
            text(
                _NOTE_SELECT.replace("SELECT n.id", "SELECT count(*) OVER () AS matching, n.id")
                + "WHERE n.call_id = :cid ORDER BY n.created_at, n.id LIMIT :limit"
            ),
            {"cid": call_id, "limit": limit},
        )
    ).all()
    return [_note(row) for row in rows], int(rows[0].matching) if rows else 0


async def note_bodies(session: AsyncSession, note_ids: set[UUID]) -> dict[UUID, Note]:
    """The notes a timeline page names, in one read. A removed note has no entry."""
    if not note_ids:
        return {}
    rows = (
        await session.execute(
            text(_NOTE_SELECT + "WHERE n.id = ANY(:ids)"), {"ids": list(note_ids)}
        )
    ).all()
    return {row.id: _note(row) for row in rows}
