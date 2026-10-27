"""Pip's knowledge actions (D-893 L8, area `knowledge`): rename, replace a note's text,
correct a file with a note, remove, and put a removed note back. A NEW note is
`propose_knowledge`'s (`copilot/write_tools.py`), which already submits one.

Each calls the function the page calls: `kb/store.rename_source` (Rename on the reader),
`kb.service.submit_source` (`POST /v1/kb/sources`), `kb.uploads.remove_upload`
(`DELETE /v1/kb/uploads/{id}`), `kb/store.remove_note` and `restore_note`. Facts and pinned
facts are not here: lane L5's tools change those.

Tiers (COPILOT-CONTRACT, PIP-AGENT-PLAN §1): a rename changes a heading, not an answer, and
has an exact inverse, so it is `immediate` with Undo; everything that changes what a live
agent says, or deletes, is `confirm`. A file's own words are never rewritten: a correction
is a note that says what it corrects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import (
    DOES_IT,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    Undo,
    UndoRecord,
    UndoRefusedError,
    WriteRefusedError,
    action_schema,
    actor_realm,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.kb import service as kb_service
from apps.api.kb import store
from apps.api.kb.curation import CURATE_PERMISSION, goes_live_without_review
from apps.workers.redaction import redact

#: A note Pip writes is short knowledge, not a document: the page takes a document as a file.
MAX_NOTE_CHARS: Final = 4000

_WHERE: Final = "on the What your agents know screen"
#: An item's [ref], as `knowledge_sources` prints it. No description: every word of a
#: schema is paid on every request, and the read's own output shows the form.
_ITEM: Final = {"type": "string"}


async def _source_of(session: AsyncSession, ref: str) -> tuple[str, UUID, UUID | None, str]:
    """`(kind, source id, upload id or None, name)` for a file, photo, link or note."""
    try:
        kind, item_id = store.parse_ref(ref)
    except ProblemError:
        raise WriteRefusedError("`item` is not a reference from `knowledge_sources`") from None
    if kind in ("fact", "pinned_fact"):
        raise WriteRefusedError("facts are changed with the facts tools, not this one")
    if kind in ("profile", "rule") or item_id is None:
        raise WriteRefusedError(
            "the business profile and waiting rules are changed on their own screens"
        )
    if kind == "note":
        row = (
            await session.execute(
                text("SELECT id, name FROM kb_sources WHERE id = :id AND kind = 'text'"),
                {"id": item_id},
            )
        ).first()
        upload_id = None
    else:
        row = (
            await session.execute(
                text(
                    "SELECT s.id, s.name FROM kb_uploads u JOIN kb_sources s "
                    "ON s.id = u.source_id WHERE u.id = :id"
                ),
                {"id": item_id},
            )
        ).first()
        upload_id = item_id
    if row is None:
        # A fact about the world, not a malformed call: absent and invisible are one 404.
        raise ProblemError.not_found("Knowledge item")
    return kind, UUID(str(row[0])), upload_id, strip_invisible(str(row[1]))


def _no_identifiers(*values: str) -> None:
    if any(redact(value).changed for value in values):
        # The value is never named: this reason reaches a log line and the next prompt.
        raise WriteRefusedError(
            "it contains something shaped like a phone number, an email address or an "
            "identity number, which you may not write; the person can add it on the What "
            "your agents know screen themselves"
        )


# --- rename (immediate, Undo) --------------------------------------------------------


class _RenameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    name: Annotated[str, Field(min_length=2, max_length=store.MAX_NAME_CHARS)]


async def _plan_rename(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_RenameArgs, args)
    _kind, source_id, _upload, old = await _source_of(session, parsed.item)
    name = " ".join(strip_invisible(parsed.name).split())
    return Plan(
        object_id=str(source_id),
        title="Rename knowledge",
        summary=f"Rename “{old}” to “{name}”. What the agents say does not change.",
        current=old,
        proposed=name,
        cost=None,
        reversal="Undo puts the old name back.",
        args={"item": parsed.item, "name": name},
    )


async def _execute_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_RenameArgs, args)
    _kind, source_id, _upload, _old = await _source_of(session, parsed.item)
    old, new = await store.rename_source(
        session, tenant_id=actor.tenant_id, source_id=source_id, name=parsed.name
    )
    return Executed(
        applied=old != new,
        detail="Renamed." if old != new else "It already had that name.",
        audit_summary={"source_id": str(source_id)},
    )


async def _capture_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    _kind, _source, _upload, name = await _source_of(session, parse_args(_RenameArgs, args).item)
    return {"name": name}


async def _invert_rename(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    _kind, source_id, _upload, now = await _source_of(session, str(record.args["item"]))
    if now != record.result_state.get("name"):
        raise UndoRefusedError("it has been renamed again since, so it was left alone")
    await store.rename_source(
        session,
        tenant_id=actor.tenant_id,
        source_id=source_id,
        name=str(record.prior_state["name"]),
    )
    return "The old name is back."


KNOWLEDGE_RENAME: Final = ActionTool(
    name="knowledge_rename",
    tier="immediate",
    undo=Undo(capture=_capture_rename, invert=_invert_rename),
    permission=CURATE_PERMISSION,
    object_type="kb_source",
    audit_action="kb.renamed",
    where=_WHERE,
    schema=action_schema(
        "knowledge_rename",
        "Rename a file, link or note." + DOES_IT,
        {"item": _ITEM, "name": {"type": "string"}},
    ),
    plan=_plan_rename,
    execute=_execute_rename,
)


# --- write, replace or correct with a note (confirm) --------------------------------


class _NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    #: Not in the schema: the planner names the note (its own name, or "Correction to …")
    #: and the canonical arguments carry it to the executor.
    name: Annotated[str, Field(max_length=store.MAX_NAME_CHARS)] | None = None
    #: Room for the "This corrects …" sentence a correction gains; the model's own text is
    #: held to `MAX_NOTE_CHARS` by the planner.
    text: Annotated[str, Field(min_length=1, max_length=MAX_NOTE_CHARS + 200)]


#: The longest a note's current text is shown on the card before it is cut.
_CARD_CURRENT_CHARS: Final = 600


async def _note_plan_args(
    session: AsyncSession, actor: ToolActor, parsed: _NoteArgs
) -> tuple[str, str, str, str | None]:
    """`(name, body, what it does, current)` for the card and the executor."""
    body = strip_invisible(parsed.text).strip()
    if len(body) < 10:
        raise WriteRefusedError("write the note in a full sentence or two")
    if (
        len(body.split("”: ", 1)[-1] if body.startswith("This corrects “") else body)
        > MAX_NOTE_CHARS
    ):
        raise WriteRefusedError(
            f"a note is at most {MAX_NOTE_CHARS} characters; a longer document is sent as a file"
        )
    kind, _source_id, _upload, existing = await _source_of(session, parsed.item)
    _no_identifiers(body)
    if kind == "note":
        opened = await store.read_item(session, tenant_id=actor.tenant_id, ref=parsed.item)
        current = "\n\n".join(t for _, t in opened.sections)[:_CARD_CURRENT_CHARS] or None
        return existing, body, "Replace this note", current
    # A file's words are never rewritten: the correction is a note that names what it
    # corrects, so the agents (and the person) can see which wins.
    name = " ".join(strip_invisible(parsed.name or "").split()) or f"Correction to {existing}"
    _no_identifiers(name)
    lead = f"This corrects “{existing[:120]}”: "
    # Idempotent: the approval re-plans from the canonical arguments, which carry it already.
    return (
        name[: store.MAX_NAME_CHARS],
        body if body.startswith(lead) else f"{lead}{body}",
        "Correct a file with a note",
        None,
    )


async def _plan_note(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_NoteArgs, args)
    name, body, title, current = await _note_plan_args(session, actor, parsed)
    live = goes_live_without_review(realm=actor_realm(actor), impersonating=actor.impersonating)
    return Plan(
        object_id=parsed.item,
        title=title,
        summary=(
            f"Save “{name}” for every agent. "
            + ("Agents use it within a minute or two." if live else "It goes to review first.")
        ),
        current=current,
        proposed=body,
        cost=None,
        reversal="The earlier version is kept; ask Pip to remove the note or change it again.",
        args={"item": parsed.item, "name": name, "text": body},
    )


async def _execute_note(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`kb.service.submit_source` — `POST /v1/kb/sources`'s call, a new version of the name."""
    parsed = parse_args(_NoteArgs, args)
    name = (parsed.name or "").strip()
    result = await kb_service.submit_source(
        session,
        tenant_id=actor.tenant_id,
        name=name,
        body=parsed.text,
        submitted_by=actor.user_id,
        auto_approve=goes_live_without_review(
            realm=actor_realm(actor), impersonating=actor.impersonating
        ),
    )
    return Executed(
        applied=True,
        detail=(
            "Saved. Your agents use it within a minute or two."
            if result["status"] == "approved"
            else "Saved. It goes to review before your agents use it."
        ),
        audit_summary={"source_id": str(result["id"]), "version": result["version"]},
        object_id=str(result["id"]),
    )


