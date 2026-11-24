"""The account-wide Improve page (founder, 24-25 Nov 2026): what would make results better
across every campaign and Inbound line, or belongs to the account itself. A campaign's or
line's own Improve tab (`diagnose.py`, `learning.py`) owns its controls; this module only
finds the patterns that span them and names the holder to fix.

Every reading is a bounded query under the caller's RLS session over the last `WINDOW_DAYS`
days, on the same definitions the holder tabs use (`learning.ANSWERED_SQL`,
`diagnose.EARLY_HANG_UP_S`, `diagnose.MIN_ANSWERED_CALLS`), so a figure here and the same
figure on a campaign's tab cannot disagree. Only ids, counts, enum columns, step names and the
business's own names and scripts are read, never transcript words (hard rule 6).

Money is the client's charge for each holder's calls (`credit_ledger` `usage` debits keyed by
call id, as `results.summary` reads one campaign's), summed as NUMERIC into a Decimal (hard
rule 7).

Not here, on purpose: each person's best hour to be called. Reusing one campaign's call data
to time another campaign's call to the same person needs a reading of the DPDP purpose limits
first, so it waits on that decision.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.call_mistakes import LESSONS
from apps.api.agents.mistake_fixes import HolderKind
from apps.api.billing.rates import ROUNDING
from apps.api.campaigns import diagnose
from apps.api.campaigns.learning import ANSWERED_SQL
from apps.api.crm.lead_definition import BECAME_LEADS_SQL

WINDOW_DAYS: Final = diagnose.WINDOW_DAYS
#: Campaigns and lines compared, most answered calls first.
MAX_HOLDERS: Final = 30
#: Calling numbers watched, most calls first.
MAX_NUMBERS: Final = 10
#: IST weeks drawn per calling number.
NUMBER_WEEKS: Final = 8
#: A number's last week against the four before it.
RECENT_DAYS: Final = 7
BASELINE_DAYS: Final = 28
#: Calls placed before a number's answer rate is judged: in its last week, and in the four
#: weeks before. Fewer is chance.
MIN_RECENT_PLACED: Final = 30
MIN_BASELINE_PLACED: Final = 60
#: The answer rate falling to this share of its own baseline or lower is a sharp drop, the
#: pattern a number carriers have started labelling as spam shows.
SPAM_DROP_RATIO: Final = 0.6
#: A mistake kind on this many holders or more is the agent's or the company training's,
#: not one script's.
MIN_HOLDERS_FOR_PATTERN: Final = 2
TOP_PATTERNS: Final = 5
#: Agents named per mistake pattern.
MAX_PATTERN_AGENTS: Final = 5
#: One person rung by two or more campaigns inside this many days is called too often.
TOO_OFTEN_DAYS: Final = 7
MAX_FIXES: Final = 20
#: Automatic script writes shown in the fixes feed (`script_history.Author`).
PIP_AUTHORS: Final = ("pip_repair", "pip_outcomes", "pip_notices")
#: Opening lines differing by fewer words than this are the same length.
MIN_OPENING_WORDS_DIFF: Final = 4

_CENT: Final = Decimal("0.01")


def _since(now: datetime | None, days: int = WINDOW_DAYS) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=days)


def _rate(part: int, whole: int, minimum: int) -> float | None:
    return part / whole if whole >= minimum and whole > 0 else None


# --- 1. Number health ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NumberWeek:
    week_start: date
    placed: int
    answered: int


@dataclass(frozen=True, slots=True)
class NumberHealth:
    e164: str
    weeks: list[NumberWeek]
    recent_placed: int
    recent_answered: int
    baseline_placed: int
    baseline_answered: int

    @property
    def recent_rate(self) -> float | None:
        return _rate(self.recent_answered, self.recent_placed, MIN_RECENT_PLACED)

    @property
    def baseline_rate(self) -> float | None:
        return _rate(self.baseline_answered, self.baseline_placed, MIN_BASELINE_PLACED)

    @property
    def dropped(self) -> bool:
        """The last week's answer rate fell to `SPAM_DROP_RATIO` of the four weeks before, on
        enough calls in both."""
        recent, baseline = self.recent_rate, self.baseline_rate
        return (
            recent is not None
            and baseline is not None
            and baseline > 0
            and recent <= baseline * SPAM_DROP_RATIO
        )


_OUTBOUND_REAL: Final = (
    "c.direction = 'outbound' AND c.from_e164 IS NOT NULL AND c.not_placed_reason IS NULL "
    "AND NOT (c.trial_call OR c.paid_test_call)"
)
_AT: Final = "COALESCE(c.started_at, c.created_at)"


async def number_health(
    session: AsyncSession, *, now: datetime | None = None
) -> list[NumberHealth]:
    moment = now or datetime.now(UTC)
    recent_since = moment - timedelta(days=RECENT_DAYS)
    baseline_since = recent_since - timedelta(days=BASELINE_DAYS)
    weeks_since = moment - timedelta(weeks=NUMBER_WEEKS)
    totals = (
        await session.execute(
            text(
                "SELECT c.from_e164 AS e164, "
                f"count(*) FILTER (WHERE {_AT} >= :recent) AS recent_placed, "
                f"count(*) FILTER (WHERE {_AT} >= :recent AND {ANSWERED_SQL}) AS recent_answered, "
                f"count(*) FILTER (WHERE {_AT} < :recent AND {_AT} >= :base) AS base_placed, "
                f"count(*) FILTER (WHERE {_AT} < :recent AND {_AT} >= :base "
                f"AND {ANSWERED_SQL}) AS base_answered "
                f"FROM calls c WHERE {_OUTBOUND_REAL} AND {_AT} >= :since "
                "GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT :n"
            ),
            {
                "recent": recent_since,
                "base": baseline_since,
                "since": min(baseline_since, weeks_since),
                "n": MAX_NUMBERS,
            },
        )
    ).all()
    if not totals:
        return []
    numbers = [str(r.e164) for r in totals]
    week_rows = (
        await session.execute(
            text(
                f"SELECT c.from_e164 AS e164, (date_trunc('week', {_AT} AT TIME ZONE "
                "'Asia/Kolkata'))::date AS wk, count(*) AS placed, "
                f"count(*) FILTER (WHERE {ANSWERED_SQL}) AS answered "
                f"FROM calls c WHERE {_OUTBOUND_REAL} AND {_AT} >= :since "
                "AND c.from_e164 = ANY(:numbers) GROUP BY 1, 2 ORDER BY 1, 2"
            ),
            {"since": weeks_since, "numbers": numbers},
        )
    ).all()
    by_number: dict[str, list[NumberWeek]] = {n: [] for n in numbers}
    for r in week_rows:
        by_number[str(r.e164)].append(NumberWeek(r.wk, int(r.placed), int(r.answered)))
    return [
        NumberHealth(
            e164=str(r.e164),
            weeks=by_number[str(r.e164)],
            recent_placed=int(r.recent_placed),
            recent_answered=int(r.recent_answered),
            baseline_placed=int(r.base_placed),
            baseline_answered=int(r.base_answered),
        )
        for r in totals
    ]


# --- 3 and 8. Compare campaigns and lines, and what each result cost --------------------------


@dataclass(frozen=True, slots=True)
class HolderFigures:
    kind: HolderKind
    id: UUID
    name: str
    placed: int
    answered: int
    goals: int
    early: int
    judged: int
    dropped: int
    #: The client's charge for the holder's calls in the window; None when the reader may not
    #: see money.
    spend_inr: Decimal | None
    opening_words: int | None
    steps: int | None
    #: The campaign's own calling hours as "HH:MM-HH:MM"; None for a line or the default window.
    calling_hours: str | None

    @property
    def answer_rate(self) -> float | None:
        return _rate(self.answered, self.placed, diagnose.MIN_ANSWERED_CALLS)

    @property
    def goal_rate(self) -> float | None:
        return _rate(self.goals, self.answered, diagnose.MIN_ANSWERED_CALLS)

    @property
    def early_rate(self) -> float | None:
        return _rate(self.early, self.answered, diagnose.MIN_ANSWERED_CALLS)

    @property
    def drop_off_share(self) -> float | None:
        """Judged calls that stopped before the script's last step."""
        return _rate(self.dropped, self.judged, diagnose.MIN_JUDGED_CALLS)

    @property
    def cost_per_goal_inr(self) -> Decimal | None:
        if self.spend_inr is None or self.goals == 0:
            return None
        return (self.spend_inr / self.goals).quantize(_CENT, rounding=ROUNDING)


