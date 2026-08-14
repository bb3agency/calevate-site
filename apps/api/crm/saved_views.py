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
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.crm import columns as lead_column_registry
from apps.api.crm.schemas import (
    MAX_SAVED_VIEWS_PER_USER,
    SavedViewFilters,
    SavedViewIn,
    SavedViewOut,
    SavedViewUpdateIn,
)
from apps.api.crm.service import lead_columns
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import session_tenant

_ROW = "id, name, filters, columns, created_at, updated_at"


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

    return SavedViewOut(
        id=row.id,
        name=row.name,
        filters=stored.model_copy(update={"fields": live_fields}),
        # `row.columns` is echoed through the resolver so the view's own order survives,
        # and `None` stays `None` — "no choice made" is not the same as "chose all of
        # them", because the second one freezes a client out of a column added tomorrow.
        columns=[c.key for c in resolved.columns] if row.columns else None,
        stale_filter_keys=stale_filters,
        stale_column_keys=list(resolved.dropped),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_views(session: AsyncSession, *, user_id: UUID) -> list[SavedViewOut]:
    """This person's views on this account, oldest first.

    Oldest first, not newest: a picker whose entries move every time somebody adds one is
    a picker where muscle memory is wrong. New views land at the bottom.
    """
    rows = (
        await session.execute(
            text(
                f"SELECT {_ROW} FROM lead_saved_views WHERE user_id = :uid "
                "ORDER BY created_at ASC, id ASC"
            ),
            {"uid": user_id},
        )
    ).all()
    schemas = _SchemaCache(session)
    return [await _resolve(r, schemas) for r in rows]


async def create_view(
    session: AsyncSession, *, user_id: UUID, payload: SavedViewIn
) -> SavedViewOut:
    tenant_id = await session_tenant(session)
    used = (
        await session.execute(
            text("SELECT count(*) FROM lead_saved_views WHERE user_id = :uid"), {"uid": user_id}
        )
    ).scalar_one()
    if int(used) >= MAX_SAVED_VIEWS_PER_USER:
        raise ProblemError.business_rule(
            "saved_view_limit_reached",
            f"You already have {MAX_SAVED_VIEWS_PER_USER} saved views on this account.",
            remediation="Delete a view you no longer use, then save this one again.",
        )
    view_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO lead_saved_views (id, tenant_id, user_id, name, filters, columns, "
                "created_at, updated_at) VALUES (:id, :tid, :uid, :name, CAST(:filters AS jsonb), "
                "CAST(:columns AS jsonb), now(), now())"
            ),
            {
                "id": view_id,
                "tid": tenant_id,
                "uid": user_id,
                "name": payload.name.strip(),
                "filters": payload.filters.model_dump_json(),
                "columns": _columns_json(payload.columns),
            },
        )
        # The UNIQUE is checked at statement time, but the flush is what surfaces it as
        # an IntegrityError here rather than at commit, where the route's error ladder
        # can no longer tell it from any other failure.
        await session.flush()
    except IntegrityError as exc:  # UNIQUE(tenant_id, user_id, name)
        raise ProblemError.conflict(
            "saved_view_name_taken",
            f"You already have a view called “{payload.name.strip()}”.",
            remediation="Pick a different name, or open the existing view and update it.",
        ) from exc
    return await get_view(session, view_id, user_id=user_id)


async def update_view(
    session: AsyncSession, view_id: UUID, *, user_id: UUID, payload: SavedViewUpdateIn
) -> SavedViewOut:
    """Rename or re-pin. An omitted field is left alone; `columns: []` clears the choice.

    The `user_id` predicate is in the WHERE clause rather than checked first: a
    read-then-write would answer "not found" for another person's view either way, and
    the single statement cannot be raced into editing a row this caller does not own.
    """
    sets: list[str] = []
    params: dict[str, Any] = {"vid": view_id, "uid": user_id}
    if payload.name is not None:
        sets.append("name = :name")
        params["name"] = payload.name.strip()
    if payload.filters is not None:
        sets.append("filters = CAST(:filters AS jsonb)")
        params["filters"] = payload.filters.model_dump_json()
    if payload.columns is not None:
        sets.append("columns = CAST(:columns AS jsonb)")
        params["columns"] = _columns_json(payload.columns)
    if not sets:
        return await get_view(session, view_id, user_id=user_id)
    try:
        result = await session.execute(
            text(
                f"UPDATE lead_saved_views SET {', '.join(sets)}, updated_at = now() "
                "WHERE id = :vid AND user_id = :uid"
            ),
            params,
        )
    except IntegrityError as exc:
        raise ProblemError.conflict(
            "saved_view_name_taken",
            "You already have a view with that name.",
            remediation="Pick a different name.",
        ) from exc
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Saved view")
    return await get_view(session, view_id, user_id=user_id)


async def delete_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> None:
    result = await session.execute(
        text("DELETE FROM lead_saved_views WHERE id = :vid AND user_id = :uid"),
        {"vid": view_id, "uid": user_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Saved view")


async def get_view(session: AsyncSession, view_id: UUID, *, user_id: UUID) -> SavedViewOut:
    row = (
        await session.execute(
            text(f"SELECT {_ROW} FROM lead_saved_views WHERE id = :vid AND user_id = :uid"),
            {"vid": view_id, "uid": user_id},
        )
    ).first()
    if row is None:
        # Same answer for "no such view" and "somebody else's view", deliberately — the
        # second one is not a fact this caller is entitled to.
        raise ProblemError.not_found("Saved view")
    return await _resolve(row, _SchemaCache(session))


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
    "create_view",
    "delete_view",
    "get_view",
    "list_views",
    "update_view",
]
