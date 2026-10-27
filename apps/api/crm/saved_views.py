"""Saved views — "Hot this week", stored (SURFACES §2), and resolved on every read.

A saved view is a NAME over a filter set and a column selection. Everything interesting
about it is what happens when the thing it points at changes: an admin edits the agent's
extraction schema (D-21 makes that admin-only, so the client cannot even see it coming),
and a view pinned to a field that no longer exists has to keep working.

**How the industry handles that, and why we do it differently.** Jira's documented
behaviour when a custom field is deleted is that filters, boards and automation rules
that referenced it break, and a separate integrity checker cleans up the dangling
references afterwards (confluence.atlassian.com/adminjiraserver/
editing-or-deleting-custom-fields-1047552719.html; jira.atlassian.com/browse/JRA-4423).
That is the standard, and it is beatable for free: a view is RESOLVED against the current
schema every time it is read, so a dead reference becomes a missing filter and a sentence
on screen rather than a 500 and a repair job. Nothing is rewritten in the row — an admin
who restores the field restores the view with it, which a destructive cleanup could not.

**A dead FILTER is reported, never silently applied-as-nothing.** Dropping a filter
WIDENS the set: somebody narrows the table to eleven leads, presses Export and mails a
supplier the whole contact list. So `stale_filter_keys` comes back beside the pruned
filters and the screen says so out loud. A dead COLUMN only narrows the table, and the
screen and the file drop it identically (`crm.columns`), so it is reported without
ceremony.

**Tenancy.** Rows are isolated by the FORCEd `tenant_isolation` policy on
`lead_saved_views` (migration a7e2c40d9b53). RLS answers "which tenant" and NEVER "which
person" — `users` is global and carries no policy — so every statement here also carries
an explicit `user_id` predicate. That is not a belt over the policy's braces; it is the
only thing making a view private.

**Two screens, one table.** The Leads table and the Calls log both save views (`screen`,
migration e5a1c7d93b20); a name is unique per person per screen, and the cap counts each
screen on its own. A day range is fixed days or "the last N days" (`schemas.ViewDaysIn`),
answered on every read with the India days it covers that day.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.crm import columns as lead_column_registry
from apps.api.crm.schemas import (
    MAX_SAVED_VIEWS_PER_USER,
    CallSavedViewIn,
    CallSavedViewOut,
    CallSavedViewUpdateIn,
    CallViewFilters,
    SavedViewFilters,
    SavedViewIn,
    SavedViewOut,
    SavedViewUpdateIn,
)
from apps.api.crm.service import lead_columns
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import session_tenant

Screen = Literal["leads", "calls"]

_ROW = "id, name, filters, columns, created_at, updated_at"


def _today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class _SchemaCache:
    """Per-request memo of "what columns does agent X have".

    Views on one account usually pin the same one or two agents, and resolving each view
    against a fresh `SELECT fields FROM extraction_schemas` would make a list of twenty
    views twenty queries. Scoped to a single call so it can never outlive the session
    whose RLS scope made it correct.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._by_agent: dict[UUID | None, tuple[lead_column_registry.LeadColumn, ...]] = {}

    async def columns(self, agent_id: UUID | None) -> tuple[lead_column_registry.LeadColumn, ...]:
        if agent_id not in self._by_agent:
            fields = await lead_columns(self._session, agent_id)
            self._by_agent[agent_id] = lead_column_registry.available(fields)
        return self._by_agent[agent_id]


