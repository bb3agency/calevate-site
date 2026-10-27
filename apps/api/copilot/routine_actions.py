"""Pip's routines (D-893 L7, area `routines`): list, create, change (including switching
off and on) and delete the person's own repeating jobs.

Each calls the function the Routines screen's routes call (`copilot/routines.py`:
`list_routines`, `create_routine`, `update_routine`, `delete_routine`), and writes the same
audit actions. All three actions are `confirm`: a routine runs on its own later, so the
person sees its exact name, instruction and schedule before it exists or changes. Each run
still asks before acting (`write_tools.stage_for_approval`); nothing here changes that.

A routine is one person's (`copilot_routines.user_id`): the read is client-realm only,
because an operator in a view-as session has none in the account.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.copilot import routines
from apps.api.copilot.actions import (
    COPILOT_PERMISSION,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.memory import redacted_content
from apps.api.copilot.routine_models import MAX_ROUTINE_INSTRUCTION, MAX_ROUTINE_NAME
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.tools import ReadTool, ToolContext, _clean
from apps.api.core.errors import ProblemError

_WHERE: Final = "on the Assistant screen, under Routines"
_CLOCK: Final = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAY_NAMES: Final = dict(
    zip(routines.WEEKDAYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), strict=True)
)
#: Instruction characters a listing quotes per routine; the screen shows the whole text.
_LISTED_INSTRUCTION: Final = 160
_RUNS_ASK: Final = "Each run asks you before it calls anyone, spends or changes anything."

_DAYS: Final = {
    "anyOf": [
        {"type": "array", "items": {"type": "string", "enum": list(routines.WEEKDAYS)}},
        {"type": "null"},
    ]
}
_NULLABLE_STR: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _when(days: int, at_minute: int) -> str:
    named = routines.days_of(days)
    spoken = "every day" if len(named) == 7 else ", ".join(_DAY_NAMES[d] for d in named)
    return f"{spoken} at {at_minute // 60:02d}:{at_minute % 60:02d} IST"


def _ist(instant: datetime) -> str:
    return instant.astimezone(IST).strftime("%d %b %H:%M")


def _person(actor: ToolActor) -> UUID:
    # `actor_for` builds an actor only from a client-realm principal outside view-as here
    # (`assistant_closed_to` refuses an operator), so the user id is a `users.id`.
    return actor.user_id


def _schedule(days: list[str] | None, time: str | None) -> tuple[int | None, int | None]:
    mask = None
    if days is not None:
        if not days or len(set(days)) != len(days):
            raise WriteRefusedError("`days` lists each weekday it runs on, once")
        mask = routines.days_mask(days)
    minute = None
    if time is not None:
        if not _CLOCK.match(time):
            raise WriteRefusedError("`time` is 24-hour HH:MM in India time")
        minute = int(time[:2]) * 60 + int(time[3:])
    return mask, minute


def _clean_text(value: str) -> str:
    """What the routine will store, as `routines` stores it: redacted (D-788)."""
    return " ".join(redacted_content(strip_invisible(value)).split())


# --- routines_list (read) ------------------------------------------------------------


async def _routines_list(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`GET /v1/copilot/routines`' read: the asking person's routines."""
    del args
    if context.user_id is None:
        return "Routines belong to one signed-in person, and none is asking here."
    rows = await routines.list_routines(
        session, user_id=context.user_id, limit=routines.MAX_ROUTINES_PER_USER
    )
    if not rows:
        return f"This person has no routines yet. They are listed {_WHERE}."
    lines = [f"{len(rows)} routine(s), each [id]:"]
    for row in rows:
        state = f"on, next {_ist(row.next_run_at)}" if row.next_run_at else "switched off"
        # Only the person's words go through `_clean`: a masked read would otherwise
        # mistake the digits of the id for a phone number and hand back an id that is not.
        lines.append(
            f"- [{row.id}] {_clean(row.name)} · {_when(row.days, row.at_minute)} · {state}"
            + (f" · last ran {_ist(row.last_run_at)}" if row.last_run_at else "")
            + f" · does: {_clean(row.instruction[:_LISTED_INSTRUCTION])}"
        )
    return "\n".join(lines)


ROUTINES_LIST: Final = ReadTool(
    name="routines_list",
    description="Their routines: id, IST schedule, on or off, next run, what each does.",
    parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    permission=COPILOT_PERMISSION,
    run=_routines_list,
)


