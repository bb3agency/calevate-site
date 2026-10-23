"""Analytics over a chosen range of IST calendar days (D-869).

Every read here is an aggregate over `calls`, `leads` and `campaigns` under the caller's
own tenant session, so RLS is the scoping and no query names a tenant. The definitions are
the ones the product already uses and are imported, never restated: "answered" is
`crm/performance.CONNECTED_SQL`, and the zone is `crm/performance.IST_ZONE`.

THE RANGE IS DAYS, NOT INSTANTS. A request names how many IST calendar days (1 to
`MAX_RANGE_DAYS`) ending on which IST date (today by default). Every bucket is an IST day or
an IST (weekday, hour), computed with `AT TIME ZONE` on the instant, so the result is the
same on a database whose session zone is UTC and on one whose zone is IST. The half-open
instant range `[start 00:00 IST, end+1 00:00 IST)` is what the `WHERE` clause compares, so
`ix_calls_tenant_started` serves the call reads.

Not cached. Each read is one or two indexed aggregates over at most a year of one account's
rows; a cache would add an invalidation question to a number a client expects to move the
moment a call ends.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.analytics.schemas import (
    CampaignDayOut,
    CampaignSeriesOut,
    CampaignTimelinesOut,
    DurationGroupBy,
    DurationGroupOut,
    DurationsOut,
    HeatmapCellOut,
    HeatmapMetric,
    HeatmapOut,
    MetricKey,
    RangeOut,
    StatsMetricOut,
    StatsOut,
    TimelineDayOut,
    TimelineOut,
)
from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.crm.performance import CONNECTED_SQL, IST_ZONE

#: A year and a leap day: the longest window a brush chart offers, and the ceiling that
#: keeps every aggregate here inside one year of one account's rows.
MAX_RANGE_DAYS: Final = 366
DEFAULT_RANGE_DAYS: Final = 30

#: The bin widths the ridgeline offers, in seconds, and how many bins every group gets.
#: Twenty bins at 30 s covers ten minutes, the length past which a phone enquiry is rare;
#: the last bin is open-ended so a long call is counted rather than dropped.
DURATION_BIN_WIDTHS: Final = (15, 30, 60, 120)
DURATION_BINS: Final = 20
MAX_DURATION_GROUPS: Final = 12

MAX_CAMPAIGN_SERIES: Final = 10

#: Leads that are a win in waiting or a win: the "hot leads" figure of the stats band.
HOT_STATUSES: Final = ("hot", "won")

_ONE_DP = Decimal("0.1")

#: The calls a range covers, by when they started. `:test` False leaves out free-trial and
#: paid test calls (D-697, D-859), which are the owner ringing their own agent.
_CALLS_IN_RANGE = (
    "started_at >= :start AND started_at < :end "
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = CAST(:aid AS uuid)) "
    "AND (CAST(:test AS boolean) OR NOT (trial_call OR paid_test_call))"
)
_LEADS_IN_RANGE = (
    "deleted_at IS NULL AND created_at >= :start AND created_at < :end "
    "AND (CAST(:aid AS uuid) IS NULL OR agent_id = CAST(:aid AS uuid))"
)


@dataclass(frozen=True, slots=True)
class Window:
    """Inclusive IST calendar days and the half-open instant range they span."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=IST)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=IST)

    def previous(self) -> Window:
        """The same number of days immediately before."""
        return Window(
            start=self.start - timedelta(days=self.days), end=self.start - timedelta(days=1)
        )

    def out(self) -> RangeOut:
        return RangeOut(from_date=self.start, to_date=self.end, days=self.days)

    def calendar(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def resolve_window(*, days: int, to: date | None, now: datetime | None = None) -> Window:
    """`days` IST days ending on `to` (today when absent). The route bounds `days`; this
    refuses an end in the future, which would be a range of empty buckets that reads as a
    collapse rather than as "has not happened yet"."""
    today = today_ist(now)
    end = to or today
    if end > today:
        raise ProblemError(
            kind="validation",
            code="analytics_range_in_future",
            title="That range has not happened yet",
            detail="`to` is after today in India time.",
            remediation="Send `to` as today's date or earlier (YYYY-MM-DD, IST), or leave it out.",
        )
    if not 1 <= days <= MAX_RANGE_DAYS:
        raise ProblemError(
            kind="validation",
            code="analytics_range_too_long",
            title="That range is too long",
            detail=f"A range covers 1 to {MAX_RANGE_DAYS} days.",
            remediation=f"Send `days` between 1 and {MAX_RANGE_DAYS}.",
        )
    return Window(start=end - timedelta(days=days - 1), end=end)


def _params(window: Window, *, agent_id: UUID | None, test_calls: bool = True) -> dict[str, Any]:
    return {
        "start": window.start_at,
        "end": window.end_at,
        "aid": agent_id,
        "test": test_calls,
    }


# --- heatmap ------------------------------------------------------------------------

_IST_OF = "({column} AT TIME ZONE '" + IST_ZONE + "')"


def _weekday_hour_sql(table: str, column: str, where: str) -> str:
    local = _IST_OF.format(column=column)
    return (
        f"SELECT EXTRACT(ISODOW FROM {local})::int AS weekday, "
        f"EXTRACT(HOUR FROM {local})::int AS hour, count(*) AS n "
        f"FROM {table} WHERE {where} GROUP BY 1, 2"
    )


_CALLS_HEATMAP_SQL: Final = _weekday_hour_sql("calls", "started_at", _CALLS_IN_RANGE)
_LEADS_HEATMAP_SQL: Final = _weekday_hour_sql("leads", "created_at", _LEADS_IN_RANGE)


async def heatmap(
    session: AsyncSession,
    *,
    window: Window,
    metric: HeatmapMetric,
    agent_id: UUID | None,
    test_calls: bool,
) -> HeatmapOut:
    rows = (
        await session.execute(
            text(_CALLS_HEATMAP_SQL if metric == "calls" else _LEADS_HEATMAP_SQL),
            _params(window, agent_id=agent_id, test_calls=test_calls),
        )
    ).all()
    counts = {(int(r.weekday), int(r.hour)): int(r.n) for r in rows}
    cells = [
        HeatmapCellOut(weekday=wd, hour=hr, count=counts.get((wd, hr), 0))
        for wd in range(1, 8)
        for hr in range(24)
    ]
    return HeatmapOut(
        window=window.out(),
        metric=metric,
        total=sum(counts.values()),
        max_count=max(counts.values(), default=0),
        cells=cells,
    )


# --- durations (ridgeline) ----------------------------------------------------------

_AGENT_KEY: Final = "c.agent_id::text"
_OUTCOME_KEY: Final = "COALESCE(c.outcome_tag, 'unread')"

_DURATIONS_FROM = (
    "FROM calls c WHERE c.status = 'completed' AND c.duration_s IS NOT NULL "
    "AND c.started_at >= :start AND c.started_at < :end "
    "AND (CAST(:aid AS uuid) IS NULL OR c.agent_id = CAST(:aid AS uuid)) "
    "AND (CAST(:test AS boolean) OR NOT (c.trial_call OR c.paid_test_call))"
)


def _durations_totals_sql(group_by: str) -> str:
    key = _AGENT_KEY if group_by == "agent" else _OUTCOME_KEY
    return (
        f"SELECT {key} AS key, count(*) AS n, "
        "percentile_disc(0.5) WITHIN GROUP (ORDER BY c.duration_s) AS median_s, "
        "percentile_disc(0.9) WITHIN GROUP (ORDER BY c.duration_s) AS p90_s "
        f"{_DURATIONS_FROM} GROUP BY 1 ORDER BY 2 DESC, 1"
    )


def _durations_bins_sql(group_by: str) -> str:
    key = _AGENT_KEY if group_by == "agent" else _OUTCOME_KEY
    return (
        f"SELECT {key} AS key, LEAST(c.duration_s / :bin, :last_bin) AS bin, count(*) AS n "
        f"{_DURATIONS_FROM} GROUP BY 1, 2"
    )


async def durations(
    session: AsyncSession,
    *,
    window: Window,
    group_by: DurationGroupBy,
    bin_s: int,
    limit: int,
    agent_id: UUID | None,
    test_calls: bool,
) -> DurationsOut:
    params = _params(window, agent_id=agent_id, test_calls=test_calls)
    totals = (await session.execute(text(_durations_totals_sql(group_by)), params)).all()
    shown = totals[:limit]
    shown_keys = [str(r.key) for r in shown]
    bins = (
        await session.execute(
            text(_durations_bins_sql(group_by)),
            {**params, "bin": bin_s, "last_bin": DURATION_BINS - 1},
        )
    ).all()
    per_key: dict[str, list[int]] = {k: [0] * DURATION_BINS for k in shown_keys}
    for row in bins:
        key = str(row.key)
        if key in per_key:
            per_key[key][int(row.bin)] = int(row.n)
    labels = await _agent_names(session, shown_keys) if group_by == "agent" else {}
    return DurationsOut(
        window=window.out(),
        group_by=group_by,
        bin_s=bin_s,
        bin_edges_s=[i * bin_s for i in range(DURATION_BINS)],
        groups=[
            DurationGroupOut(
                key=str(r.key),
                label=labels.get(str(r.key), str(r.key)),
                calls=int(r.n),
                counts=per_key[str(r.key)],
                median_s=int(r.median_s),
                p90_s=int(r.p90_s),
            )
            for r in shown
        ],
        other_calls=sum(int(r.n) for r in totals[limit:]),
    )


async def _agent_names(session: AsyncSession, ids: Sequence[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            text("SELECT id::text, name FROM agents WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": list(ids)},
        )
    ).all()
    return {str(r[0]): str(r[1]) for r in rows}


# --- timelines (brush charts) -------------------------------------------------------

_TIMELINE_SQL: Final = (
    "WITH d AS (SELECT generate_series(CAST(:start_day AS date), CAST(:end_day AS date), "
    "  interval '1 day')::date AS day), "
    "c AS (SELECT " + _IST_OF.format(column="started_at") + "::date AS day, count(*) AS calls, "
    f"  count(*) FILTER (WHERE {CONNECTED_SQL}) AS answered "
    f"  FROM calls WHERE {_CALLS_IN_RANGE} GROUP BY 1), "
    "l AS (SELECT " + _IST_OF.format(column="created_at") + "::date AS day, count(*) AS leads "
    f"  FROM leads WHERE {_LEADS_IN_RANGE} GROUP BY 1) "
    "SELECT d.day, COALESCE(c.calls, 0) AS calls, COALESCE(c.answered, 0) AS answered, "
    "COALESCE(l.leads, 0) AS leads FROM d LEFT JOIN c ON c.day = d.day "
    "LEFT JOIN l ON l.day = d.day ORDER BY d.day"
)


async def timeline(
    session: AsyncSession, *, window: Window, agent_id: UUID | None, test_calls: bool
) -> TimelineOut:
    rows = (
        await session.execute(
            text(_TIMELINE_SQL),
            {
                **_params(window, agent_id=agent_id, test_calls=test_calls),
                "start_day": window.start,
                "end_day": window.end,
            },
        )
    ).all()
    days = [
        TimelineDayOut(
            ist_date=r.day, calls=int(r.calls), answered=int(r.answered), leads=int(r.leads)
        )
        for r in rows
    ]
    return TimelineOut(
        window=window.out(),
        days=days,
        calls=sum(d.calls for d in days),
        answered=sum(d.answered for d in days),
        leads=sum(d.leads for d in days),
    )


#: A dial is counted on the IST day it was PLACED (`created_at`): a dial the network never
#: connected has no `started_at`, and it is still a dial the campaign spent.
_DIALS_RANGE = "c.created_at >= :start AND c.created_at < :end"

_TOP_CAMPAIGNS_SQL: Final = (
    "SELECT cp.id, cp.name, cp.status, count(c.id) AS dials FROM campaigns cp "
    f"JOIN calls c ON c.campaign_id = cp.id AND {_DIALS_RANGE} "
    "GROUP BY cp.id, cp.name, cp.status, cp.created_at "
    "ORDER BY dials DESC, cp.created_at DESC, cp.id LIMIT :limit"
)
_ONE_CAMPAIGN_SQL: Final = "SELECT cp.id, cp.name, cp.status FROM campaigns cp WHERE cp.id = :cid"

_CAMPAIGN_DIALS_SQL: Final = (
    "SELECT c.campaign_id, " + _IST_OF.format(column="c.created_at") + "::date AS day, "
    "count(*) AS dials, "
    f"count(*) FILTER (WHERE {CONNECTED_SQL}) "
    "AS connected "
    f"FROM calls c WHERE c.campaign_id = ANY(CAST(:ids AS uuid[])) AND {_DIALS_RANGE} GROUP BY 1, 2"
)
#: A campaign's lead is one whose FIRST call was one of the campaign's dials — the lead the
#: campaign created, not every lead it happened to ring.
_CAMPAIGN_LEADS_SQL: Final = (
    "SELECT c.campaign_id, " + _IST_OF.format(column="l.created_at") + "::date AS day, "
    "count(*) AS leads FROM leads l JOIN calls c ON c.id = l.first_call_id "
    "WHERE c.campaign_id = ANY(CAST(:ids AS uuid[])) AND l.deleted_at IS NULL "
    "AND l.created_at >= :start AND l.created_at < :end GROUP BY 1, 2"
)


async def campaign_timelines(
    session: AsyncSession, *, window: Window, campaign_id: UUID | None, limit: int
) -> CampaignTimelinesOut:
    params = {"start": window.start_at, "end": window.end_at}
    if campaign_id is not None:
        heads = (await session.execute(text(_ONE_CAMPAIGN_SQL), {"cid": campaign_id})).all()
        if not heads:
            raise ProblemError.not_found("Campaign")
    else:
        heads = (await session.execute(text(_TOP_CAMPAIGNS_SQL), {**params, "limit": limit})).all()
    ids = [str(h.id) for h in heads]
    dials: dict[tuple[str, date], tuple[int, int]] = {}
    leads: dict[tuple[str, date], int] = {}
    if ids:
        for r in (await session.execute(text(_CAMPAIGN_DIALS_SQL), {**params, "ids": ids})).all():
            dials[(str(r.campaign_id), r.day)] = (int(r.dials), int(r.connected))
        for r in (await session.execute(text(_CAMPAIGN_LEADS_SQL), {**params, "ids": ids})).all():
            leads[(str(r.campaign_id), r.day)] = int(r.leads)
    series: list[CampaignSeriesOut] = []
    for head in heads:
        cid = str(head.id)
        days = [
            CampaignDayOut(
                ist_date=day,
                dials=dials.get((cid, day), (0, 0))[0],
                connected=dials.get((cid, day), (0, 0))[1],
                leads=leads.get((cid, day), 0),
            )
            for day in window.calendar()
        ]
        series.append(
            CampaignSeriesOut(
                campaign_id=head.id,
                name=str(head.name),
                status=str(head.status),
                dials=sum(d.dials for d in days),
                connected=sum(d.connected for d in days),
                leads=sum(d.leads for d in days),
                days=days,
            )
        )
    return CampaignTimelinesOut(window=window.out(), campaigns=series)


# --- stats band ---------------------------------------------------------------------

_FIGURES_SQL: Final = (
    "SELECT count(*) AS calls, "
    f"count(*) FILTER (WHERE {CONNECTED_SQL}) AS answered, "
    "avg(duration_s) FILTER (WHERE status = 'completed') AS avg_duration, "
    f"COALESCE(sum(duration_s) FILTER (WHERE {CONNECTED_SQL}), 0) AS talk_s "
    f"FROM calls WHERE {_CALLS_IN_RANGE}"
)
_LEAD_FIGURES_SQL: Final = (
    "SELECT count(*) AS leads, count(*) FILTER (WHERE status = ANY(:hot)) AS hot "
    f"FROM leads WHERE {_LEADS_IN_RANGE}"
)


@dataclass(frozen=True, slots=True)
class _Figures:
    calls: int
    answered: int
    avg_duration_s: Decimal | None
    talk_minutes: Decimal
    leads: int
    hot_leads: int

    @property
    def answer_rate_pct(self) -> Decimal | None:
        if self.calls == 0:
            return None
        return (Decimal(self.answered) * 100 / Decimal(self.calls)).quantize(
            _ONE_DP, rounding=ROUND_HALF_UP
        )


async def _figures(
    session: AsyncSession, window: Window, *, agent_id: UUID | None, test_calls: bool
) -> _Figures:
    params = _params(window, agent_id=agent_id, test_calls=test_calls)
    calls = (await session.execute(text(_FIGURES_SQL), params)).one()
    lead_row = (
        await session.execute(text(_LEAD_FIGURES_SQL), {**params, "hot": list(HOT_STATUSES)})
    ).one()
    avg = calls.avg_duration
    return _Figures(
        calls=int(calls.calls),
        answered=int(calls.answered),
        avg_duration_s=None
        if avg is None
        else Decimal(str(avg)).quantize(Decimal("1"), rounding=ROUND_HALF_UP),
        talk_minutes=(Decimal(int(calls.talk_s)) / 60).quantize(_ONE_DP, rounding=ROUND_HALF_UP),
        leads=int(lead_row.leads),
        hot_leads=int(lead_row.hot),
    )


def change_pct(value: Decimal | None, previous: Decimal | None) -> Decimal | None:
    """Percentage change, 1 dp; None when there is nothing to compare against."""
    if value is None or previous is None or previous == 0:
        return None
    return ((value - previous) * 100 / previous).quantize(_ONE_DP, rounding=ROUND_HALF_UP)


def _metric(key: MetricKey, value: Decimal | None, previous: Decimal | None) -> StatsMetricOut:
    return StatsMetricOut(
        key=key,
        value=value,
        previous=previous,
        change_pct=change_pct(value, previous),
        higher_is_better=True,
    )


async def stats(
    session: AsyncSession, *, window: Window, agent_id: UUID | None, test_calls: bool
) -> StatsOut:
    before = window.previous()
    now = await _figures(session, window, agent_id=agent_id, test_calls=test_calls)
    then = await _figures(session, before, agent_id=agent_id, test_calls=test_calls)

    def count(value: int) -> Decimal:
        return Decimal(value)

    return StatsOut(
        window=window.out(),
        previous_window=before.out(),
        metrics=[
            _metric("calls", count(now.calls), count(then.calls)),
            _metric("answered", count(now.answered), count(then.answered)),
            _metric("answer_rate_pct", now.answer_rate_pct, then.answer_rate_pct),
            _metric("leads", count(now.leads), count(then.leads)),
            _metric("hot_leads", count(now.hot_leads), count(then.hot_leads)),
            _metric("avg_duration_s", now.avg_duration_s, then.avg_duration_s),
            _metric("talk_minutes", now.talk_minutes, then.talk_minutes),
        ],
    )


__all__ = [
    "DEFAULT_RANGE_DAYS",
    "DURATION_BINS",
    "DURATION_BIN_WIDTHS",
    "MAX_CAMPAIGN_SERIES",
    "MAX_DURATION_GROUPS",
    "MAX_RANGE_DAYS",
    "Window",
    "campaign_timelines",
    "change_pct",
    "durations",
    "heatmap",
    "resolve_window",
    "stats",
    "timeline",
]
