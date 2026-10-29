"""Proof a client can check for themselves: how fast their agent answered each IST week, and
what each answered call, captured lead and booking cost them (D-944).

REPLY SPEED. The figure is the voice platform's answer time (`CallQuality.answer_ms_*`,
D-902): the caller falling silent to the first word of the actual answer. Aggregated with the
admin Voice response time screen's rules, imported rather than restated
(`ops/reply_times.median_or_none` / `p90_or_none`): the typical wait is the median of the
calls' own medians, the slow wait the 90th percentile of their p90s, withheld below
`P90_MIN_CALLS` calls. A call with no answer time is not measured, never zero. Weeks are IST
Monday-to-Sunday; the newest is the week running now. Grouped per language: the call's
summary language when the after-call work found one, else its agent's main language.

No stored roll-up: the per-call figures already live on `calls`, and a second copy could
disagree with them (D-770's reason). The client's read is one indexed scan of their own
calls under RLS; the fleet read is `call_speed_scan` (migration f7b3e9a1c254), the
`call_reply_scan` pattern.

RUPEES PER RESULT. The rupees are what left the client's wallet (`billing/history.
spend_series`, the Spend screen's reader), not `usage_events.unit_cost_paid`, which is OUR
cost and not what the client pays. Divided by answered calls (`crm/performance` rule),
leads created and booked results in the same IST days. A booked result is a call whose
business outcome (D-836) moves its lead to hot, or the starting set's "Wants to buy or book";
an agent's own list decides, through `agents/call_outcomes.outcome_lead_move`. A figure with
nothing to divide by is null, never zero. Every amount is `Decimal`, rounded once by
`billing/service.to_paise`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from calevate_shared.business_outcomes import STARTING_OUTCOMES
from calevate_shared.languages import find_language
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.call_outcomes import outcome_lead_move
from apps.api.billing.history import spend_series
from apps.api.billing.plans import IST
from apps.api.billing.rates import CLIENT_PULSE_SECONDS
from apps.api.billing.service import to_paise
from apps.api.core.settings import get_settings
from apps.api.crm.performance import CONNECTED_SQL, DIAL_ONLY_STATUSES
from apps.api.ops.reply_times import P90_MIN_CALLS, median_or_none, p90_or_none

DEFAULT_WEEKS: Final = 4
MAX_WEEKS: Final = 12
#: The row that sums every language of a week.
ALL_LANGUAGES: Final = "all"
UNKNOWN_LANGUAGE: Final = "unknown"
#: Calls read per report; a run that hits it says so (`complete=False`).
MAX_SPEED_CALLS: Final = 100_000
#: The windows the cost card offers, in IST days ending today.
COST_WINDOWS: Final = (7, 30)
#: The starting set's buying outcome (`STARTING_OUTCOMES[0]`, "Wants to buy or book"), which
#: moves a lead only to interested and is still a booking.
BUYING_OUTCOME_KEY: Final = STARTING_OUTCOMES[0].key

_DIAL_ONLY: Final = frozenset(DIAL_ONLY_STATUSES)


@dataclass(frozen=True, slots=True)
class SpeedCall:
    started_at: datetime
    language: str
    status: str
    duration_s: int | None
    answer_median: float | None
    answer_p90: float | None

    @property
    def connected(self) -> bool:
        """`crm/performance.CONNECTED_SQL`, in Python, from the same status list."""
        if self.status == "completed":
            return True
        return bool(self.duration_s) and self.status not in _DIAL_ONLY


class WeekSpeed(BaseModel):
    #: The IST Monday the week starts on.
    week_start: date
    #: A BCP-47 tag (`te-IN`), `all` for the week's every call, or `unknown`.
    language: str
    calls: int
    answered: int
    #: Answered over calls; null for a week with no calls.
    answered_share: float | None
    #: Mean length of the answered calls, seconds; null with none.
    average_call_s: float | None
    #: Calls the platform sent an answer time for.
    calls_measured: int
    #: Median of the calls' own median wait for the answer.
    reply_typical_ms: float | None
    #: 90th percentile of the calls' own p90 wait; null below `p90_min_calls`.
    reply_slow_ms: float | None


class ReplySpeedOut(BaseModel):
    """Per IST week, oldest first: the week's `all` row, then one per language."""

    weeks: list[WeekSpeed]
    typical_target_ms: int
    slow_target_ms: int
    p90_min_calls: int
    #: The newest week is still running.
    current_week_partial: bool


class FleetReplySpeedOut(ReplySpeedOut):
    #: Clients with a call in the window.
    clients: int
    #: False when the window held more than `MAX_SPEED_CALLS` calls.
    complete: bool
    #: The console flag for a public page (`public_quality_page_enabled`). Nothing public
    #: serves these figures; the field says whether one may.
    public_page_enabled: bool


def language_key(tag: str | None) -> str:
    if not tag:
        return UNKNOWN_LANGUAGE
    found = find_language(tag)
    return found.bcp47 if found is not None else UNKNOWN_LANGUAGE


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def ist_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def week_starts(today: date, count: int) -> list[date]:
    """The `count` IST weeks ending with the one holding `today`, oldest first."""
    newest = week_start(today)
    return [newest - timedelta(weeks=count - 1 - i) for i in range(count)]


