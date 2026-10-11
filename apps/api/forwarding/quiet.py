"""A forwarded line that has gone quiet (D-746): calls normally arrive, and for three days none
have. The likeliest cause is the forward being switched off on the client's phone (a new SIM,
a reset handset, a carrier change), which nothing else in the product can see.

WHAT "NORMALLY GETS CALLS" MEANS, concretely: in the 14 days before the quiet stretch, the
client's agents took at least 6 inbound calls on at least 3 different IST days, not counting
forwarding tests. Fewer than that and three silent days are ordinary for the business, so
nothing is said. The window is the client's, not the line's, because our call record does
not reliably name which of the client's numbers was dialled.

ONCE PER EPISODE. The episode opens when a working line passes three days with no inbound
call; it is stamped on the line (`quiet_since`, `quiet_alerted_at`), the client sees one
notice in their attention queue for as long as it lasts, and operators get one alarm
(`forwarded_line_quiet`, attention). It closes when an inbound call arrives or a test finds
the forward working, and a new silence is a new episode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert, resolve_alert
from apps.api.core.logging import get_logger

log = get_logger(__name__)

QUIET_AFTER: Final = timedelta(days=3)
NORMAL_LOOKBACK: Final = timedelta(days=14)
NORMAL_MIN_CALLS: Final = 6
NORMAL_MIN_DAYS: Final = 3
ALARM: Final = "forwarded_line_quiet"

_INBOUND: Final = "c.direction = 'inbound' AND c.forwarding_test_id IS NULL"


async def last_inbound_at(session: AsyncSession) -> datetime | None:
    return (
        await session.execute(
            text(f"SELECT max(COALESCE(c.started_at, c.created_at)) FROM calls c WHERE {_INBOUND}")
        )
    ).scalar()


async def normally_gets_calls(session: AsyncSession, *, before: datetime) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT count(*), count(DISTINCT (COALESCE(c.started_at, c.created_at) "
                "AT TIME ZONE 'Asia/Kolkata')::date) FROM calls c "
                f"WHERE {_INBOUND} AND COALESCE(c.started_at, c.created_at) >= :since "
                "AND COALESCE(c.started_at, c.created_at) < :before"
            ),
            {"since": before - NORMAL_LOOKBACK, "before": before},
        )
    ).first()
    calls, days = (int(row[0]), int(row[1])) if row else (0, 0)
    return calls >= NORMAL_MIN_CALLS and days >= NORMAL_MIN_DAYS


async def sweep_tenant(
    session: AsyncSession, *, tenant_id: UUID, now: datetime | None = None
) -> str:
    """Open or close this client's quiet episodes. Returns what happened, for the sweep's log."""
    now = now or datetime.now(UTC)
    lines = (
        await session.execute(
            text(
                "SELECT id, quiet_since FROM forwarded_lines WHERE status = 'working' "
                "OR quiet_since IS NOT NULL"
            )
        )
    ).all()
    if not lines:
        return "no_lines"
    last = await last_inbound_at(session)
    outcome = "steady"
    for line_id, quiet_since in lines:
        if quiet_since is not None:
            if last is not None and last > quiet_since:
                await session.execute(
                    text(
                        "UPDATE forwarded_lines SET quiet_since = NULL, quiet_alerted_at = NULL, "
                        "updated_at = now() WHERE id = :id"
                    ),
                    {"id": line_id},
                )
                resolve_alert("CORE_LOGIC", ALARM, episode=str(line_id))
                outcome = "recovered"
            continue
        silent_since = last
        if silent_since is None or now - silent_since < QUIET_AFTER:
            continue
        if not await normally_gets_calls(session, before=silent_since):
            continue
        claimed = (
            await session.execute(
                text(
                    "UPDATE forwarded_lines SET quiet_since = :since, quiet_alerted_at = now(), "
                    "updated_at = now() WHERE id = :id AND quiet_since IS NULL RETURNING id"
                ),
                {"id": line_id, "since": silent_since},
            )
        ).first()
        if claimed is None:
            continue
        alert(
            "CORE_LOGIC",
            ALARM,
            detail=(
                "a client whose forwarded number normally brings calls has had no inbound call "
                "for three days; the forward on their own phone may have been switched off. "
                "They see a notice asking them to run the forwarding test again."
            ),
            episode=str(line_id),
            tenant_id=str(tenant_id),
        )
        outcome = "quiet"
    log.info("forwarding_quiet_swept", extra={"tenant_id": str(tenant_id), "outcome": outcome})
    return outcome


__all__ = [
    "ALARM",
    "NORMAL_LOOKBACK",
    "NORMAL_MIN_CALLS",
    "NORMAL_MIN_DAYS",
    "QUIET_AFTER",
    "last_inbound_at",
    "normally_gets_calls",
    "sweep_tenant",
]
