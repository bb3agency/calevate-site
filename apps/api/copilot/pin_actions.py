"""Pip's pin actions (D-934, area `reports`): keep a chart on the home, or take one off.

Both are `immediate` with Undo: a card is a shortcut to figures the person can already see,
it reaches no caller and spends nothing, and each has an exact inverse (`pins.remove_pin` /
`pins.restore_pin` on the same row). The home's buttons call the same functions through
`pin_routes.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import charts, pins
from apps.api.copilot.actions import (
    DOES_IT,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    Undo,
    UndoRecord,
    UndoRefusedError,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.pin_models import MAX_PIN_TITLE
from apps.api.core.errors import ProblemError

_WHERE: Final = "on the home screen"
_OBJECT: Final = "dashboard_pin"


class _PinArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart: str
    days: int | None = None
    title: Annotated[str, Field(min_length=1, max_length=MAX_PIN_TITLE)]


class _UnpinArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=MAX_PIN_TITLE)]


def _pin_id(args: Mapping[str, Any]) -> UUID | None:
    raw = args.get(f"{_OBJECT}_id")
    return UUID(str(raw)) if raw else None


async def _state(session: AsyncSession, pin_id: UUID | None) -> dict[str, Any]:
    if pin_id is None:
        return {}
    try:
        row = await pins.get_pin(session, "client", pin_id)
    except ProblemError:
        return {"removed": True}
    return {"removed": row.removed_at is not None}


# --- chart_pin -------------------------------------------------------------------------


async def _plan_pin(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_PinArgs, args)
    if parsed.chart not in charts.names("client"):
        raise WriteRefusedError("`chart` is not one of report_chart's charts")
    if len(await pins.list_pins(session, "client")) >= pins.MAX_PINS:
        raise WriteRefusedError(
            f"the home screen already holds {pins.MAX_PINS} cards; ask which to take off"
        )
    days = charts.chart_args({"days": parsed.days}).days
    title = " ".join(parsed.title.split())
    if not title:
        raise WriteRefusedError("`title` is blank")
    return Plan(
        object_id="",
        title="Pin a chart",
        summary=f"Keep “{title}” on the home screen, always up to date.",
        current=None,
        proposed=title,
        cost=None,
        reversal="Undo takes it off the home screen.",
        args={"chart": parsed.chart, "days": days, "title": title},
    )


async def _execute_pin(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_PinArgs, args)
    try:
        row = await pins.add_pin(
            session,
            "client",
            tenant_id=actor.tenant_id,
            created_by=actor.user_id,
            chart=parsed.chart,
            args={"days": parsed.days},
            title=parsed.title,
        )
    except ProblemError as refused:
        raise WriteRefusedError(f"{refused.detail} {refused.remediation or ''}".strip()) from None
    return Executed(
        applied=True,
        detail="Pinned to the home screen.",
        audit_summary={"chart": row.chart, "days": row.args.days},
        object_id=str(row.id),
    )


async def _capture_pin(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    return await _state(session, _pin_id(args))


async def _invert_pin(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    del actor
    try:
        await pins.remove_pin(session, "client", UUID(record.object_id))
    except ProblemError:
        raise UndoRefusedError("that card was already taken off the home screen") from None
    return "Taken off the home screen."


CHART_PIN: Final = ActionTool(
    name="chart_pin",
    tier="immediate",
    undo=Undo(capture=_capture_pin, invert=_invert_pin),
    permission="copilot:use",
    object_type=_OBJECT,
    audit_action="copilot.pin_added",
    where=_WHERE,
    schema=action_schema(
        "chart_pin",
        "Keep a report_chart chart on the home screen." + DOES_IT,
        {
            "chart": {"type": "string"},
            "days": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "title": {"type": "string"},
        },
    ),
    plan=_plan_pin,
    execute=_execute_pin,
)


# --- chart_unpin -----------------------------------------------------------------------


async def _find(session: AsyncSession, title: str) -> pins.PinRow:
    try:
        row = await pins.find_by_title(session, "client", title)
    except ProblemError as refused:
        raise WriteRefusedError(refused.detail) from None
    if row is None:
        raise WriteRefusedError("no card on the home screen has that name")
    return row


async def _plan_unpin(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    row = await _find(session, parse_args(_UnpinArgs, args).title)
    return Plan(
        object_id=str(row.id),
        title="Remove a card",
        summary=f"Take “{row.title}” off the home screen.",
        current=row.title,
        proposed="Not on the home screen",
        cost=None,
        reversal="Undo puts it back where it was.",
        args={"title": row.title},
    )


async def _execute_unpin(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    row = await _find(session, parse_args(_UnpinArgs, args).title)
    await pins.remove_pin(session, "client", row.id)
    return Executed(
        applied=True,
        detail="Taken off the home screen.",
        audit_summary={"chart": row.chart},
        object_id=str(row.id),
    )


async def _capture_unpin(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    pin_id = _pin_id(args)
    if pin_id is None:
        found = await pins.find_by_title(session, "client", str(args.get("title", "")))
        pin_id = None if found is None else found.id
    return await _state(session, pin_id)


async def _invert_unpin(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    del actor
    try:
        await pins.restore_pin(session, "client", UUID(record.object_id))
    except ProblemError as refused:
        raise UndoRefusedError(refused.detail) from None
    return "Back on the home screen."


CHART_UNPIN: Final = ActionTool(
    name="chart_unpin",
    tier="immediate",
    undo=Undo(capture=_capture_unpin, invert=_invert_unpin),
    permission="copilot:use",
    object_type=_OBJECT,
    audit_action="copilot.pin_removed",
    where=_WHERE,
    schema=action_schema(
        "chart_unpin",
        "Take a card off the home screen, by its name." + DOES_IT,
        {"title": {"type": "string"}},
    ),
    plan=_plan_unpin,
    execute=_execute_unpin,
)

PIN_ACTIONS: Final[tuple[ActionTool, ...]] = (CHART_PIN, CHART_UNPIN)

__all__ = ["CHART_PIN", "CHART_UNPIN", "PIN_ACTIONS"]