# --- routine_create (confirm) ------------------------------------------------------------


class _CreateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_NAME)]
    instruction: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_INSTRUCTION)]
    days: list[str]
    time: str


async def _plan_create(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del session, actor
    parsed = parse_args(_CreateArgs, args)
    mask, minute = _schedule(parsed.days, parsed.time)
    assert mask is not None and minute is not None
    name, instruction = (
        _clean_text(parsed.name),
        redacted_content(strip_invisible(parsed.instruction)).strip(),
    )
    if not name or not instruction:
        raise WriteRefusedError("`name` and `instruction` need words")
    return Plan(
        object_id="",
        title="Set up a routine",
        summary=f"“{name}”, {_when(mask, minute)}. {_RUNS_ASK}",
        current=None,
        proposed=instruction,
        cost=None,
        reversal="Switch it off, change it or delete it at any time.",
        args={
            "name": name,
            "instruction": instruction,
            "days": routines.days_of(mask),
            "time": f"{minute // 60:02d}:{minute % 60:02d}",
        },
    )


async def _execute_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_CreateArgs, args)
    mask, minute = _schedule(parsed.days, parsed.time)
    assert mask is not None and minute is not None
    row = await routines.create_routine(
        session,
        tenant_id=actor.tenant_id,
        user_id=_person(actor),
        name=parsed.name,
        instruction=parsed.instruction,
        days=mask,
        at_minute=minute,
        enabled=True,
        now=datetime.now(UTC),
    )
    assert row.next_run_at is not None
    return Executed(
        applied=True,
        detail=f"Set up. It first runs {_ist(row.next_run_at)} IST.",
        audit_summary={"days": row.days, "at_minute": row.at_minute, "enabled": row.enabled},
        object_id=str(row.id),
    )


ROUTINE_CREATE: Final = ActionTool(
    name="routine_create",
    tier="confirm",
    undo=None,
    permission=COPILOT_PERMISSION,
    object_type="copilot_routine",
    audit_action="copilot.routine_created",
    where=_WHERE,
    schema=action_schema(
        "routine_create",
        "A repeating job in the person's words, on weekdays at an IST time." + PROPOSES_ONLY,
        {
            "name": {"type": "string"},
            "instruction": {"type": "string"},
            "days": {"type": "array", "items": {"type": "string", "enum": list(routines.WEEKDAYS)}},
            "time": {"type": "string", "description": "HH:MM, 24-hour IST."},
        },
    ),
    plan=_plan_create,
    execute=_execute_create,
)


# --- routine_edit (confirm) --------------------------------------------------------------


class _EditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routine: UUID
    name: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_NAME)] | None = None
    instruction: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_INSTRUCTION)] | None = (
        None
    )
    days: list[str] | None = None
    time: str | None = None
    on: bool | None = None


async def _read(session: AsyncSession, actor: ToolActor, routine_id: UUID) -> routines.RoutineRow:
    try:
        return await routines.read_routine(session, routine_id=routine_id, user_id=_person(actor))
    except ProblemError:
        raise WriteRefusedError(
            "`routine` is not one of this person's; see routines_list"
        ) from None


async def _plan_edit(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_EditArgs, args)
    row = await _read(session, actor, parsed.routine)
    mask, minute = _schedule(parsed.days, parsed.time)
    name = None if parsed.name is None else _clean_text(parsed.name)
    instruction = (
        None
        if parsed.instruction is None
        else redacted_content(strip_invisible(parsed.instruction)).strip()
    )
    if name == "" or instruction == "":
        raise WriteRefusedError("`name` and `instruction` need words")
    if (
        mask is None
        and minute is None
        and name is None
        and instruction is None
        and parsed.on is None
    ):
        raise WriteRefusedError("say what changes: name, instruction, days, time or on")
    days, at = mask or row.days, row.at_minute if minute is None else minute
    on = row.enabled if parsed.on is None else parsed.on

    def described(n: str, d: int, m: int, enabled: bool) -> str:
        return f"“{n}”, {_when(d, m)}" + ("" if enabled else ", switched off")

    title = (
        "Switch a routine off"
        if parsed.on is False and row.enabled
        else "Switch a routine on"
        if parsed.on and not row.enabled
        else "Change a routine"
    )
    return Plan(
        object_id=str(row.id),
        title=title,
        summary=described(name or row.name, days, at, on) + (f". {_RUNS_ASK}" if on else "."),
        current=described(row.name, row.days, row.at_minute, row.enabled)
        + (f": {row.instruction}" if instruction is not None else ""),
        proposed=described(name or row.name, days, at, on)
        + (f": {instruction}" if instruction is not None else ""),
        cost=None,
        reversal="Change it back at any time.",
        args={
            "routine": str(row.id),
            "name": name,
            "instruction": instruction,
            "days": None if mask is None else routines.days_of(mask),
            "time": None if minute is None else f"{minute // 60:02d}:{minute % 60:02d}",
            "on": parsed.on,
        },
    )


