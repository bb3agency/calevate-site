"""Ops > Call words: the founder edits the words the call checks listen for (G-C2).

    GET /v1/ops/call-words          every entry: what is in force, the shipped default, and
                                     what the founder is asked to write
    GET /v1/ops/call-words/{key}    one entry with its history
    PUT /v1/ops/call-words/{key}    save an entry, or put the shipped one back (null);
                                     step-up `change_call_words:<key>`

The list is `calevate_shared/call_words.json`'s entries, read at request time, so an entry a
release adds to the file appears here without a change to this screen. A save is checked three
ways before it is written: the value keeps the shipped shape and every word or pattern in it
compiles (`call_words.problems`); every check this process has loaded still builds with it
(`call_words.trial`), because a fragment can be valid alone and break the pattern it is
joined into; and a pattern handed to PostgreSQL is tried there. A save reaches every check
within the poll (`call_words_store`), so it takes the step-up gate: the do-not-call phrases
are among these entries, and a wrong one decides which numbers can be dialled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from calevate_shared import call_words
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops import call_words_store as store

router = APIRouter(prefix="/v1/ops/call-words", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
WordsOperator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
EntryKey = Annotated[str, Path(max_length=120, pattern=r"^[A-Za-z0-9_.]+$")]

#: The longest pattern, and the most words and patterns in one entry, a save may carry. The
#: longest shipped pattern is under 900 characters and the longest list under 60 words.
MAX_PATTERN_CHARS = 4000
MAX_LIST_ITEMS = 500

#: A pattern, a list of words, or a table by language (`call_words` module docstring).
CallWordValue = str | list[str] | dict[str, Any]


def change_confirmation(key: str) -> str:
    """The step-up string, bound to the entry."""
    return f"change_call_words:{key}"


class RevisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Null when this save put the shipped entry back.
    value: CallWordValue | None
    note: str | None
    changed_by: UUID
    changed_at: datetime


class CallWordOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    #: The part of the key before its first dot: which part of the product reads it.
    group: str
    shape: Literal["pattern", "list", "table"]
    #: What the checks listen for now.
    value: CallWordValue
    #: What the file ships.
    shipped: CallWordValue
    #: True when an edit is in force in place of the shipped entry.
    edited: bool
    changed_at: datetime | None
    #: What the founder is asked to write here, from the file's `missing` section.
    asked_for: str | None
    #: How the entry is used, from the file's `notes` section.
    note: str | None
    #: The step-up string `PUT` needs.
    confirmation: str


class CallWordDetailOut(CallWordOut):
    history: list[RevisionOut]


class CallWordsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The file's own description of the lists.
    about: str
    entries: list[CallWordOut]


class CallWordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The whole entry in its shipped shape; null puts the shipped entry back.
    value: CallWordValue | None
    note: str | None = Field(default=None, max_length=300)


def _shape(value: Any) -> Literal["pattern", "list", "table"]:
    if isinstance(value, str):
        return "pattern"
    return "list" if isinstance(value, list) else "table"


def _asked_for(key: str) -> str | None:
    notes = call_words.missing_notes()
    if key in notes:
        return notes[key]
    for pattern, text_ in notes.items():
        if pattern.endswith(".*") and key.startswith(pattern[:-1]):
            return text_
    return None


def _entry(key: str, revision: store.Revision | None) -> CallWordOut:
    shipped = call_words.shipped()[key]
    edited = revision is not None and revision.value is not None
    return CallWordOut(
        key=key,
        group=key.split(".", 1)[0],
        shape=_shape(shipped),
        value=revision.value if revision is not None and edited else shipped,
        shipped=shipped,
        edited=edited,
        changed_at=revision.created_at if revision is not None else None,
        asked_for=_asked_for(key),
        note=call_words.entry_notes().get(key),
        confirmation=change_confirmation(key),
    )


def _known(key: str) -> str:
    if key not in call_words.shipped():
        raise ProblemError.not_found("Word list")
    return key


async def _detail(session: AsyncSession, key: str) -> CallWordDetailOut:
    revisions = await store.history(session, key=key)
    entry = _entry(key, revisions[0] if revisions else None)
    return CallWordDetailOut(
        **entry.model_dump(),
        history=[
            RevisionOut(
                value=r.value, note=r.note, changed_by=r.created_by, changed_at=r.created_at
            )
            for r in revisions
        ],
    )


@router.get(
    "",
    response_model=CallWordsOut,
    summary="Every word list the call checks listen for",
    openapi_extra=permission_meta("ops:manage"),
)
async def list_call_words(session: GlobalSession, _operator: WordsOperator) -> CallWordsOut:
    latest = await store.latest(session)
    return CallWordsOut(
        about=call_words.about(),
        entries=[_entry(key, latest.get(key)) for key in call_words.shipped()],
    )


@router.get(
    "/{key}",
    response_model=CallWordDetailOut,
    summary="One word list and its history",
    openapi_extra=permission_meta("ops:manage"),
)
async def read_call_words(
    session: GlobalSession, _operator: WordsOperator, key: EntryKey
) -> CallWordDetailOut:
    return await _detail(session, _known(key))


def _refuse(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def _too_big(value: Any) -> str | None:
    if sum(1 for _ in call_words.strings_of(value)) > MAX_LIST_ITEMS:
        return f"A list or table holds at most {MAX_LIST_ITEMS} words and patterns."
    longest = max((len(s) for s in call_words.strings_of(value)), default=0)
    if longest > MAX_PATTERN_CHARS:
        return f"A pattern or word holds at most {MAX_PATTERN_CHARS} characters."
    return None


async def _postgres_refuses(session: AsyncSession, patterns: tuple[str, ...]) -> str | None:
    """The first pattern PostgreSQL cannot read, with its message, or None. Each try runs in
    a savepoint, because a refused pattern aborts the transaction it runs in."""
    for pattern in patterns:
        try:
            async with session.begin_nested():
                await session.execute(text("SELECT '' ~* :pattern"), {"pattern": pattern})
        except DBAPIError as exc:
            return str(exc.orig).splitlines()[0] if exc.orig is not None else str(exc)
    return None


@router.put(
    "/{key}",
    response_model=CallWordDetailOut,
    summary="Save one word list, or put the shipped one back (step-up, audited)",
    description=(
        "The whole entry in its shipped shape, or null for the shipped entry. Refused with "
        "a plain reason when a word or pattern does not compile, or would break the check "
        "it is part of. Every check uses it within a minute, without a deploy. Requires "
        "`X-Confirm-Action: change_call_words:<key>`."
    ),
    openapi_extra=permission_meta("ops:manage"),
)
async def change_call_words(
    payload: CallWordIn,
    session: GlobalSession,
    request: Request,
    principal: WordsOperator,
    key: EntryKey,
    step_up: StepUpGate,
    tasks: BackgroundTasks,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> CallWordDetailOut:
    key = _known(key)
    step_up.require(x_confirm_action, change_confirmation(key))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="call_words_actor_unknown",
            title="This session has no admin identity",
            detail="A change to the call words has to be attributable to an operator.",
        )
    value = payload.value
    if value is not None:
        too_big = _too_big(value)
        if too_big is not None:
            raise _refuse("call_words_too_long", "That list is too long", too_big)
        found = call_words.problems(key, value)
        if found:
            raise _refuse("call_words_invalid", "That cannot be saved", " ".join(found))
    tried = call_words.trial(key, value)
    if tried.failures:
        raise _refuse(
            "call_words_breaks_check",
            "That would break a check",
            "It is valid on its own, but the check it is joined into no longer works: "
            f"{tried.failures[0][1]}.",
        )
    refused = await _postgres_refuses(session, tried.postgres_patterns)
    if refused is not None:
        raise _refuse(
            "call_words_postgres_refused",
            "That would break a search",
            f"This list is also searched in the database, which cannot read it: {refused}.",
        )
    current = (await store.latest(session)).get(key)
    shipped = call_words.shipped()[key]
    in_force = current.value if current is not None and current.value is not None else shipped
    if (shipped if value is None else value) == in_force:
        raise ProblemError(
            kind="conflict",
            code="call_words_unchanged",
            title="Nothing to save",
            detail="That is what the checks already listen for.",
        )
    note = payload.note.strip() if payload.note and payload.note.strip() else None
    revision = await store.add_revision(
        session, key=key, value=value, note=note, actor_id=principal.user_id
    )
    await write_audit(
        session,
        action="platform.call_words_reset" if value is None else "platform.call_words_changed",
        actor=principal,
        object_type="call_word_revisions",
        object_id=str(revision.seq),
        ip=client_request_ip(request),
        summary={"entry_key": key},
    )
    # This process uses the new words at once; every other within its poll.
    tasks.add_task(store.refresh_call_words)
    return await _detail(session, key)


__all__ = ["change_confirmation", "router"]