async def _resolve(row: Any, schemas: _SchemaCache) -> SavedViewOut:
    """One stored row → what the screen may act on, with the dead references named."""
    stored = SavedViewFilters.model_validate(row.filters or {})
    available = await schemas.columns(stored.agent_id)
    facet_keys = {c.key for c in lead_column_registry.facetable(available)}

    live_fields = {k: v for k, v in stored.fields.items() if k in facet_keys}
    stale_filters = sorted(k for k in stored.fields if k not in facet_keys)
    resolved = lead_column_registry.resolve(available, row.columns)
    today = _today()

    return SavedViewOut(
        id=row.id,
        name=row.name,
        filters=stored.model_copy(
            update={
                "fields": live_fields,
                "created": stored.created.resolved(today) if stored.created else None,
                "last_call": stored.last_call.resolved(today) if stored.last_call else None,
            }
        ),
        # `row.columns` is echoed through the resolver so the view's own order survives,
        # and `None` stays `None` — "no choice made" is not the same as "chose all of
        # them", because the second one freezes a client out of a column added tomorrow.
        columns=[c.key for c in resolved.columns] if row.columns else None,
        stale_filter_keys=stale_filters,
        stale_column_keys=list(resolved.dropped),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _resolve_call(row: Any) -> CallSavedViewOut:
    stored = CallViewFilters.model_validate(row.filters or {})
    return CallSavedViewOut(
        id=row.id,
        name=row.name,
        filters=stored.model_copy(
            update={"when": stored.when.resolved(_today()) if stored.when else None}
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _rows(session: AsyncSession, *, user_id: UUID, screen: Screen) -> list[Any]:
    """This person's views of one screen, oldest first.

    Oldest first, not newest: a picker whose entries move every time somebody adds one is
    a picker where muscle memory is wrong. New views land at the bottom.
    """
    return list(
        (
            await session.execute(
                text(
                    f"SELECT {_ROW} FROM lead_saved_views WHERE user_id = :uid "
                    "AND screen = :screen ORDER BY created_at ASC, id ASC"
                ),
                {"uid": user_id, "screen": screen},
            )
        ).all()
    )


async def _row(session: AsyncSession, view_id: UUID, *, user_id: UUID, screen: Screen) -> Any:
    row = (
        await session.execute(
            text(
                f"SELECT {_ROW} FROM lead_saved_views WHERE id = :vid AND user_id = :uid "
                "AND screen = :screen"
            ),
            {"vid": view_id, "uid": user_id, "screen": screen},
        )
    ).first()
    if row is None:
        # Same answer for "no such view" and "somebody else's view", deliberately — the
        # second one is not a fact this caller is entitled to.
        raise ProblemError.not_found("Saved view")
    return row


def _name_taken(name: str) -> ProblemError:
    return ProblemError.conflict(
        "saved_view_name_taken",
        f"You already have a view called “{name}”.",
        remediation="Pick a different name, or open the existing view and update it.",
    )


async def _create(
    session: AsyncSession,
    *,
    user_id: UUID,
    screen: Screen,
    name: str,
    filters_json: str,
    columns_json: str | None,
) -> UUID:
    tenant_id = await session_tenant(session)
    # Count and insert are one critical section per person: without it, saves racing at
    # one under the cap each read the same count and each insert (BACKEND-PATTERNS §5 —
    # an advisory xact lock, released by the COMMIT or ROLLBACK that decides the row).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"saved-views:{tenant_id}:{user_id}:{screen}"},
    )
    used = (
        await session.execute(
            text("SELECT count(*) FROM lead_saved_views WHERE user_id = :uid AND screen = :s"),
            {"uid": user_id, "s": screen},
        )
    ).scalar_one()
    if int(used) >= MAX_SAVED_VIEWS_PER_USER:
        raise ProblemError.business_rule(
            "saved_view_limit_reached",
            f"You already have {MAX_SAVED_VIEWS_PER_USER} saved views on this screen.",
            remediation="Delete a view you no longer use, then save this one again.",
        )
    view_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO lead_saved_views (id, tenant_id, user_id, screen, name, filters, "
                "columns, created_at, updated_at) VALUES (:id, :tid, :uid, :screen, :name, "
                "CAST(:filters AS jsonb), CAST(:columns AS jsonb), now(), now())"
            ),
            {
                "id": view_id,
                "tid": tenant_id,
                "uid": user_id,
                "screen": screen,
                "name": name,
                "filters": filters_json,
                "columns": columns_json,
            },
        )
        # The UNIQUE is checked at statement time, but the flush is what surfaces it as
        # an IntegrityError here rather than at commit, where the route's error ladder
        # can no longer tell it from any other failure.
        await session.flush()
    except IntegrityError as exc:  # UNIQUE(tenant_id, user_id, screen, name)
        raise _name_taken(name) from exc
    return view_id


async def _update(
    session: AsyncSession,
    view_id: UUID,
    *,
    user_id: UUID,
    screen: Screen,
    sets: dict[str, Any],
) -> None:
    """One UPDATE of the given columns. The `user_id` predicate is in the WHERE clause
    rather than checked first: a read-then-write would answer "not found" for another
    person's view either way, and the single statement cannot be raced into editing a row
    this caller does not own."""
    if not sets:
        await _row(session, view_id, user_id=user_id, screen=screen)
        return
    # One statement for every combination: an omitted name or filters keeps its column
    # (COALESCE), and `columns` is written only when given, since NULL is a real value there.
    try:
        result = await session.execute(
            text(
                "UPDATE lead_saved_views SET name = COALESCE(:name, name), "
                "filters = COALESCE(CAST(:filters AS jsonb), filters), "
                "columns = CASE WHEN :set_columns THEN CAST(:columns AS jsonb) ELSE columns END, "
                "updated_at = now() WHERE id = :vid AND user_id = :uid AND screen = :screen"
            ),
            {
                "name": sets.get("name"),
                "filters": sets.get("filters"),
                "set_columns": "columns" in sets,
                "columns": sets.get("columns"),
                "vid": view_id,
                "uid": user_id,
                "screen": screen,
            },
        )
    except IntegrityError as exc:
        raise _name_taken(str(sets.get("name", ""))) from exc
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Saved view")


async def _delete(session: AsyncSession, view_id: UUID, *, user_id: UUID, screen: Screen) -> None:
    result = await session.execute(
        text(
            "DELETE FROM lead_saved_views WHERE id = :vid AND user_id = :uid AND screen = :screen"
        ),
        {"vid": view_id, "uid": user_id, "screen": screen},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Saved view")


# --- the Leads table ---------------------------------------------------------------------


async def list_views(session: AsyncSession, *, user_id: UUID) -> list[SavedViewOut]:
    schemas = _SchemaCache(session)
    return [
        await _resolve(r, schemas) for r in await _rows(session, user_id=user_id, screen="leads")
    ]


async def create_view(
    session: AsyncSession, *, user_id: UUID, payload: SavedViewIn
) -> SavedViewOut:
    view_id = await _create(
        session,
        user_id=user_id,
        screen="leads",
        name=payload.name.strip(),
        filters_json=payload.filters.model_dump_json(),
        columns_json=_columns_json(payload.columns),
    )
    return await get_view(session, view_id, user_id=user_id)


async def update_view(
    session: AsyncSession, view_id: UUID, *, user_id: UUID, payload: SavedViewUpdateIn
) -> SavedViewOut:
    """Rename or re-pin. An omitted field is left alone; `columns: []` clears the choice."""
    sets: dict[str, Any] = {}
    if payload.name is not None:
        sets["name"] = payload.name.strip()
    if payload.filters is not None:
        sets["filters"] = payload.filters.model_dump_json()
    if payload.columns is not None:
        sets["columns"] = _columns_json(payload.columns)
    await _update(session, view_id, user_id=user_id, screen="leads", sets=sets)
    return await get_view(session, view_id, user_id=user_id)


async def delete_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> None:
    await _delete(session, view_id, user_id=user_id, screen="leads")


async def get_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> SavedViewOut:
    row = await _row(session, view_id, user_id=user_id, screen="leads")
    return await _resolve(row, _SchemaCache(session))


async def find_view(session: AsyncSession, *, user_id: UUID, name: str) -> SavedViewOut | None:
    """This person's Leads view of that name (exact, ignoring case and outer spaces)."""
    wanted = name.strip().casefold()
    for row in await _rows(session, user_id=user_id, screen="leads"):
        if str(row.name).casefold() == wanted:
            return await _resolve(row, _SchemaCache(session))
    return None


# --- the Calls log -----------------------------------------------------------------------


async def list_call_views(session: AsyncSession, *, user_id: UUID) -> list[CallSavedViewOut]:
    return [_resolve_call(r) for r in await _rows(session, user_id=user_id, screen="calls")]


async def create_call_view(
    session: AsyncSession, *, user_id: UUID, payload: CallSavedViewIn
) -> CallSavedViewOut:
    view_id = await _create(
        session,
        user_id=user_id,
        screen="calls",
        name=payload.name.strip(),
        filters_json=payload.filters.model_dump_json(),
        columns_json=None,
    )
    return await get_call_view(session, view_id, user_id=user_id)


async def update_call_view(
    session: AsyncSession, view_id: UUID, *, user_id: UUID, payload: CallSavedViewUpdateIn
) -> CallSavedViewOut:
    sets: dict[str, Any] = {}
    if payload.name is not None:
        sets["name"] = payload.name.strip()
    if payload.filters is not None:
        sets["filters"] = payload.filters.model_dump_json()
    await _update(session, view_id, user_id=user_id, screen="calls", sets=sets)
    return await get_call_view(session, view_id, user_id=user_id)


async def delete_call_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> None:
    await _delete(session, view_id, user_id=user_id, screen="calls")


async def get_call_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> CallSavedViewOut:
    return _resolve_call(await _row(session, view_id, user_id=user_id, screen="calls"))


def _columns_json(columns: list[str] | None) -> str | None:
    """`[]` and `None` both mean "no column choice"; the CHECK allows only one of them.

    Normalised here rather than in the model so the two write paths cannot disagree —
    `SavedViewUpdateIn` uses `[]` as its CLEAR signal precisely because `None` already
    means "unchanged" there.
    """
    if not columns:
        return None
    return json.dumps(columns)


__all__ = [
    "Screen",
    "create_call_view",
    "create_view",
    "delete_call_view",
    "delete_view",
    "find_view",
    "get_call_view",
    "get_view",
    "list_call_views",
    "list_views",
    "update_call_view",
    "update_view",
]