async def _execute_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_EditArgs, args)
    mask, minute = _schedule(parsed.days, parsed.time)
    row = await routines.update_routine(
        session,
        routine_id=parsed.routine,
        user_id=_person(actor),
        name=parsed.name,
        instruction=parsed.instruction,
        days=mask,
        at_minute=minute,
        enabled=parsed.on,
        now=datetime.now(UTC),
    )
    return Executed(
        applied=True,
        detail=(
            f"Saved. It next runs {_ist(row.next_run_at)} IST."
            if row.next_run_at
            else "Saved. It is switched off and will not run."
        ),
        audit_summary={"days": row.days, "at_minute": row.at_minute, "enabled": row.enabled},
    )


ROUTINE_EDIT: Final = ActionTool(
    name="routine_edit",
    tier="confirm",
    undo=None,
    permission=COPILOT_PERMISSION,
    object_type="copilot_routine",
    audit_action="copilot.routine_updated",
    where=_WHERE,
    schema=action_schema(
        "routine_edit",
        "Change one of the person's routines; on false pauses it, true resumes. Only what "
        "changes; null keeps the rest." + PROPOSES_ONLY,
        {
            "routine": {"type": "string", "description": "Its id from routines_list."},
            "name": _NULLABLE_STR,
            "instruction": _NULLABLE_STR,
            "days": _DAYS,
            "time": _NULLABLE_STR,
            "on": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        },
    ),
    plan=_plan_edit,
    execute=_execute_edit,
)


# --- routine_delete (confirm) ------------------------------------------------------------


class _DeleteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routine: UUID


async def _plan_delete(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_DeleteArgs, args)
    row = await _read(session, actor, parsed.routine)
    return Plan(
        object_id=str(row.id),
        title="Delete a routine",
        summary=(
            f"Delete “{row.name}” and its run history. Tasks it already started keep "
            "running, and what they did stays in your activity log."
        ),
        current=f"{_when(row.days, row.at_minute)}: {row.instruction}",
        proposed="Deleted",
        cost=None,
        reversal="This cannot be undone; you would set the routine up again.",
        args={"routine": str(row.id)},
    )


async def _execute_delete(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_DeleteArgs, args)
    await routines.delete_routine(session, routine_id=parsed.routine, user_id=_person(actor))
    return Executed(applied=True, detail="Deleted.", audit_summary={})


ROUTINE_DELETE: Final = ActionTool(
    name="routine_delete",
    tier="confirm",
    undo=None,
    permission=COPILOT_PERMISSION,
    object_type="copilot_routine",
    audit_action="copilot.routine_deleted",
    where=_WHERE,
    schema=action_schema(
        "routine_delete",
        "Delete one of the person's routines and its run history." + PROPOSES_ONLY,
        {"routine": {"type": "string", "description": "Its id from routines_list."}},
    ),
    plan=_plan_delete,
    execute=_execute_delete,
)


#: Appended to `WRITE_TOOLS` in this order (wire order).
ROUTINE_ACTIONS: Final[tuple[ActionTool, ...]] = (ROUTINE_CREATE, ROUTINE_EDIT, ROUTINE_DELETE)
#: Composed into the CLIENT realm's reads only (`service.realm_read_tools`).
ROUTINE_READS: Final[tuple[ReadTool, ...]] = (ROUTINES_LIST,)

__all__ = [
    "ROUTINES_LIST",
    "ROUTINE_ACTIONS",
    "ROUTINE_CREATE",
    "ROUTINE_DELETE",
    "ROUTINE_EDIT",
    "ROUTINE_READS",
]
