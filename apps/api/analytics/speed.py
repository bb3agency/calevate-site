"""How fast a new lead was called (W8.1): the proof behind "we ring your leads at once".

A LEAD HERE IS ONE DELIVERY THE CALL NEW LEADS PLAN TOOK ON. `ingest_lead` starts a
Follow-up run for every delivery it is asked to call, and the run's `trigger_ref` is
`delivery:<lead source id>:<received, epoch ms>`: the source and the instant the request
reached us, written before any rule is asked. That is the arrival this measures from, so a
lead sent through the public API, a form, a portal or Meta is timed the same way, and a lead
source switched to "keep, don't call" is not counted against a speed it was never asked for.
A repeat delivery for a person already in the Follow-up starts no run and is not a new lead.

THE CLOCK STOPS when our first outbound call to the person is placed (`calls.created_at`,
the dial row written before the phone platform is asked to ring). The platform reports no
separate "ringing" instant, so "placed" is the truthful end.

AFTER HOURS, THE CLOCK STARTS LATER. A lead held for the owner to release starts when it was
released (`lead_call_holds.settled_at`); one booked for the next opening because of calling
hours starts at the instant it was booked for (the deferral's own `callback_at`). The
client's chosen wait before calling is NOT moved: it is time the lead waited, and the card
measures that. A lead booked for later by a Follow-up worker rather than by intake carries no
deferral row and is timed from arrival, which can only make the figure slower, never better.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.analytics.schemas import (
    SpeedCompareOut,
    SpeedFiguresOut,
    SpeedPeriod,
    SpeedSourceOut,
    SpeedToLeadOut,
    SpeedWindowOut,
)
from apps.api.analytics.service import resolve_window
from apps.api.crm.lead_definition import BECAME_LEADS_SQL
from apps.api.crm.performance import CONNECTED_SQL
from apps.api.follow_ups.models import LIVE_RUN_STATUSES
from apps.api.ingest.service import WINDOW_REFUSALS

#: "Called within a minute vs later" is offered only from this many called leads. Below it
#: two interested rates are a handful of people each, and a difference reads as a finding.
SPEED_COMPARE_MIN_LEADS: Final = 30
#: The source table's rows; an account with more sources gets the rest as `other_sources`.
MAX_SPEED_SOURCES: Final = 20
WITHIN_SECONDS: Final = 60

#: The deferrals that moved a first call past calling hours: the plan's own after-hours
#: choice (`ingest/service` writes `plan_<reason>`) and the gate's window refusals.
AFTER_HOURS_RULES: Final = ("plan_after_hours", *sorted(WINDOW_REFUSALS))

_PERIOD_DAYS: Final[dict[SpeedPeriod, int]] = {"7d": 7, "30d": 30, "90d": 90}

#: The shape `ingest_lead` writes; anything else (a date or call trigger) is not an arrival.
_DELIVERY_REF: Final = "^delivery:[0-9a-f-]{36}:[0-9]{1,15}$"

_SPEED_SQL: Final = (
    "WITH a AS (SELECT r.lead_id, r.status AS run_status, "
    "CAST(split_part(r.trigger_ref, ':', 2) AS uuid) AS source_id, "
    "to_timestamp(CAST(split_part(r.trigger_ref, ':', 3) AS bigint) / 1000.0) AS arrived_at "
    "FROM follow_up_runs r WHERE r.started_at >= :start AND r.started_at < :end "
    "AND r.lead_id IS NOT NULL AND r.trigger_ref ~ :shape), "
    "t AS (SELECT a.*, "
    "(SELECT min(c.created_at) FROM calls c WHERE c.lead_id = a.lead_id "
    "AND c.direction = 'outbound' AND c.created_at >= a.arrived_at) AS first_call_at, "
    "(SELECT h.settled_at FROM lead_call_holds h WHERE h.lead_id = a.lead_id "
    "AND h.status = 'released' AND h.held_at >= a.arrived_at "
    "ORDER BY h.held_at LIMIT 1) AS released_at, "
    "(SELECT CAST(e.payload ->> 'callback_at' AS timestamptz) FROM lead_events e "
    "WHERE e.lead_id = a.lead_id AND e.type = 'note' "
    "AND e.payload ->> 'kind' = 'call_deferred' AND e.payload ->> 'rule' = ANY(:after_hours) "
    "AND e.created_at >= a.arrived_at AND e.created_at < a.arrived_at + interval '10 minutes' "
    "ORDER BY e.created_at LIMIT 1) AS opens_at, "
    "EXISTS (SELECT 1 FROM calls c WHERE c.lead_id = a.lead_id "
    f"AND c.created_at >= a.arrived_at AND {CONNECTED_SQL}) AS reached, "
    "EXISTS (SELECT 1 FROM lead_call_holds h WHERE h.lead_id = a.lead_id "
    "AND h.status = 'held') AS held_now FROM a), "
    "u AS (SELECT t.*, GREATEST(t.arrived_at, COALESCE(t.released_at, t.opens_at, t.arrived_at)) "
    "AS clock_at, bl.id IS NOT NULL AS interested FROM t "
    f"LEFT JOIN {BECAME_LEADS_SQL} AS bl ON bl.id = t.lead_id "
    "AND bl.became_lead_at >= t.arrived_at), "
    "v AS (SELECT u.*, CASE WHEN u.first_call_at IS NULL THEN NULL "
    "ELSE GREATEST(0, EXTRACT(EPOCH FROM u.first_call_at - u.clock_at)) END AS wait_s, "
    "(u.first_call_at IS NULL AND (u.run_status = ANY(:live) OR u.held_now)) AS waiting FROM u) "
    "SELECT source_id, GROUPING(source_id) AS is_total, count(*) AS leads, "
    "count(wait_s) AS called, "
    "percentile_disc(0.5) WITHIN GROUP (ORDER BY wait_s) AS median_s, "
    "count(*) FILTER (WHERE wait_s <= :within) AS within_s, "
    "count(*) FILTER (WHERE reached) AS reached, "
    "count(*) FILTER (WHERE NOT reached AND NOT waiting) AS never_reached, "
    "count(*) FILTER (WHERE waiting) AS waiting, "
    "count(*) FILTER (WHERE interested) AS interested, "
    "count(*) FILTER (WHERE clock_at > arrived_at) AS from_release, "
    "count(*) FILTER (WHERE wait_s <= :within AND interested) AS fast_interested, "
    "count(*) FILTER (WHERE wait_s > :within) AS later_called, "
    "count(*) FILTER (WHERE wait_s > :within AND interested) AS later_interested "
    "FROM v GROUP BY GROUPING SETS ((source_id), ()) "
    "ORDER BY is_total DESC, leads DESC, source_id"
)
_SOURCE_KINDS_SQL: Final = (
    "SELECT id, source FROM inbound_webhooks WHERE id = ANY(CAST(:ids AS uuid[]))"
)


@dataclass(frozen=True, slots=True)
class _Span:
    period: SpeedPeriod
    start_at: datetime
    end_at: datetime


def speed_span(period: SpeedPeriod, *, now: datetime | None = None) -> _Span:
    """`24h` to the minute; the day periods are IST calendar days ending today."""
    moment = now or datetime.now(UTC)
    if period == "24h":
        return _Span(period, moment - timedelta(hours=24), moment)
    window = resolve_window(days=_PERIOD_DAYS[period], to=None, now=moment)
    return _Span(period, window.start_at, window.end_at)


def _figures(row: Any) -> dict[str, Any]:
    return {
        "leads": int(row.leads),
        "called": int(row.called),
        "median_s": None if row.median_s is None else round(float(row.median_s)),
        "within_60s": int(row.within_s),
        "reached": int(row.reached),
        "never_reached": int(row.never_reached),
        "waiting": int(row.waiting),
        "interested": int(row.interested),
        "from_release": int(row.from_release),
    }


async def speed_to_lead(
    session: AsyncSession, *, period: SpeedPeriod, now: datetime | None = None
) -> SpeedToLeadOut:
    span = speed_span(period, now=now)
    rows = (
        await session.execute(
            text(_SPEED_SQL),
            {
                "start": span.start_at,
                "end": span.end_at,
                "shape": _DELIVERY_REF,
                "after_hours": list(AFTER_HOURS_RULES),
                "live": list(LIVE_RUN_STATUSES),
                "within": WITHIN_SECONDS,
            },
        )
    ).all()
    total_row = next((r for r in rows if int(r.is_total) == 1), None)
    per_source = [r for r in rows if int(r.is_total) == 0]
    shown = per_source[:MAX_SPEED_SOURCES]
    kinds: dict[str, str] = {}
    ids = [str(r.source_id) for r in shown if r.source_id is not None]
    if ids:
        found = (await session.execute(text(_SOURCE_KINDS_SQL), {"ids": ids})).all()
        kinds = {str(r.id): str(r.source) for r in found}
    total = (
        SpeedFiguresOut(**_figures(total_row))
        if total_row is not None
        else SpeedFiguresOut(
            leads=0,
            called=0,
            median_s=None,
            within_60s=0,
            reached=0,
            never_reached=0,
            waiting=0,
            interested=0,
            from_release=0,
        )
    )
    compare = None
    if total_row is not None and total.called >= SPEED_COMPARE_MIN_LEADS:
        compare = SpeedCompareOut(
            fast_called=total.within_60s,
            fast_interested=int(total_row.fast_interested),
            later_called=int(total_row.later_called),
            later_interested=int(total_row.later_interested),
        )
    return SpeedToLeadOut(
        window=SpeedWindowOut(period=period, start_at=span.start_at, end_at=span.end_at),
        total=total,
        sources=[
            SpeedSourceOut(
                **_figures(r),
                source_id=r.source_id,
                source=kinds.get(str(r.source_id)),
            )
            for r in shown
        ],
        other_sources=sum(int(r.leads) for r in per_source[MAX_SPEED_SOURCES:]),
        compare=compare,
        compare_min_leads=SPEED_COMPARE_MIN_LEADS,
    )


__all__ = [
    "AFTER_HOURS_RULES",
    "MAX_SPEED_SOURCES",
    "SPEED_COMPARE_MIN_LEADS",
    "WITHIN_SECONDS",
    "speed_span",
    "speed_to_lead",
]