DifferenceKind = Literal["opening_length", "step_count", "calling_hours"]


@dataclass(frozen=True, slots=True)
class Difference:
    kind: DifferenceKind
    best: str
    others: str
    #: What Pip is asked to write into another holder's script; None where the difference is
    #: one of the holder's own settings (its calling hours), which the owner changes there.
    instruction: str | None


@dataclass(frozen=True, slots=True)
class Comparison:
    holders: list[HolderFigures]
    best: HolderFigures | None
    differences: list[Difference] = field(default_factory=list)
    total_spend_inr: Decimal | None = None
    total_goals: int = 0

    @property
    def total_cost_per_goal_inr(self) -> Decimal | None:
        if self.total_spend_inr is None or self.total_goals == 0:
            return None
        return (self.total_spend_inr / self.total_goals).quantize(_CENT, rounding=ROUNDING)


_JUDGED: Final = "jsonb_typeof(c.step_progress->'steps') = 'array'"
_DROPPED: Final = (
    f"{_JUDGED} AND EXISTS (SELECT 1 FROM jsonb_array_elements(c.step_progress->'steps') s "
    "WHERE s->>'state' = 'not_reached')"
)


def _figures_sql(kind: HolderKind) -> str:
    column = "c.campaign_id" if kind == "campaign" else "c.inbound_line_id"
    real = "TRUE" if kind == "campaign" else "NOT (c.trial_call OR c.paid_test_call)"
    return (
        f"SELECT '{kind}' AS kind, {column} AS hid, "
        "count(*) FILTER (WHERE c.not_placed_reason IS NULL) AS placed, "
        f"count(*) FILTER (WHERE {ANSWERED_SQL}) AS answered, "
        f"count(*) FILTER (WHERE {ANSWERED_SQL} AND c.goal_reached = 'yes') AS goals, "
        f"count(*) FILTER (WHERE {ANSWERED_SQL} AND c.outcome_tag = 'hung_up_early' "
        "AND c.duration_s <= :early) AS early, "
        f"count(*) FILTER (WHERE {_JUDGED}) AS judged, "
        f"count(*) FILTER (WHERE {_DROPPED}) AS dropped "
        f"FROM calls c WHERE {column} IS NOT NULL AND {real} "
        f"AND {_AT} >= :since AND {_AT} < :until "
        "GROUP BY 2"
    )


