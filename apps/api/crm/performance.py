"""Performance analytics (teardown §5 feature floor, SURFACES §2).

The competitor's Performance tab is connect rate, a Calls→Connected→Qualified funnel,
outcome splits, and busiest hours. All of it is derivable from `calls` and `leads`
rows we already write, so this module is queries and definitions — no new tables, no
new writes.

The definitions matter more than the SQL and are stated here once:

- **Connected** = the call reached a conversation: status `completed`, OR a duration
  above zero on a call that later dropped. `no_answer`/`busy`/`failed`/`voicemail` are
  dials, not conversations, and counting voicemail as "connected" is how a competitor
  demo inflates its connect rate. The status exclusion is the load-bearing half: an
  answering machine gives a `voicemail` a perfectly real duration, so "duration > 0"
  alone readmits exactly the calls the definition rules out.
- **Qualified** = the LEAD moved past `new` (contacted/interested/hot/won). Lead-level,
  not call-level: three calls that qualify one lead are one qualified outcome, and the
  funnel exists to show conversion, not activity.
- **Busiest hours are IST.** The histogram exists so the owner can staff the counter
  and pick campaign windows; a UTC histogram of an Indian business day is off by 5.5
  hours, which is worse than no histogram.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Statuses that are a dial and never a conversation, whatever the clock says.
DIAL_ONLY_STATUSES = ("no_answer", "busy", "failed", "voicemail")
CONNECTED_SQL = (
    "(status = 'completed' OR (duration_s IS NOT NULL AND duration_s > 0 "
    f"AND status NOT IN {DIAL_ONLY_STATUSES!r}))"
)
QUALIFIED_STATUSES = ("contacted", "interested", "hot", "won")

# `started_at` is `timestamptz`; EXTRACT renders one in the SESSION's TimeZone, so
# shifting by a fixed interval only yields IST on a database that happens to be set to
# UTC. `AT TIME ZONE` names the zone we mean and is correct on any of them.
IST_HOUR_SQL = "EXTRACT(HOUR FROM started_at AT TIME ZONE 'Asia/Kolkata')"


async def performance(session: AsyncSession, *, days: int = 30) -> dict[str, Any]:
    """The whole tab in three aggregate queries over tenant-scoped tables."""
    days = max(1, min(days, 365))
    since = datetime.now(UTC) - timedelta(days=days)

    funnel_row = (
        await session.execute(
            text(
                "SELECT count(*) AS calls, "
                f"  count(*) FILTER (WHERE {CONNECTED_SQL}) AS connected, "
                "  count(*) FILTER (WHERE direction = 'inbound') AS inbound, "
                "  count(*) FILTER (WHERE direction = 'outbound') AS outbound, "
                "  avg(duration_s) FILTER (WHERE status = 'completed') AS avg_duration "
                "FROM calls WHERE created_at >= :since"
            ),
            {"since": since},
        )
    ).first()
    calls = int(funnel_row[0] or 0) if funnel_row else 0
    connected = int(funnel_row[1] or 0) if funnel_row else 0

    qualified = (
        await session.execute(
            text(
                "SELECT count(*) FROM leads WHERE deleted_at IS NULL "
                f"AND status IN {QUALIFIED_STATUSES!r} AND updated_at >= :since"
            ),
            {"since": since},
        )
    ).scalar()

    outcomes = (
        await session.execute(
            text(
                "SELECT COALESCE(outcome_tag, status), count(*) FROM calls "
                "WHERE created_at >= :since GROUP BY 1 ORDER BY 2 DESC"
            ),
            {"since": since},
        )
    ).all()

    # 24 buckets, always all 24: a chart that omits silent hours reads as data loss,
    # and the owner is exactly the reader who notices 3am is missing.
    hours = dict.fromkeys(range(24), 0)
    for hour, count in (
        await session.execute(
            text(
                f"SELECT {IST_HOUR_SQL}::int, "
                "count(*) FROM calls WHERE started_at IS NOT NULL AND created_at >= :since "
                "GROUP BY 1"
            ),
            {"since": since},
        )
    ).all():
        hours[int(hour)] = int(count)

    # Rates as whole-number percentages, None when the denominator is zero — "0%" and
    # "no calls yet" are different facts (same doctrine as the margin panel).
    connect_rate = round(connected * 100 / calls) if calls else None
    qualify_rate = round(int(qualified or 0) * 100 / connected) if connected else None

    return {
        "days": days,
        "funnel": {
            "calls": calls,
            "connected": connected,
            "qualified": int(qualified or 0),
        },
        "connect_rate_pct": connect_rate,
        "qualify_rate_pct": qualify_rate,
        "inbound": int(funnel_row[2] or 0) if funnel_row else 0,
        "outbound": int(funnel_row[3] or 0) if funnel_row else 0,
        "avg_duration_s": int(funnel_row[4]) if funnel_row and funnel_row[4] else None,
        "outcomes": {str(k): int(v) for k, v in outcomes},
        "busiest_hours_ist": [hours[h] for h in range(24)],
    }


__all__ = [
    "CONNECTED_SQL",
    "DIAL_ONLY_STATUSES",
    "IST_HOUR_SQL",
    "QUALIFIED_STATUSES",
    "performance",
]
