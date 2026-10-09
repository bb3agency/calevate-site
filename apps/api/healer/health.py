"""Per-agent health from REAL calls only (D-701). No synthetic test calls, ever.

Every fifteen minutes each live agent's finished calls are counted against seven signals
and scored 0-100. The score is compared with the agent's OWN baseline, the median of its
scored windows over the previous week, so a receptionist whose callers often hang up
quickly is not accused of anything a sales agent's numbers would make look odd. Nothing is
raised for one bad call: a window needs `MIN_WINDOW_CALLS`, a deviation must hold for
`SUSTAINED_WINDOWS` windows in a row, and a broken line needs `BROKEN_MIN_CALLS` calls.

What each signal can see, honestly: failed and sub-ten-second calls, escalations and the
knowledge-gap occurrences work on every engine. Slow starts (time to first audio), the
degraded knowledge states and caller-language mismatches are recorded only on our own
runtime; on ThinnestAI they read zero. In-call action failures come from
`action_invocations`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final
from uuid import UUID

from calevate_shared.worker_api import DEGRADED_KNOWLEDGE_STATES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.base import uuid7

WINDOW: Final = timedelta(minutes=15)
#: A window with fewer real calls than this is recorded but never judged.
MIN_WINDOW_CALLS: Final = 2
#: Consecutive judged windows below baseline before `agent_health_degraded`.
SUSTAINED_WINDOWS: Final = 3
#: Judged windows needed before a baseline exists; until then an absolute floor is used.
BASELINE_MIN_WINDOWS: Final = 8
BASELINE_DAYS: Final = 7
#: How far below its own baseline a window must fall to count as deviating.
DEVIATION_POINTS: Final = Decimal("20")
#: The floor for an agent with no baseline yet, and the ceiling a deviation must be under.
ABSOLUTE_FLOOR: Final = Decimal("60")
DEVIATION_CEILING: Final = Decimal("80")
#: A call shorter than this that "completed" is a caller giving up, not a conversation.
SHORT_CALL_S: Final = 10
#: Time to the agent's first audio beyond which a start counts as dead air.
SLOW_START_MS: Final = 2500
#: Broken line: at least this many calls across the last two windows...
BROKEN_MIN_CALLS: Final = 5
#: ...of which at least this share failed or ended inside ten seconds.
BROKEN_SHARE: Final = Decimal("0.7")
#: Kept for the baseline week plus a margin; older windows are pruned by the scorer.
KEEP_DAYS: Final = 14

#: How much each signal can take off a perfect 100, as a share of calls affected.
WEIGHTS: Final[dict[str, Decimal]] = {
    "broken": Decimal("50"),
    "knowledge": Decimal("15"),
    "slow": Decimal("10"),
    "actions": Decimal("10"),
    "language": Decimal("10"),
    "escalations": Decimal("5"),
}

#: Statuses an in-call action reports when it worked or got a business answer. Anything
#: else (`unreachable`, `misconfigured`, `no_credential`, an http 4xx/5xx...) is a failure.
ACTION_OK_STATUSES: Final = (
    "delivered",
    "checked",
    "booked",
    "found",
    "not_found",
    "slot_taken",
    "link_sent",
    "crm_saved",
)


@dataclass(frozen=True, slots=True)
class WindowCounts:
    agent_id: UUID
    calls: int
    short_calls: int
    failed_calls: int
    slow_starts: int
    escalations: int
    knowledge_misses: int
    action_failures: int
    language_misses: int


def score(c: WindowCounts) -> Decimal:
    """100 minus each signal's weight times the share of calls it touched."""
    if c.calls <= 0:
        return Decimal("100")
    calls = Decimal(c.calls)

    def share(n: int) -> Decimal:
        return min(Decimal(n) / calls, Decimal(1))

    penalty = (
        WEIGHTS["broken"] * share(c.failed_calls + c.short_calls)
        + WEIGHTS["knowledge"] * share(c.knowledge_misses)
        + WEIGHTS["slow"] * share(c.slow_starts)
        + WEIGHTS["actions"] * share(c.action_failures)
        + WEIGHTS["language"] * share(c.language_misses)
        + WEIGHTS["escalations"] * share(c.escalations)
    )
    value = max(Decimal(0), Decimal(100) - penalty)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def deviates(value: Decimal, baseline: Decimal | None, calls: int) -> bool:
    """Whether one window counts against the agent. Never on too few calls."""
    if calls < MIN_WINDOW_CALLS:
        return False
    if baseline is None:
        return value < ABSOLUTE_FLOOR
    return value < min(baseline - DEVIATION_POINTS, DEVIATION_CEILING)


def window_start(at: datetime) -> datetime:
    """The fifteen-minute boundary at or before `at` (aware, UTC)."""
    return at.replace(minute=at.minute - at.minute % 15, second=0, microsecond=0)