def _script_shape(script: Any) -> tuple[int | None, int | None]:
    """Words in the opening line and the step count of a structured script; None for none."""
    if not isinstance(script, dict) or script.get("raw_override") is not None:
        return None, None
    opening = str(script.get("opening_line") or "").split()
    steps = script.get("steps")
    return (len(opening) or None), (len(steps) if isinstance(steps, list) and steps else None)


def _hours(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("start") and value.get("end"):
        return f"{value['start']}-{value['end']}"
    return None


async def compare_holders(
    session: AsyncSession,
    *,
    include_spend: bool,
    now: datetime | None = None,
    since: datetime | None = None,
) -> Comparison:
    """The last `WINDOW_DAYS` days to `now`, or the calls from `since` to `now` (the weekly
    summary's closed week)."""
    until = now or datetime.now(UTC)
    since = since or _since(until)
    rows = (
        await session.execute(
            text(
                f"SELECT * FROM ({_figures_sql('campaign')} UNION ALL "
                f"{_figures_sql('inbound_line')}) f "
                "ORDER BY f.answered DESC, f.placed DESC, f.hid LIMIT :n"
            ),
            {
                "since": since,
                "until": until,
                "early": diagnose.EARLY_HANG_UP_S,
                "n": MAX_HOLDERS,
            },
        )
    ).all()
    if not rows:
        return Comparison(
            holders=[], best=None, total_spend_inr=Decimal("0.00") if include_spend else None
        )
    campaign_ids = [r.hid for r in rows if r.kind == "campaign"]
    line_ids = [r.hid for r in rows if r.kind == "inbound_line"]
    details: dict[UUID, Any] = {}
    for row in (
        await session.execute(
            text(
                "SELECT id, name, script, calling_hours FROM campaigns WHERE id = ANY(:c) "
                "AND archived_at IS NULL UNION ALL "
                "SELECT id, name, script, NULL FROM inbound_lines WHERE id = ANY(:l) "
                "AND archived_at IS NULL"
            ),
            {"c": campaign_ids, "l": line_ids},
        )
    ).all():
        details[row.id] = row
    spend: dict[UUID, Decimal] = {}
    if include_spend:
        for row in (
            await session.execute(
                text(
                    "SELECT COALESCE(k.campaign_id, k.inbound_line_id) AS hid, "
                    "coalesce(-sum(l.delta), 0) AS spent FROM calls k JOIN credit_ledger l "
                    "ON l.tenant_id = k.tenant_id AND l.reason = 'usage' AND l.ref = k.id::text "
                    "WHERE (k.campaign_id = ANY(:c) OR k.inbound_line_id = ANY(:l)) "
                    "AND l.delta < 0 AND COALESCE(k.started_at, k.created_at) >= :since "
                    "AND COALESCE(k.started_at, k.created_at) < :until GROUP BY 1"
                ),
                {"c": campaign_ids, "l": line_ids, "since": since, "until": until},
            )
        ).all():
            spend[row.hid] = Decimal(row.spent).quantize(_CENT, rounding=ROUNDING)
    holders: list[HolderFigures] = []
    for r in rows:
        detail = details.get(r.hid)
        if detail is None:
            continue  # archived since: its own page is gone, so nothing links to it
        words, steps = _script_shape(detail.script)
        holders.append(
            HolderFigures(
                kind=r.kind,
                id=r.hid,
                name=str(detail.name),
                placed=int(r.placed),
                answered=int(r.answered),
                goals=int(r.goals),
                early=int(r.early),
                judged=int(r.judged),
                dropped=int(r.dropped),
                spend_inr=spend.get(r.hid, Decimal("0.00")) if include_spend else None,
                opening_words=words,
                steps=steps,
                calling_hours=_hours(detail.calling_hours),
            )
        )
    best = best_holder(holders)
    return Comparison(
        holders=holders,
        best=best,
        differences=differences(best, holders) if best else [],
        total_spend_inr=(
            sum((h.spend_inr or Decimal("0.00") for h in holders), Decimal("0.00"))
            if include_spend
            else None
        ),
        total_goals=sum(h.goals for h in holders),
    )


def best_holder(holders: list[HolderFigures]) -> HolderFigures | None:
    """The holder with the highest goal rate, once two or more have enough answered calls to
    have one: a single measured holder has nothing to be best against."""
    measured = [h for h in holders if h.goal_rate is not None]
    if len(measured) < 2:
        return None
    top = max(measured, key=lambda h: (h.goal_rate or 0.0, h.answered))
    return top if (top.goal_rate or 0.0) > 0 else None


def differences(best: HolderFigures, holders: list[HolderFigures]) -> list[Difference]:
    """What is measurably different about the best holder against the other measured ones.
    Each is computed from the scripts and settings; one with no value on either side is not
    said."""
    others = [h for h in holders if h.goal_rate is not None and h.id != best.id]
    found: list[Difference] = []
    words = [h.opening_words for h in others if h.opening_words is not None]
    if best.opening_words is not None and words:
        typical = round(statistics.median(words))
        if abs(best.opening_words - typical) >= MIN_OPENING_WORDS_DIFF:
            shorter = best.opening_words < typical
            found.append(
                Difference(
                    kind="opening_length",
                    best=f"{best.opening_words} words",
                    others=f"{typical} words",
                    instruction=(
                        f"Make the opening line {'shorter' if shorter else 'longer'}, about "
                        f"{best.opening_words} words, as on “{best.name}”, which reaches "
                        "its goal most often. Keep the AI and recording notices it says. Keep "
                        "the steps as they are."
                    ),
                )
            )
    counts = [h.steps for h in others if h.steps is not None]
    if best.steps is not None and counts:
        typical_steps = statistics.median(counts)
        if abs(best.steps - typical_steps) >= 1:
            found.append(
                Difference(
                    kind="step_count",
                    best=f"{best.steps} steps",
                    others=f"{typical_steps:g} steps",
                    instruction=(
                        f"Rework the script into {best.steps} steps, as on “{best.name}”, "
                        "which reaches its goal most often. Keep the opening line and its "
                        "notices as they are."
                    ),
                )
            )
    if best.kind == "campaign" and best.calling_hours is not None:
        other_hours = [h.calling_hours for h in others if h.kind == "campaign"]
        differ = [h for h in other_hours if h != best.calling_hours]
        if other_hours and len(differ) * 2 >= len(other_hours):
            common = statistics.mode([h or "all day" for h in differ])
            found.append(
                Difference(
                    kind="calling_hours",
                    best=best.calling_hours,
                    others=common,
                    instruction=None,
                )
            )
    return found


# --- 4. Mistakes on more than one campaign or line -----------------------------------------


@dataclass(frozen=True, slots=True)
class PatternAgent:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class MistakePattern:
    kind: str
    label: str
    calls: int
    holders: int
    agents: list[PatternAgent]


async def mistake_patterns(
    session: AsyncSession, *, now: datetime | None = None
) -> list[MistakePattern]:
    rows = (
        await session.execute(
            text(
                "SELECT m.kind, count(DISTINCT m.call_id) AS calls, "
                "count(DISTINCT COALESCE(c.campaign_id, c.inbound_line_id)) AS holders, "
                "(array_agg(DISTINCT c.agent_id))[1:CAST(:agents AS int)] AS agents "
                "FROM call_mistakes m JOIN calls c ON c.id = m.call_id "
                "WHERE m.call_started_at >= :since AND m.kind = ANY(:kinds) "
                "AND (c.campaign_id IS NOT NULL OR (c.inbound_line_id IS NOT NULL "
                "AND NOT (c.trial_call OR c.paid_test_call))) "
                "GROUP BY m.kind "
                "HAVING count(DISTINCT COALESCE(c.campaign_id, c.inbound_line_id)) >= :min "
                "ORDER BY calls DESC, m.kind LIMIT :n"
            ),
            {
                "since": _since(now),
                "kinds": sorted(LESSONS),
                "min": MIN_HOLDERS_FOR_PATTERN,
                "n": TOP_PATTERNS,
                "agents": MAX_PATTERN_AGENTS,
            },
        )
    ).all()
    agent_ids = sorted({a for r in rows for a in (r.agents or [])})
    names: dict[UUID, str] = {}
    if agent_ids:
        names = {
            r.id: str(r.name)
            for r in (
                await session.execute(
                    text("SELECT id, name FROM agents WHERE id = ANY(:ids)"), {"ids": agent_ids}
                )
            ).all()
        }
    return [
        MistakePattern(
            kind=str(r.kind),
            label=LESSONS[str(r.kind)].label,
            calls=int(r.calls),
            holders=int(r.holders),
            agents=[PatternAgent(a, names[a]) for a in (r.agents or []) if a in names],
        )
        for r in rows
    ]


# --- 6. Hot leads and promised call-backs --------------------------------------------------


@dataclass(frozen=True, slots=True)
class FollowUpCounts:
    #: Leads standing at the goal-reached stage, as the dashboard counts them.
    hot_leads: int
    #: Call-backs booked and not yet made.
    callbacks_due: int


async def follow_up_counts(session: AsyncSession) -> FollowUpCounts:
    hot = (
        await session.execute(
            text(f"SELECT count(*) FROM {BECAME_LEADS_SQL} AS bl WHERE bl.status = 'hot'")
        )
    ).scalar_one()
    due = (
        await session.execute(
            text("SELECT count(*) FROM scheduled_callbacks WHERE status = 'scheduled'")
        )
    ).scalar_one()
    return FollowUpCounts(hot_leads=int(hot), callbacks_due=int(due))


# --- 7. Contact list health ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContactHealth:
    #: People on the account's current campaign lists who are on a do-not-call list.
    on_dnc: int
    #: People on those lists whose every try failed to connect.
    unreachable: int
    #: People rung by two or more campaigns in the last `TOO_OFTEN_DAYS` days.
    called_too_often: int
    too_often_days: int


async def contact_health(session: AsyncSession, *, now: datetime | None = None) -> ContactHealth:
    row = (
        await session.execute(
            text(
                "SELECT count(DISTINCT cc.phone_e164) FILTER (WHERE cc.status = 'dnc_blocked' "
                "OR EXISTS (SELECT 1 FROM dnc_list d WHERE d.phone_e164 = cc.phone_e164)) "
                "AS dnc, count(DISTINCT cc.phone_e164) FILTER (WHERE cc.status = 'failed') "
                "AS failed FROM campaign_contacts cc JOIN campaigns k ON k.id = cc.campaign_id "
                "WHERE k.archived_at IS NULL"
            )
        )
    ).one()
    often = (
        await session.execute(
            text(
                "SELECT count(*) FROM (SELECT c.to_e164 FROM calls c "
                "WHERE c.direction = 'outbound' AND c.campaign_id IS NOT NULL "
                f"AND c.to_e164 IS NOT NULL AND {_AT} >= :since "
                "GROUP BY 1 HAVING count(DISTINCT c.campaign_id) >= 2) x"
            ),
            {"since": _since(now, TOO_OFTEN_DAYS)},
        )
    ).scalar_one()
    return ContactHealth(
        on_dnc=int(row.dnc),
        unreachable=int(row.failed),
        called_too_often=int(often),
        too_often_days=TOO_OFTEN_DAYS,
    )


# --- 9. Pip's fixes, in one feed -----------------------------------------------------------

FixKind = Literal["pip_repair", "pip_outcomes", "pip_notices", "best_hours", "opening_winner"]


@dataclass(frozen=True, slots=True)
class PipFix:
    kind: FixKind
    holder_kind: HolderKind
    holder_id: UUID
    holder_name: str
    at: datetime
    #: For an opening test, the opening that won; for best hours, the hours set.
    detail: str | None


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def pip_fixes(session: AsyncSession, *, now: datetime | None = None) -> list[PipFix]:
    since = _since(now)
    fixes: list[PipFix] = []
    for r in (
        await session.execute(
            text(
                "SELECT v.author, v.created_at, v.campaign_id, v.inbound_line_id, "
                "COALESCE(k.name, l.name) AS name FROM script_versions v "
                "LEFT JOIN campaigns k ON k.id = v.campaign_id "
                "LEFT JOIN inbound_lines l ON l.id = v.inbound_line_id "
                "WHERE v.author = ANY(:authors) AND v.created_at >= :since "
                "AND COALESCE(k.archived_at, l.archived_at) IS NULL "
                "ORDER BY v.created_at DESC LIMIT :n"
            ),
            {"authors": list(PIP_AUTHORS), "since": since, "n": MAX_FIXES},
        )
    ).all():
        fixes.append(
            PipFix(
                kind=r.author,
                holder_kind="campaign" if r.campaign_id else "inbound_line",
                holder_id=r.campaign_id or r.inbound_line_id,
                holder_name=str(r.name or ""),
                at=r.created_at,
                detail=None,
            )
        )
    for r in (
        await session.execute(
            text(
                "SELECT id, name, best_hours_applied, opening_test_result FROM campaigns "
                "WHERE archived_at IS NULL AND ("
                "best_hours_applied->>'by' = 'pip' OR "
                "opening_test_result->>'applied' = 'true') "
                "ORDER BY updated_at DESC LIMIT :n"
            ),
            {"n": MAX_FIXES},
        )
    ).all():
        hours = r.best_hours_applied if isinstance(r.best_hours_applied, dict) else {}
        at = _when(hours.get("at")) if hours.get("by") == "pip" else None
        if at is not None and at >= since:
            fixes.append(
                PipFix("best_hours", "campaign", r.id, str(r.name), at, _hours(hours.get("block")))
            )
        test = r.opening_test_result if isinstance(r.opening_test_result, dict) else {}
        won = _when(test.get("at")) if test.get("applied") and not test.get("undone_at") else None
        if won is not None and won >= since:
            opening = str(test.get("opening_b") or "") if test.get("winner") == "b" else None
            fixes.append(PipFix("opening_winner", "campaign", r.id, str(r.name), won, opening))
    fixes.sort(key=lambda f: f.at, reverse=True)
    return fixes[:MAX_FIXES]


__all__ = [
    "MAX_FIXES",
    "MAX_HOLDERS",
    "MAX_NUMBERS",
    "MIN_BASELINE_PLACED",
    "MIN_RECENT_PLACED",
    "NUMBER_WEEKS",
    "SPAM_DROP_RATIO",
    "TOO_OFTEN_DAYS",
    "WINDOW_DAYS",
    "Comparison",
    "ContactHealth",
    "Difference",
    "FollowUpCounts",
    "HolderFigures",
    "MistakePattern",
    "NumberHealth",
    "NumberWeek",
    "PipFix",
    "best_holder",
    "compare_holders",
    "contact_health",
    "differences",
    "follow_up_counts",
    "mistake_patterns",
    "number_health",
    "pip_fixes",
]
