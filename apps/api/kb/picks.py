"""The sources from What your agents know that a piece of work is written from: an inbound
line's (`inbound_line_sources`, D-997) and a campaign's (`campaign_sources`). One reader and
one writer for both, so a line and a campaign resolve a pick the same way.

A pick names a `kb_sources` row. A typed note gets a new row on every edit, so a picked note
is read as its newest version (by name); a file or link keeps its row, so its id stands.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: Most sources one piece of work may pick; the pick list's own request bound.
MAX_PICKS: Final = 200


@dataclass(frozen=True)
class PickTable:
    """A picks table and the column naming its holder. Only the constants below exist, so
    the names interpolated into SQL are never input."""

    table: str
    holder: str


LINE_PICKS: Final = PickTable("inbound_line_sources", "inbound_line_id")
CAMPAIGN_PICKS: Final = PickTable("campaign_sources", "campaign_id")


async def read_picks(
    session: AsyncSession, picks: PickTable, holder_ids: list[UUID]
) -> dict[UUID, list[UUID]]:
    """Each holder's picked source ids, in the order they were picked. RLS scopes it."""
    found: dict[UUID, list[UUID]] = defaultdict(list)
    if not holder_ids:
        return found
    for holder_id, source_id in (
        await session.execute(
            text(
                # Only a picked typed note follows its name: a file or link picked keeps
                # its own row even when a typed note happens to share its name.
                f"SELECT p.{picks.holder}, COALESCE((SELECT n.id FROM kb_sources n "
                "WHERE s.kind = 'text' AND NOT EXISTS "
                "(SELECT 1 FROM kb_uploads w WHERE w.source_id = s.id) "
                "AND n.name = s.name AND n.kind = 'text' AND NOT EXISTS "
                "(SELECT 1 FROM kb_uploads u WHERE u.source_id = n.id) "
                "ORDER BY n.version DESC, n.id DESC LIMIT 1), p.kb_source_id) "
                f"FROM {picks.table} p JOIN kb_sources s ON s.id = p.kb_source_id "
                f"WHERE p.{picks.holder} = ANY(:ids) ORDER BY p.created_at, p.id"
            ),
            {"ids": holder_ids},
        )
    ).all():
        found[holder_id].append(source_id)
    return found


async def _refuse_unknown(session: AsyncSession, wanted: list[UUID]) -> None:
    """A source of another account is invisible under RLS and refused as missing."""
    if not wanted:
        return
    found = set(
        (
            await session.execute(
                text("SELECT id FROM kb_sources WHERE id = ANY(:ids)"), {"ids": wanted}
            )
        ).scalars()
    )
    if found != set(wanted):
        raise ProblemError.not_found("Source")


async def replace_picks(
    session: AsyncSession,
    picks: PickTable,
    *,
    tenant_id: UUID,
    holder_id: UUID,
    kb_source_ids: list[UUID],
    created_by: UUID | None,
) -> None:
    """The holder's picks become exactly `kb_source_ids`. The caller holds the holder's lock."""
    wanted = list(dict.fromkeys(kb_source_ids))
    await _refuse_unknown(session, wanted)
    await session.execute(
        text(f"DELETE FROM {picks.table} WHERE {picks.holder} = :hid"), {"hid": holder_id}
    )
    for source_id in wanted:
        await _insert(session, picks, tenant_id, holder_id, source_id, created_by)


async def add_pick(
    session: AsyncSession,
    picks: PickTable,
    *,
    tenant_id: UUID,
    holder_id: UUID,
    kb_source_id: UUID,
    created_by: UUID | None,
) -> None:
    """Pick one more source, keeping the others; picking one twice is a no-op. Past
    `MAX_PICKS` it is refused, the bound a replace already has from its request model."""
    await _refuse_unknown(session, [kb_source_id])
    count = (
        await session.execute(
            text(
                f"SELECT count(*) FILTER (WHERE kb_source_id <> :s), "
                f"bool_or(kb_source_id = :s) FROM {picks.table} WHERE {picks.holder} = :hid"
            ),
            {"hid": holder_id, "s": kb_source_id},
        )
    ).one()
    if not count[1] and int(count[0]) >= MAX_PICKS:
        raise ProblemError.business_rule(
            "sources_full",
            f"This already uses {MAX_PICKS} sources.",
            remediation="Untick a source it no longer needs, then add this one.",
        )
    await _insert(session, picks, tenant_id, holder_id, kb_source_id, created_by)


async def _insert(
    session: AsyncSession,
    picks: PickTable,
    tenant_id: UUID,
    holder_id: UUID,
    source_id: UUID,
    created_by: UUID | None,
) -> None:
    await session.execute(
        text(
            f"INSERT INTO {picks.table} (id, tenant_id, {picks.holder}, kb_source_id, "
            "created_by) VALUES (:id, :t, :hid, :s, :by) ON CONFLICT DO NOTHING"
        ),
        {"id": uuid7(), "t": tenant_id, "hid": holder_id, "s": source_id, "by": created_by},
    )


__all__ = [
    "CAMPAIGN_PICKS",
    "LINE_PICKS",
    "MAX_PICKS",
    "PickTable",
    "add_pick",
    "read_picks",
    "replace_picks",
]
