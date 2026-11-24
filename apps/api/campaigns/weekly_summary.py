"""Pip's weekly summary of an account (founder, 24-25 Nov 2026): one short paragraph about the
IST week that closed, written by `workers/weekly_summary` and shown on the Improve page.

The paragraph is written from `WeekFigures` alone: counts, rates, the name of the script step
that lost the most people and the name of the best campaign or line. No transcript, caller
word or phone number is read or sent (hard rule 6); `figures` is stored beside the paragraph
so the page shows the numbers it was written from.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.campaigns import account_improve, diagnose
from apps.api.campaigns.learning import ANSWERED_SQL
from apps.api.campaigns.models import WEEKLY_SUMMARY_MAX
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.quality.sampling import ist_week_start

#: Calls placed or taken in a week before it gets a summary: below it there is nothing to say.
MIN_CALLS: Final = 5
#: Past summaries one read returns.
MAX_LISTED: Final = 26


@dataclass(frozen=True, slots=True)
class WeekFigures:
    week_start: str
    calls: int
    answered: int
    #: Outbound calls answered over outbound calls placed; None below `MIN_ANSWERED_CALLS`.
    answer_rate: float | None
    #: The script step that lost the most people across the account's judged calls.
    drop_off_step: str | None
    drop_off_lost: int
    goals: int
    #: Script repairs, outcomes written, notices woven, best hours and opening winners applied.
    fixes: int
    best_name: str | None
    best_goal_rate: float | None


def closed_week(moment: datetime) -> tuple[date, datetime, datetime]:
    """The IST week that had ended when `moment` fell: its Monday and its UTC half-open
    interval, as `kb_aggregation.closed_week` cuts it."""
    monday = ist_week_start(moment) - timedelta(days=7)
    since = datetime.combine(monday, time.min, tzinfo=IST)
    return monday, since.astimezone(UTC), (since + timedelta(days=7)).astimezone(UTC)


_AT: Final = "COALESCE(c.started_at, c.created_at)"
_REAL: Final = (
    "(c.campaign_id IS NOT NULL OR NOT (c.trial_call OR c.paid_test_call)) "
    f"AND {_AT} >= :since AND {_AT} < :until"
)


async def _worst_step(session: AsyncSession, since: datetime, until: datetime) -> tuple[str, int]:
    """Each holder's steps judged as `diagnose.drop_off` judges them, over the week; the step
    that lost the most people on any one holder."""
    rows = (
        await session.execute(
            text(
                "SELECT COALESCE(c.campaign_id, c.inbound_line_id) AS hid, "
                "(s->>'step')::int AS step, "
                "(array_agg(s->>'name' ORDER BY c.started_at DESC NULLS LAST))[1] AS name, "
                "count(*) FILTER (WHERE s->>'state' = 'reached') AS reached, "
                "count(*) FILTER (WHERE s->>'state' = 'not_reached') AS not_reached, "
                "count(*) FILTER (WHERE s->>'state' = 'unclear') AS unclear "
                "FROM calls c CROSS JOIN LATERAL jsonb_array_elements("
                "CASE WHEN jsonb_typeof(c.step_progress->'steps') = 'array' "
                "THEN c.step_progress->'steps' ELSE '[]'::jsonb END) s "
                f"WHERE {_REAL} AND (c.campaign_id IS NOT NULL OR c.inbound_line_id IS NOT NULL) "
                "AND (s->>'step') ~ '^[0-9]{1,3}$' "
                "GROUP BY 1, 2 ORDER BY 1, 2 LIMIT :n"
            ),
            {
                "since": since,
                "until": until,
                "n": account_improve.MAX_HOLDERS * diagnose.MAX_STEPS,
            },
        )
    ).all()
    by_holder: dict[UUID, list[diagnose.StepCount]] = {}
    for r in rows:
        by_holder.setdefault(r.hid, []).append(
            diagnose.StepCount(
                int(r.step), str(r.name or ""), int(r.reached), int(r.not_reached), int(r.unclear)
            )
        )
    best: tuple[str, int] = ("", 0)
    for steps in by_holder.values():
        judged = max((s.reached + s.not_reached + s.unclear for s in steps), default=0)
        if judged < diagnose.MIN_JUDGED_CALLS:
            continue
        for s in diagnose.with_losses(steps):
            if s.lost_here > best[1]:
                best = (s.name, s.lost_here)
    return best


async def _fixes(session: AsyncSession, since: datetime, until: datetime) -> int:
    written = (
        await session.execute(
            text(
                "SELECT count(*) FROM script_versions WHERE author = ANY(:authors) "
                "AND created_at >= :since AND created_at < :until"
            ),
            {"authors": list(account_improve.PIP_AUTHORS), "since": since, "until": until},
        )
    ).scalar_one()
    applied = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE best_hours_applied->>'by' = 'pip' "
                "AND (best_hours_applied->>'at')::timestamptz >= :since "
                "AND (best_hours_applied->>'at')::timestamptz < :until) "
                "+ count(*) FILTER (WHERE opening_test_result->>'applied' = 'true' "
                "AND (opening_test_result->>'at')::timestamptz >= :since "
                "AND (opening_test_result->>'at')::timestamptz < :until) "
                "FROM campaigns WHERE best_hours_applied IS NOT NULL "
                "OR opening_test_result IS NOT NULL"
            ),
            {"since": since, "until": until},
        )
    ).scalar_one()
    return int(written) + int(applied or 0)


async def week_figures(session: AsyncSession, moment: datetime) -> WeekFigures:
    monday, since, until = closed_week(moment)
    counts = (
        await session.execute(
            text(
                "SELECT count(*) AS calls, "
                f"count(*) FILTER (WHERE {ANSWERED_SQL}) AS answered, "
                "count(*) FILTER (WHERE c.direction = 'outbound' "
                "AND c.not_placed_reason IS NULL) AS placed_out, "
                f"count(*) FILTER (WHERE c.direction = 'outbound' AND {ANSWERED_SQL}) "
                "AS answered_out, "
                f"count(*) FILTER (WHERE {ANSWERED_SQL} AND c.goal_reached = 'yes') AS goals "
                f"FROM calls c WHERE {_REAL}"
            ),
            {"since": since, "until": until},
        )
    ).one()
    step, lost = await _worst_step(session, since, until)
    comparison = await account_improve.compare_holders(
        session, include_spend=False, now=until, since=since
    )
    best = comparison.best
    placed_out, answered_out = int(counts.placed_out), int(counts.answered_out)
    return WeekFigures(
        week_start=monday.isoformat(),
        calls=int(counts.calls),
        answered=int(counts.answered),
        answer_rate=(
            round(answered_out / placed_out, 4)
            if placed_out >= diagnose.MIN_ANSWERED_CALLS
            else None
        ),
        drop_off_step=step or None,
        drop_off_lost=lost,
        goals=int(counts.goals),
        fixes=await _fixes(session, since, until),
        best_name=best.name if best else None,
        best_goal_rate=round(best.goal_rate, 4) if best and best.goal_rate is not None else None,
    )


#: What the model is told. The figures are the only facts it may use; the owner reads the
#: result, so it names no provider (D-679) and is plain prose a phone screen shows.
SYSTEM_PROMPT: Final = (
    "You write a short weekly note to a small-business owner about how their AI phone agents "
    "did last week. Write one paragraph of at most 80 words in plain, friendly English. Use "
    "only the figures in the JSON you are given and never invent a number, a name or a cause. "
    "Say the answer rate as a percentage when it is given, the script step where most people "
    "dropped off when one is named, how many fixes were made, and which campaign did best "
    "when one is named. Leave out anything that is null. No markdown, lists, headings, emoji "
    "or quotation marks. Do not name any company or technology provider."
)


def prompt_figures(figures: WeekFigures) -> str:
    return json.dumps(asdict(figures), ensure_ascii=False, sort_keys=True)


def clean_summary(content: str | None) -> str:
    """The model's paragraph as one plain line, cut to what the column holds."""
    words = " ".join((content or "").replace("*", "").replace("#", "").split())
    return words[:WEEKLY_SUMMARY_MAX]