_COUNTS = text(
    "WITH c AS ("
    " SELECT c.id, c.agent_id, c.status, c.duration_s, c.outcome_tag, c.knowledge_state"
    " FROM calls c WHERE c.created_at >= :start AND c.created_at < :end"
    " AND NOT c.trial_call AND c.status IN ('completed', 'failed'))"
    " SELECT a.id, count(c.id),"
    " count(c.id) FILTER (WHERE c.status = 'completed' AND coalesce(c.duration_s, 0) < :short),"
    " count(c.id) FILTER (WHERE c.status = 'failed'),"
    " count(c.id) FILTER (WHERE EXISTS (SELECT 1 FROM call_engine_latency l"
    "   WHERE l.call_id = c.id AND l.time_to_first_audio_ms > :slow)),"
    " count(c.id) FILTER (WHERE c.outcome_tag = 'transferred'),"
    " count(c.id) FILTER (WHERE c.knowledge_state = ANY(CAST(:degraded AS text[]))"
    "   OR EXISTS (SELECT 1 FROM knowledge_gap_occurrences g WHERE g.call_id = c.id)),"
    " count(c.id) FILTER (WHERE EXISTS (SELECT 1 FROM transcript_turns t"
    "   WHERE t.call_id = c.id AND t.speaker = 'caller' AND t.lang IS NOT NULL"
    "   AND split_part(t.lang, '-', 1) <> split_part(a.language_primary, '-', 1)"
    "   AND NOT EXISTS (SELECT 1 FROM unnest(coalesce(a.languages_extra, '{}'::text[])) x"
    "     WHERE split_part(x, '-', 1) = split_part(t.lang, '-', 1))))"
    " FROM agents a JOIN c ON c.agent_id = a.id"
    " WHERE a.deleted_at IS NULL GROUP BY a.id"
)

_ACTION_FAILURES = text(
    "SELECT agent_id, count(*) FROM action_invocations WHERE created_at >= :start "
    "AND created_at < :end AND source = 'in_call' AND status <> ALL(CAST(:ok AS text[])) "
    "AND status NOT LIKE 'http_2%' GROUP BY agent_id"
)

_BASELINE = text(
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY score), count(*) "
    "FROM agent_health_windows WHERE agent_id = :aid AND calls >= :min_calls "
    "AND window_start >= :start - make_interval(days => :days) AND window_start < :start "
    "- make_interval(mins => :gap)"
)

_UPSERT = text(
    "INSERT INTO agent_health_windows (id, tenant_id, agent_id, window_start, calls, "
    "short_calls, failed_calls, slow_starts, escalations, knowledge_misses, action_failures, "
    "language_misses, score, baseline, deviating, created_at, updated_at) VALUES (:id, :tid, "
    ":aid, :start, :calls, :short, :failed, :slow, :esc, :kb, :act, :lang, :score, :baseline, "
    ":dev, now(), now()) ON CONFLICT (agent_id, window_start) DO UPDATE SET calls = "
    "EXCLUDED.calls, short_calls = EXCLUDED.short_calls, failed_calls = EXCLUDED.failed_calls, "
    "slow_starts = EXCLUDED.slow_starts, escalations = EXCLUDED.escalations, knowledge_misses "
    "= EXCLUDED.knowledge_misses, action_failures = EXCLUDED.action_failures, language_misses "
    "= EXCLUDED.language_misses, score = EXCLUDED.score, baseline = EXCLUDED.baseline, "
    "deviating = EXCLUDED.deviating, updated_at = now()"
)


async def count_window(session: AsyncSession, *, start: datetime) -> list[WindowCounts]:
    """Every agent of the session's tenant with at least one real call in the window."""
    params = {"start": start, "end": start + WINDOW}
    rows = (
        await session.execute(
            _COUNTS,
            {
                **params,
                "short": SHORT_CALL_S,
                "slow": SLOW_START_MS,
                "degraded": sorted(DEGRADED_KNOWLEDGE_STATES),
            },
        )
    ).all()
    failures = {
        r[0]: int(r[1])
        for r in (
            await session.execute(_ACTION_FAILURES, {**params, "ok": list(ACTION_OK_STATUSES)})
        ).all()
    }
    return [
        WindowCounts(
            agent_id=r[0],
            calls=int(r[1]),
            short_calls=int(r[2]),
            failed_calls=int(r[3]),
            slow_starts=int(r[4]),
            escalations=int(r[5]),
            knowledge_misses=int(r[6]),
            action_failures=failures.get(r[0], 0),
            language_misses=int(r[7]),
        )
        for r in rows
    ]


