"""Reads about now: each agent's IST day (W8.3), the last hour of calls (W8.2), and the
weekly call-quality scorecard (W8.5).

All three leave out the owner's own test calls (D-697, D-859), as the dashboard does: a row
that says "Today: 12 calls" is the business's calls, not the owner ringing their agent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.roster import AGENT_ROSTER_LIMIT
from apps.api.analytics.schemas import (
    AgentsTodayOut,
    AgentTodayOut,
    LastHourOut,
    LastHourSlotOut,
    QualityGapAgentOut,
    QualityWeekOut,
    QualityWeeksOut,
)
from apps.api.analytics.service import EVERY_CALL, Narrowing, Window, resolve_window, today_ist
from apps.api.crm.lead_definition import BECAME_LEADS_SQL, REAL_CALL_SQL
from apps.api.crm.performance import CONNECTED_SQL, IST_ZONE

# --- agents today -------------------------------------------------------------------------

_TODAY_CALLS_SQL: Final = (
    "SELECT agent_id, count(*) AS calls, "
    f"count(*) FILTER (WHERE {CONNECTED_SQL}) AS answered FROM calls "
    "WHERE started_at >= :start AND started_at < :end AND NOT (trial_call OR paid_test_call) "
    "GROUP BY agent_id ORDER BY calls DESC, agent_id LIMIT :limit"
)
_TODAY_LEADS_SQL: Final = (
    f"SELECT bl.agent_id, count(*) AS n FROM {BECAME_LEADS_SQL} AS bl "
    "WHERE bl.became_lead_at >= :start AND bl.became_lead_at < :end "
    "GROUP BY bl.agent_id ORDER BY n DESC, bl.agent_id LIMIT :limit"
)


async def agents_today(session: AsyncSession, *, now: datetime | None = None) -> AgentsTodayOut:
    day = today_ist(now)
    window = Window(start=day, end=day)
    params = {"start": window.start_at, "end": window.end_at, "limit": AGENT_ROSTER_LIMIT}
    calls = {
        UUID(str(r.agent_id)): (int(r.calls), int(r.answered))
        for r in (await session.execute(text(_TODAY_CALLS_SQL), params)).all()
    }
    leads = {
        UUID(str(r.agent_id)): int(r.n)
        for r in (await session.execute(text(_TODAY_LEADS_SQL), params)).all()
    }
    ids = sorted(set(calls) | set(leads), key=lambda a: (-calls.get(a, (0, 0))[0], str(a)))
    return AgentsTodayOut(
        ist_date=day,
        agents=[
            AgentTodayOut(
                agent_id=agent_id,
                calls=calls.get(agent_id, (0, 0))[0],
                answered=calls.get(agent_id, (0, 0))[1],
                interested=leads.get(agent_id, 0),
            )
            for agent_id in ids[:AGENT_ROSTER_LIMIT]
        ],
    )


# --- the last hour ------------------------------------------------------------------------

LAST_HOUR_SLOT_MINUTES: Final = 5
LAST_HOUR_SLOTS: Final = 12
#: Live calls are looked for among rows made this recently: a row still marked ringing or
#: connected after two hours outlasts the longest call cap (`agents/models.CALL_CAP_MAX_S`,
#: one hour), so its end was never heard, and
#: counting it would keep "live now" lit with nobody on the line.
LIVE_HORIZON: Final = timedelta(hours=2)

_NARROW_SQL: Final = (
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = CAST(:aid AS uuid)) "
    "AND (CAST(:cid AS uuid) IS NULL OR campaign_id = CAST(:cid AS uuid)) "
    "AND (CAST(:lid AS uuid) IS NULL OR inbound_line_id = CAST(:lid AS uuid)) "
    "AND (CAST(:dir AS text) IS NULL OR direction = CAST(:dir AS text)) "
    "AND NOT (trial_call OR paid_test_call)"
)
_LAST_HOUR_SQL: Final = (
    "SELECT floor(EXTRACT(EPOCH FROM started_at - CAST(:start AS timestamptz)) / :slot)::int "
    "AS slot, count(*) AS n FROM calls WHERE started_at >= :start AND started_at < :end "
    f"{_NARROW_SQL} GROUP BY 1"
)
_LIVE_NOW_SQL: Final = (
    "SELECT count(*) FROM calls WHERE status IN ('ringing', 'in_progress') "
    f"AND created_at >= :since {_NARROW_SQL}"
)


async def last_hour(
    session: AsyncSession,
    *,
    agent_id: UUID | None,
    narrow: Narrowing = EVERY_CALL,
    now: datetime | None = None,
) -> LastHourOut:
    moment = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    slot = timedelta(minutes=LAST_HOUR_SLOT_MINUTES)
    # The current minute's slot is the last one, so a call this minute is drawn at once.
    end = moment + timedelta(minutes=1)
    start = end - slot * LAST_HOUR_SLOTS
    narrowing = {
        "aid": agent_id,
        "cid": narrow.campaign_id,
        "lid": narrow.line_id,
        "dir": narrow.direction,
    }
    rows = (
        await session.execute(
            text(_LAST_HOUR_SQL),
            {**narrowing, "start": start, "end": end, "slot": slot.total_seconds()},
        )
    ).all()
    counts = {int(r.slot): int(r.n) for r in rows}
    live = (
        await session.execute(text(_LIVE_NOW_SQL), {**narrowing, "since": moment - LIVE_HORIZON})
    ).scalar_one()
    slots = [
        LastHourSlotOut(start_at=start + slot * i, calls=counts.get(i, 0))
        for i in range(LAST_HOUR_SLOTS)
    ]
    return LastHourOut(live_now=int(live), calls=sum(s.calls for s in slots), slots=slots)


# --- weekly call quality ------------------------------------------------------------------

MAX_QUALITY_WEEKS: Final = 12
DEFAULT_QUALITY_WEEKS: Final = 8
MAX_GAP_AGENTS: Final = 5

_WEEK_OF = f"date_trunc('week', (c.started_at AT TIME ZONE '{IST_ZONE}'))::date"
_QUALITY_SQL: Final = (
    f"SELECT {_WEEK_OF} AS week, count(*) AS calls_read, "
    "count(*) FILTER (WHERE c.goal_reached IN ('yes', 'no')) AS judged, "
    "count(*) FILTER (WHERE c.goal_reached = 'yes') AS goal_reached, "
    "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM knowledge_gap_occurrences g "
    "WHERE g.call_id = c.id)) AS not_known, "
    "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM call_mistakes m "
    "WHERE m.call_id = c.id)) AS mistakes "
    "FROM calls c WHERE c.started_at >= :start AND c.started_at < :end "
    f"AND c.summary_state = 'ready' AND {REAL_CALL_SQL} GROUP BY 1"
)
_GAP_AGENTS_SQL: Final = (
    "SELECT g.agent_id, a.name, count(*) AS n FROM knowledge_gaps g "
    "JOIN agents a ON a.id = g.agent_id WHERE g.status = 'open' AND a.archived_at IS NULL "
    "GROUP BY g.agent_id, a.name ORDER BY n DESC, a.name LIMIT :limit"
)


def quality_window(weeks: int, *, now: datetime | None = None) -> Window:
    """The last `weeks` Monday-first IST weeks, this one included and cut at today."""
    today = today_ist(now)
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks - 1)
    return resolve_window(days=(today - first).days + 1, to=today, now=now)


async def quality_weeks(
    session: AsyncSession, *, weeks: int, now: datetime | None = None
) -> QualityWeeksOut:
    window = quality_window(weeks, now=now)
    rows = (
        await session.execute(text(_QUALITY_SQL), {"start": window.start_at, "end": window.end_at})
    ).all()
    by_week: dict[date, object] = {r.week: r for r in rows}
    out: list[QualityWeekOut] = []
    monday = window.start
    while monday <= window.end:
        row = by_week.get(monday)
        out.append(
            QualityWeekOut(
                from_date=monday,
                to_date=min(monday + timedelta(days=6), window.end),
                calls_read=int(getattr(row, "calls_read", 0)),
                judged=int(getattr(row, "judged", 0)),
                goal_reached=int(getattr(row, "goal_reached", 0)),
                calls_not_known=int(getattr(row, "not_known", 0)),
                calls_with_mistakes=int(getattr(row, "mistakes", 0)),
            )
        )
        monday += timedelta(days=7)
    gaps = (await session.execute(text(_GAP_AGENTS_SQL), {"limit": MAX_GAP_AGENTS})).all()
    return QualityWeeksOut(
        weeks=out,
        gap_agents=[
            QualityGapAgentOut(agent_id=r.agent_id, name=str(r.name), open_questions=int(r.n))
            for r in gaps
        ],
    )


__all__ = [
    "DEFAULT_QUALITY_WEEKS",
    "LAST_HOUR_SLOTS",
    "LAST_HOUR_SLOT_MINUTES",
    "LIVE_HORIZON",
    "MAX_GAP_AGENTS",
    "MAX_QUALITY_WEEKS",
    "agents_today",
    "last_hour",
    "quality_weeks",
    "quality_window",
]
