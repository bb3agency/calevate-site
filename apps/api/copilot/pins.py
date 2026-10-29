"""Dashboard pins (D-934): Pip's charts kept on the client home and the admin home.

A pin is the chart's NAME and ARGUMENTS, never its figures; `card` re-runs it under the
viewer's own session and role (`charts.build_in`), so a card an owner pinned shows a staff
member a refusal rather than the owner's spend.

The client table is the account's, shared by everyone on it (FORCEd RLS: the session is the
tenancy). The admin table is the operators', platform-scoped. One set of functions serves
both, keyed by `PinRealm`; the table name is chosen from a constant, never from input.

Removing a pin stamps `removed_at` rather than deleting, so the Undo in the toast and in
Pip's receipt is an exact restore of the same row in the same place. A removed row is purged
the next time a pin is added, a day later.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import charts
from apps.api.copilot.chart_spec import ChartArgs
from apps.api.copilot.pin_models import MAX_PIN_TITLE
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

PinRealm = Literal["client", "admin"]

#: The most cards one home holds. A home is read at a glance; past a dozen it is a report.
MAX_PINS: Final = 12

_TABLE: Final[dict[PinRealm, str]] = {
    "client": "dashboard_pins",
    "admin": "admin_dashboard_pins",
}
_COLUMNS: Final = "id, chart, args, title, position, created_at, removed_at"


@dataclass(frozen=True, slots=True)
class PinRow:
    id: UUID
    chart: str
    args: ChartArgs
    title: str
    position: int
    created_at: datetime
    removed_at: datetime | None


def _row(r: Any) -> PinRow:
    raw = r.args if isinstance(r.args, dict) else json.loads(r.args)
    return PinRow(
        id=r.id,
        chart=str(r.chart),
        args=charts.chart_args(raw),
        title=str(r.title),
        position=int(r.position),
        created_at=r.created_at,
        removed_at=r.removed_at,
    )


def _not_found() -> ProblemError:
    return ProblemError.not_found("Pinned card")


def clean_title(title: str) -> str:
    cleaned = " ".join(strip_invisible(title).split())[:MAX_PIN_TITLE].strip()
    if not cleaned:
        raise ProblemError(
            kind="validation",
            code="pin_title_blank",
            title="Give the card a name",
            detail="A pinned card needs a name of at least one character.",
            remediation="Type a name and save again.",
        )
    return cleaned


async def list_pins(session: AsyncSession, realm: PinRealm) -> list[PinRow]:
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM {_TABLE[realm]} WHERE removed_at IS NULL "
            "ORDER BY position, created_at, id LIMIT :n"
        ),
        {"n": MAX_PINS},
    )
    return [_row(r) for r in rows]


async def get_pin(session: AsyncSession, realm: PinRealm, pin_id: UUID) -> PinRow:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM {_TABLE[realm]} WHERE id = :id"), {"id": pin_id}
        )
    ).first()
    if row is None:
        raise _not_found()
    return _row(row)


async def find_by_title(session: AsyncSession, realm: PinRealm, title: str) -> PinRow | None:
    """The one live pin with this title, ignoring case; None when none. Refuses two."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM {_TABLE[realm]} WHERE removed_at IS NULL "
                "AND lower(title) = lower(:t) LIMIT 2"
            ),
            {"t": " ".join(title.split())},
        )
    ).all()
    if len(rows) > 1:
        raise ProblemError(
            kind="conflict",
            code="pin_title_ambiguous",
            title="Two cards share that name",
            detail="More than one pinned card has that name.",
            remediation="Remove the one you mean from the home screen.",
        )
    return _row(rows[0]) if rows else None