async def baseline_for(session: AsyncSession, *, agent_id: UUID, start: datetime) -> Decimal | None:
    """The median judged score of the agent's previous week, skipping the windows a
    sustained deviation is measured over so a slide cannot drag its own baseline down."""
    row = (
        await session.execute(
            _BASELINE,
            {
                "aid": agent_id,
                "min_calls": MIN_WINDOW_CALLS,
                "start": start,
                "days": BASELINE_DAYS,
                "gap": int(WINDOW.total_seconds() // 60) * SUSTAINED_WINDOWS,
            },
        )
    ).one()
    if row[0] is None or int(row[1]) < BASELINE_MIN_WINDOWS:
        return None
    return Decimal(str(row[0])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def record_window(
    session: AsyncSession, *, tenant_id: UUID, start: datetime, counts: WindowCounts
) -> tuple[Decimal, Decimal | None, bool]:
    value = score(counts)
    baseline = await baseline_for(session, agent_id=counts.agent_id, start=start)
    deviating = deviates(value, baseline, counts.calls)
    await session.execute(
        _UPSERT,
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": counts.agent_id,
            "start": start,
            "calls": counts.calls,
            "short": counts.short_calls,
            "failed": counts.failed_calls,
            "slow": counts.slow_starts,
            "esc": counts.escalations,
            "kb": counts.knowledge_misses,
            "act": counts.action_failures,
            "lang": counts.language_misses,
            "score": value,
            "baseline": baseline,
            "dev": deviating,
        },
    )
    return value, baseline, deviating


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the last few windows say about one agent."""

    agent_id: UUID
    degraded: bool
    broken: bool
    #: The signal that took most off the score across the judged windows, for proposals.
    worst_signal: str | None


_RECENT = text(
    "SELECT window_start, calls, short_calls, failed_calls, slow_starts, escalations, "
    "knowledge_misses, action_failures, language_misses, deviating FROM agent_health_windows "
    "WHERE agent_id = :aid AND window_start >= :since ORDER BY window_start DESC"
)


def judge(agent_id: UUID, rows: Sequence[Any]) -> Verdict:
    """`rows` newest first, as `_RECENT` returns them."""
    judged = [r for r in rows if int(r[1]) >= MIN_WINDOW_CALLS]
    degraded = len(judged) >= SUSTAINED_WINDOWS and all(
        bool(r[9]) for r in judged[:SUSTAINED_WINDOWS]
    )
    last_two = rows[:2]
    calls = sum(int(r[1]) for r in last_two)
    broken_calls = sum(int(r[2]) + int(r[3]) for r in last_two)
    broken = calls >= BROKEN_MIN_CALLS and Decimal(broken_calls) >= BROKEN_SHARE * calls
    totals = {
        "broken": sum(int(r[2]) + int(r[3]) for r in judged[:SUSTAINED_WINDOWS]),
        "slow": sum(int(r[4]) for r in judged[:SUSTAINED_WINDOWS]),
        "escalations": sum(int(r[5]) for r in judged[:SUSTAINED_WINDOWS]),
        "knowledge": sum(int(r[6]) for r in judged[:SUSTAINED_WINDOWS]),
        "actions": sum(int(r[7]) for r in judged[:SUSTAINED_WINDOWS]),
        "language": sum(int(r[8]) for r in judged[:SUSTAINED_WINDOWS]),
    }
    weighted = {k: WEIGHTS[k] * v for k, v in totals.items() if v}
    worst = max(weighted, key=lambda k: weighted[k]) if weighted else None
    return Verdict(agent_id=agent_id, degraded=degraded, broken=broken, worst_signal=worst)


async def verdict_for(session: AsyncSession, *, agent_id: UUID, now: datetime) -> Verdict:
    since = window_start(now) - WINDOW * (SUSTAINED_WINDOWS + 1)
    rows = (await session.execute(_RECENT, {"aid": agent_id, "since": since})).all()
    return judge(agent_id, rows)


async def calls_since(session: AsyncSession, *, agent_id: UUID, since: datetime) -> tuple[int, int]:
    """Real calls on this agent since `since`, and how many of them were broken."""
    row = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE status = 'failed' OR (status = "
                "'completed' AND coalesce(duration_s, 0) < :short)) FROM calls WHERE agent_id "
                "= :aid AND created_at >= :since AND NOT trial_call AND status IN "
                "('completed', 'failed')"
            ),
            {"aid": agent_id, "since": since, "short": SHORT_CALL_S},
        )
    ).one()
    return int(row[0]), int(row[1])


def looks_broken(calls: int, broken: int) -> bool:
    return calls >= BROKEN_MIN_CALLS and Decimal(broken) >= BROKEN_SHARE * calls


async def prune(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            "DELETE FROM agent_health_windows WHERE window_start < now() - "
            "make_interval(days => :days)"
        ),
        {"days": KEEP_DAYS},
    )
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "ACTION_OK_STATUSES",
    "BROKEN_MIN_CALLS",
    "BROKEN_SHARE",
    "MIN_WINDOW_CALLS",
    "SUSTAINED_WINDOWS",
    "WINDOW",
    "Verdict",
    "WindowCounts",
    "baseline_for",
    "calls_since",
    "count_window",
    "deviates",
    "judge",
    "looks_broken",
    "prune",
    "record_window",
    "score",
    "verdict_for",
    "window_start",
]