async def has_summary(session: AsyncSession, week_start: date) -> bool:
    return bool(
        (
            await session.execute(
                text("SELECT 1 FROM weekly_summaries WHERE week_start = :w"), {"w": week_start}
            )
        ).scalar()
    )


async def store(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    figures: WeekFigures,
    summary: str,
    model: str,
) -> bool:
    """Write the week's summary once; False when that week already has one."""
    result = await session.execute(
        text(
            "INSERT INTO weekly_summaries (id, tenant_id, week_start, summary, figures, model) "
            "VALUES (:id, :t, :w, :s, CAST(:f AS jsonb), :m) "
            "ON CONFLICT (tenant_id, week_start) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "t": tenant_id,
            "w": date.fromisoformat(figures.week_start),
            "s": summary,
            "f": prompt_figures(figures),
            "m": model,
        },
    )
    return bool(rowcount_of(result))


@dataclass(frozen=True, slots=True)
class StoredSummary:
    id: UUID
    week_start: date
    summary: str
    figures: dict[str, Any]
    created_at: datetime


async def list_summaries(session: AsyncSession, *, limit: int) -> list[StoredSummary]:
    rows = (
        await session.execute(
            text(
                "SELECT id, week_start, summary, figures, created_at FROM weekly_summaries "
                "ORDER BY week_start DESC LIMIT :n"
            ),
            {"n": min(limit, MAX_LISTED)},
        )
    ).all()
    return [
        StoredSummary(
            id=r.id,
            week_start=r.week_start,
            summary=str(r.summary),
            figures=r.figures if isinstance(r.figures, dict) else {},
            created_at=r.created_at,
        )
        for r in rows
    ]


__all__ = [
    "MAX_LISTED",
    "MIN_CALLS",
    "SYSTEM_PROMPT",
    "StoredSummary",
    "WeekFigures",
    "clean_summary",
    "closed_week",
    "has_summary",
    "list_summaries",
    "prompt_figures",
    "store",
    "week_figures",
]