def _ist_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


def week_speed(week: date, language: str, calls: Sequence[SpeedCall]) -> WeekSpeed:
    answered = [c for c in calls if c.connected]
    lengths = [c.duration_s for c in answered if c.duration_s is not None]
    measured = [c for c in calls if c.answer_median is not None]
    return WeekSpeed(
        week_start=week,
        language=language,
        calls=len(calls),
        answered=len(answered),
        answered_share=round(len(answered) / len(calls), 4) if calls else None,
        average_call_s=round(sum(lengths) / len(lengths), 1) if lengths else None,
        calls_measured=len(measured),
        reply_typical_ms=median_or_none(
            sorted(c.answer_median for c in measured if c.answer_median is not None)
        ),
        reply_slow_ms=p90_or_none(
            sorted(c.answer_p90 for c in measured if c.answer_p90 is not None)
        ),
    )


def rollup(calls: Iterable[SpeedCall], weeks: Sequence[date]) -> list[WeekSpeed]:
    """Every week gets its `all` row, zero-filled; a language row only where it had calls,
    busiest first."""
    by_week: dict[date, list[SpeedCall]] = {week: [] for week in weeks}
    for call in calls:
        bucket = by_week.get(week_start(call.started_at.astimezone(IST).date()))
        if bucket is not None:
            bucket.append(call)
    out: list[WeekSpeed] = []
    for week in weeks:
        week_calls = by_week[week]
        out.append(week_speed(week, ALL_LANGUAGES, week_calls))
        by_language: dict[str, list[SpeedCall]] = {}
        for call in week_calls:
            by_language.setdefault(call.language, []).append(call)
        for language, group in sorted(by_language.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out.append(week_speed(week, language, group))
    return out


def _speed_call(row: Sequence[Any]) -> SpeedCall:
    return SpeedCall(
        started_at=row[0],
        language=language_key(row[1]),
        status=str(row[2]),
        duration_s=int(row[3]) if row[3] is not None else None,
        answer_median=float(row[4]) if row[4] is not None else None,
        answer_p90=float(row[5]) if row[5] is not None else None,
    )


_CLIENT_SQL: Final = text(
    "SELECT c.started_at, COALESCE(c.summary_language, a.language_primary), c.status, "
    "c.duration_s, (c.engine_quality ->> 'answer_ms_median')::float8, "
    "(c.engine_quality ->> 'answer_ms_p90')::float8 "
    "FROM calls c LEFT JOIN agents a ON a.id = c.agent_id "
    "WHERE c.started_at >= :since AND c.started_at < :until "
    "AND NOT (c.trial_call OR c.paid_test_call) "
    "ORDER BY c.started_at DESC LIMIT :cap"
)

_FLEET_SQL: Final = text(
    "SELECT s.started_at, s.language, s.status, s.duration_s, s.answer_median, s.answer_p90, "
    "s.scanned_tenant_id FROM call_speed_scan(:since) AS s "
    "WHERE s.started_at < :until AND NOT s.test_call "
    "ORDER BY s.started_at DESC LIMIT :cap"
)


def _targets() -> tuple[int, int]:
    settings = get_settings()
    return settings.reply_time_typical_target_ms, settings.reply_time_slow_target_ms


async def client_reply_speed(
    session: AsyncSession, *, weeks: int = DEFAULT_WEEKS, now: datetime | None = None
) -> ReplySpeedOut:
    """The caller's own account, under its RLS session. The owner's own test calls are left
    out: they are the owner ringing their agent, not callers."""
    today = ist_today(now)
    starts = week_starts(today, weeks)
    rows = (
        await session.execute(
            _CLIENT_SQL,
            {
                "since": _ist_midnight(starts[0]),
                "until": _ist_midnight(starts[-1] + timedelta(weeks=1)),
                "cap": MAX_SPEED_CALLS,
            },
        )
    ).all()
    typical, slow = _targets()
    return ReplySpeedOut(
        weeks=rollup((_speed_call(r) for r in rows), starts),
        typical_target_ms=typical,
        slow_target_ms=slow,
        p90_min_calls=P90_MIN_CALLS,
        current_week_partial=today != starts[-1] + timedelta(days=6),
    )


async def fleet_reply_speed(
    session: AsyncSession, *, weeks: int = DEFAULT_WEEKS, now: datetime | None = None
) -> FleetReplySpeedOut:
    """Every client, by language. Must be handed an `admin_session()`: only it can enumerate
    the tenants `call_speed_scan` enters one by one."""
    today = ist_today(now)
    starts = week_starts(today, weeks)
    rows = (
        await session.execute(
            _FLEET_SQL,
            {
                "since": _ist_midnight(starts[0]),
                "until": _ist_midnight(starts[-1] + timedelta(weeks=1)),
                "cap": MAX_SPEED_CALLS + 1,
            },
        )
    ).all()
    complete = len(rows) <= MAX_SPEED_CALLS
    kept = rows[:MAX_SPEED_CALLS]
    typical, slow = _targets()
    return FleetReplySpeedOut(
        weeks=rollup((_speed_call(r) for r in kept), starts),
        typical_target_ms=typical,
        slow_target_ms=slow,
        p90_min_calls=P90_MIN_CALLS,
        current_week_partial=today != starts[-1] + timedelta(days=6),
        clients=len({r[6] for r in kept}),
        complete=complete,
        public_page_enabled=get_settings().public_quality_page_enabled,
    )


# --- rupees per result ----------------------------------------------------------------


class CostWindowOut(BaseModel):
    days: int
    from_date: date
    to_date: date
    #: What left the wallet in these IST days (calls, number rental, AI help, corrections).
    spent_inr: Decimal
    answered_calls: int
    leads_captured: int
    booked_results: int
    per_answered_call_inr: Decimal | None
    per_lead_inr: Decimal | None
    per_booked_result_inr: Decimal | None


class CostPerResultOut(BaseModel):
    windows: list[CostWindowOut]
    #: Calls are billed in steps of this many seconds, rounded up (D-681).
    billing_step_seconds: int


def per_unit(spent: Decimal, count: int) -> Decimal | None:
    return None if count <= 0 else to_paise(spent / Decimal(count))


def is_booking(outcomes: object, key: str | None) -> bool:
    """A business outcome that moves the lead to hot, or the starting set's buying one."""
    if not key:
        return False
    return key == BUYING_OUTCOME_KEY or outcome_lead_move(outcomes, key) == "hot"


@dataclass(frozen=True, slots=True)
class ResultCounts:
    answered_calls: int
    leads_captured: int
    booked_results: int


_ANSWERED_SQL: Final = text(
    "SELECT count(*) FROM calls WHERE started_at >= :start AND started_at < :end "
    f"AND {CONNECTED_SQL}"
)
_LEADS_SQL: Final = text(
    "SELECT count(*) FROM leads WHERE deleted_at IS NULL "
    "AND created_at >= :start AND created_at < :end"
)
#: Grouped by agent and outcome key, so the rows are bounded by agents x 8 outcomes.
_OUTCOMES_SQL: Final = text(
    "SELECT a.business_outcomes, c.business_outcome, count(*) FROM calls c "
    "JOIN agents a ON a.id = c.agent_id "
    "WHERE c.started_at >= :start AND c.started_at < :end AND c.business_outcome IS NOT NULL "
    "GROUP BY a.id, a.business_outcomes, c.business_outcome"
)


async def result_counts(session: AsyncSession, *, start: date, end: date) -> ResultCounts:
    """Answered calls, new leads and booked results on IST days `start`..`end` inclusive."""
    binds = {"start": _ist_midnight(start), "end": _ist_midnight(end + timedelta(days=1))}
    answered = int((await session.execute(_ANSWERED_SQL, binds)).scalar_one())
    leads = int((await session.execute(_LEADS_SQL, binds)).scalar_one())
    booked = sum(
        int(row[2])
        for row in (await session.execute(_OUTCOMES_SQL, binds)).all()
        if is_booking(row[0], row[1])
    )
    return ResultCounts(answered_calls=answered, leads_captured=leads, booked_results=booked)


async def cost_window(
    session: AsyncSession, *, tenant_id: UUID, days: int, today: date
) -> CostWindowOut:
    start = today - timedelta(days=days - 1)
    series = await spend_series(session, tenant_id=tenant_id, start=start, end=today)
    counts = await result_counts(session, start=start, end=today)
    spent = series.spent_inr
    return CostWindowOut(
        days=days,
        from_date=start,
        to_date=today,
        spent_inr=spent,
        answered_calls=counts.answered_calls,
        leads_captured=counts.leads_captured,
        booked_results=counts.booked_results,
        per_answered_call_inr=per_unit(spent, counts.answered_calls),
        per_lead_inr=per_unit(spent, counts.leads_captured),
        per_booked_result_inr=per_unit(spent, counts.booked_results),
    )


async def cost_per_result(
    session: AsyncSession, *, tenant_id: UUID, now: datetime | None = None
) -> CostPerResultOut:
    today = ist_today(now)
    return CostPerResultOut(
        windows=[
            await cost_window(session, tenant_id=tenant_id, days=days, today=today)
            for days in COST_WINDOWS
        ],
        billing_step_seconds=int(CLIENT_PULSE_SECONDS),
    )


__all__ = [
    "ALL_LANGUAGES",
    "BUYING_OUTCOME_KEY",
    "COST_WINDOWS",
    "DEFAULT_WEEKS",
    "MAX_SPEED_CALLS",
    "MAX_WEEKS",
    "UNKNOWN_LANGUAGE",
    "CostPerResultOut",
    "CostWindowOut",
    "FleetReplySpeedOut",
    "ReplySpeedOut",
    "ResultCounts",
    "SpeedCall",
    "WeekSpeed",
    "client_reply_speed",
    "cost_per_result",
    "cost_window",
    "fleet_reply_speed",
    "is_booking",
    "ist_today",
    "language_key",
    "per_unit",
    "result_counts",
    "rollup",
    "week_speed",
    "week_start",
    "week_starts",
]