KNOWLEDGE_NOTE_SAVE: Final = ActionTool(
    name="knowledge_note_save",
    tier="confirm",
    undo=None,
    permission=CURATE_PERMISSION,
    object_type="kb_source",
    audit_action="kb.submitted",
    where=_WHERE,
    schema=action_schema(
        "knowledge_note_save",
        "In the person's words: a note's new text, or a note correcting a file or link "
        "(item = that ref)." + PROPOSES_ONLY,
        {
            "item": _ITEM,
            "text": {"type": "string"},
        },
    ),
    plan=_plan_note,
    execute=_execute_note,
)


# --- remove (confirm) -----------------------------------------------------------------


class _RemoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    #: True puts a removed NOTE back (`kb/store.restore_note`). One tool for both directions,
    #: because every tool's schema is paid on every request (PIP-AGENT-PLAN §2a).
    put_back: bool | None = None


async def _plan_remove(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_RemoveArgs, args)
    kind, source_id, _upload, name = await _source_of(session, parsed.item)
    note = kind == "note"
    if parsed.put_back:
        if not note:
            raise WriteRefusedError("only a removed note can be put back; send a file again")
        return Plan(
            object_id=str(source_id),
            title="Put a note back",
            summary=f"Every agent answers from “{name}” again, as it last was.",
            current="Removed",
            proposed="In your knowledge",
            cost=None,
            reversal="Remove it again at any time.",
            args={"item": parsed.item, "put_back": True},
        )
    return Plan(
        object_id=str(source_id),
        title="Remove this from your knowledge",
        summary=(
            f"Take “{name}” off every agent."
            + (" Its versions are kept." if note else " The file and our copy are deleted.")
        ),
        current="In your knowledge",
        proposed="Removed",
        cost=None,
        reversal=(
            "Ask Pip to put the note back."
            if note
            else "This cannot be undone; you would send the file or link again."
        ),
        args={"item": parsed.item, "put_back": None},
    )