async def add_pin(
    session: AsyncSession,
    realm: PinRealm,
    *,
    tenant_id: UUID | None,
    created_by: UUID | None,
    chart: str,
    args: Mapping[str, Any],
    title: str,
) -> PinRow:
    """Pin a chart at the end of the home. Refuses an unknown chart and a full home.

    A transaction lock per account (or for the admin home) makes the count-then-insert
    one step, so two tabs pinning at once cannot pass the cap together."""
    try:
        charts.ability(chart, realm)
    except charts.ChartRefusedError:
        raise ProblemError(
            kind="validation",
            code="pin_chart_unknown",
            title="That chart can't be pinned here",
            detail="This home has no chart of that name.",
            remediation="Pin a chart from the assistant on this console.",
        ) from None
    parsed = charts.chart_args(args)
    name = clean_title(title)
    table = _TABLE[realm]
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{table}:{tenant_id or 'platform'}"},
    )
    await session.execute(
        text(
            f"DELETE FROM {table} WHERE removed_at IS NOT NULL "
            "AND removed_at < now() - interval '1 day'"
        )
    )
    count, last = (
        await session.execute(
            text(
                f"SELECT count(*), COALESCE(max(position), -1) FROM {table} "
                "WHERE removed_at IS NULL"
            )
        )
    ).one()
    if int(count) >= MAX_PINS:
        raise ProblemError(
            kind="conflict",
            code="pin_limit",
            title="Your home is full",
            detail=f"A home holds {MAX_PINS} cards.",
            remediation="Remove a card you no longer need, then pin this one.",
        )
    values: dict[str, Any] = {
        "id": uuid7(),
        "by": created_by,
        "chart": chart,
        "args": json.dumps(parsed.model_dump()),
        "title": name,
        "pos": min(int(last) + 1, 99),
    }
    columns = "id, created_by, chart, args, title, position"
    binds = ":id, :by, :chart, CAST(:args AS jsonb), :title, :pos"
    if realm == "client":
        columns, binds = f"tenant_id, {columns}", f":tid, {binds}"
        values["tid"] = tenant_id
    row = (
        await session.execute(
            text(f"INSERT INTO {table} ({columns}) VALUES ({binds}) RETURNING {_COLUMNS}"),
            values,
        )
    ).one()
    return _row(row)


async def rename_pin(session: AsyncSession, realm: PinRealm, pin_id: UUID, title: str) -> PinRow:
    row = (
        await session.execute(
            text(
                f"UPDATE {_TABLE[realm]} SET title = :title, updated_at = now() "
                f"WHERE id = :id AND removed_at IS NULL RETURNING {_COLUMNS}"
            ),
            {"id": pin_id, "title": clean_title(title)},
        )
    ).first()
    if row is None:
        raise _not_found()
    return _row(row)


async def reorder_pins(session: AsyncSession, realm: PinRealm, ids: Sequence[UUID]) -> list[PinRow]:
    """Put the live pins in this order. Every live pin must be named exactly once, so a
    stale tab cannot drop a card a colleague added meanwhile."""
    live = await list_pins(session, realm)
    if sorted(map(str, ids)) != sorted(str(p.id) for p in live):
        raise ProblemError(
            kind="conflict",
            code="pin_order_stale",
            title="The cards changed",
            detail="Someone added or removed a card while you were moving them.",
            remediation="Reload the page and move them again.",
        )
    await session.execute(
        text(
            f"UPDATE {_TABLE[realm]} p SET position = o.position, updated_at = now() "
            "FROM unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS o(id, position) "
            "WHERE p.id = o.id"
        ),
        {"ids": [str(i) for i in ids]},
    )
    return await list_pins(session, realm)


async def remove_pin(session: AsyncSession, realm: PinRealm, pin_id: UUID) -> PinRow:
    row = (
        await session.execute(
            text(
                f"UPDATE {_TABLE[realm]} SET removed_at = now(), updated_at = now() "
                f"WHERE id = :id AND removed_at IS NULL RETURNING {_COLUMNS}"
            ),
            {"id": pin_id},
        )
    ).first()
    if row is None:
        raise _not_found()
    return _row(row)


async def restore_pin(session: AsyncSession, realm: PinRealm, pin_id: UUID) -> PinRow:
    """Undo a removal: the same row, in the same place. Refused past the cap."""
    live = await list_pins(session, realm)
    if len(live) >= MAX_PINS:
        raise ProblemError(
            kind="conflict",
            code="pin_limit",
            title="Your home is full",
            detail=f"A home holds {MAX_PINS} cards.",
            remediation="Remove a card you no longer need, then put this one back.",
        )
    row = (
        await session.execute(
            text(
                f"UPDATE {_TABLE[realm]} SET removed_at = NULL, updated_at = now() "
                f"WHERE id = :id AND removed_at IS NOT NULL RETURNING {_COLUMNS}"
            ),
            {"id": pin_id},
        )
    ).first()
    if row is None:
        raise _not_found()
    return _row(row)


__all__ = [
    "MAX_PINS",
    "PinRealm",
    "PinRow",
    "add_pin",
    "clean_title",
    "find_by_title",
    "get_pin",
    "list_pins",
    "remove_pin",
    "rename_pin",
    "reorder_pins",
    "restore_pin",
]