async def _execute_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`kb.uploads.remove_upload` (`DELETE /v1/kb/uploads/{id}`), `kb/store.remove_note`,
    or — `put_back` — `kb/store.restore_note`."""
    from apps.api.kb.uploads import remove_upload

    parsed = parse_args(_RemoveArgs, args)
    kind, source_id, upload_id, _name = await _source_of(session, parsed.item)
    if parsed.put_back and kind == "note":
        version = await store.restore_note(session, tenant_id=actor.tenant_id, source_id=source_id)
        return Executed(
            applied=True,
            detail="The note is back on every agent.",
            audit_summary={"source_id": str(source_id), "put_back": True, "version": version},
            audit_action="kb.restored",
        )
    if kind == "note":
        await store.remove_note(session, tenant_id=actor.tenant_id, source_id=source_id)
        detail = "The note is off every agent. Ask me to put it back if you need it."
    else:
        assert upload_id is not None
        await remove_upload(session, tenant_id=actor.tenant_id, upload_id=upload_id)
        detail = "It is removed from every agent and deleted."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={"source_id": str(source_id), "kind": kind},
    )


KNOWLEDGE_REMOVE: Final = ActionTool(
    name="knowledge_remove",
    tier="confirm",
    undo=None,
    permission=CURATE_PERMISSION,
    object_type="kb_source",
    audit_action="kb.removed",
    where=_WHERE,
    schema=action_schema(
        "knowledge_remove",
        "Propose removing a file, photo, link or note (put_back: restore a removed note)."
        + PROPOSES_ONLY,
        {"item": _ITEM, "put_back": {"anyOf": [{"type": "boolean"}, {"type": "null"}]}},
    ),
    plan=_plan_remove,
    execute=_execute_remove,
)


#: Appended to `WRITE_TOOLS`; `knowledge_remove` keeps its place in `CONSOLE_ACTIONS`.
KNOWLEDGE_ACTIONS: Final[tuple[ActionTool, ...]] = (KNOWLEDGE_RENAME, KNOWLEDGE_NOTE_SAVE)

__all__ = [
    "KNOWLEDGE_ACTIONS",
    "KNOWLEDGE_NOTE_SAVE",
    "KNOWLEDGE_REMOVE",
    "KNOWLEDGE_RENAME",
    "MAX_NOTE_CHARS",
]
