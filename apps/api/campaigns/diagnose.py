"""What goes wrong on a campaign's or Inbound line's calls, for its Improve tab (D-1042, 24 Nov
2026): where people drop off in the script, which call mistakes recur, how many hang up while
the opening is said, and why people said no. The holder's sibling of `learning.py`, which
answers when to call and which opening works.

Each reading is one bounded query under the caller's RLS session, over the holder's real
calls in the last `WINDOW_DAYS` days: a campaign's calls carry its id (its test calls do not),
a line's test calls carry the line's id too and are left out by their flags. Only ids,
counts, step names and enum columns are read, never transcript words (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from calevate_shared.extraction import REFUSAL_REASONS, RefusalReason
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_heal
from apps.api.agents.call_mistakes import LESSONS
from apps.api.agents.mistake_fixes import Holder, HolderKind
from apps.api.campaigns.learning import ANSWERED_SQL

#: How far back every reading looks: the call-mistake window, so a kind counted here is one
#: the agent's own list counts too.
WINDOW_DAYS: Final = 30
#: Calls whose steps were judged before the drop-off bars are drawn: fewer is chance.
MIN_JUDGED_CALLS: Final = 10
#: Answered calls before an early hang-up rate is shown, for this holder and for its peers.
MIN_ANSWERED_CALLS: Final = 20
#: A hang-up this soon after answering is one in the opening line.
EARLY_HANG_UP_S: Final = 20
#: The mistake kinds shown, most calls first.
TOP_MISTAKES: Final = 5
#: The steps read; a script has far fewer, and a reading from an older, longer script stops
#: here rather than growing the answer.
MAX_STEPS: Final = 30

#: What has been done about a mistake kind since the latest call that showed it, in the call
#: page's terms (`script_heal.call_fix_states`): the script was repaired of it, a repair is
#: under way, or no repair reached it and our team has it.
FixStatus = Literal["repaired", "repairing", "told"]


def _id_column(kind: HolderKind) -> str:
    return "c.campaign_id" if kind == "campaign" else "c.inbound_line_id"


def _real_calls(kind: HolderKind) -> str:
    """The holder kind's calls that are not the owner's test calls."""
    return "TRUE" if kind == "campaign" else "NOT (c.trial_call OR c.paid_test_call)"


def _holder_calls(kind: HolderKind) -> str:
    return (
        f"{_id_column(kind)} = :hid AND {_real_calls(kind)} "
        "AND COALESCE(c.started_at, c.created_at) >= :since"
    )


def _since(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)


# --- Where people drop off -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepCount:
    step: int
    #: The step's name as the newest judged call had it (the script may have changed).
    name: str
    reached: int
    not_reached: int
    unclear: int
    #: Calls that reached the step before but not this one: this step's own loss.
    lost_here: int = 0


@dataclass(frozen=True, slots=True)
class DropOff:
    judged_calls: int
    steps: list[StepCount]
    #: The step that loses the most people, or None below the sample or with no loss.
    worst_step: int | None


def with_losses(steps: list[StepCount]) -> list[StepCount]:
    """Each step's own loss: the calls not reaching it less those already lost before it,
    so a call that stopped at step 2 counts against step 2 alone."""
    out: list[StepCount] = []
    before = 0
    for s in steps:
        out.append(
            StepCount(
                s.step, s.name, s.reached, s.not_reached, s.unclear, max(0, s.not_reached - before)
            )
        )
        before = max(before, s.not_reached)
    return out


async def drop_off(
    session: AsyncSession, holder: Holder, *, now: datetime | None = None
) -> DropOff:
    rows = (
        await session.execute(
            text(
                "SELECT (s->>'step')::int AS step, "
                "(array_agg(s->>'name' ORDER BY c.started_at DESC NULLS LAST))[1] AS name, "
                "count(*) FILTER (WHERE s->>'state' = 'reached') AS reached, "
                "count(*) FILTER (WHERE s->>'state' = 'not_reached') AS not_reached, "
                "count(*) FILTER (WHERE s->>'state' = 'unclear') AS unclear "
                "FROM calls c CROSS JOIN LATERAL jsonb_array_elements("
                "CASE WHEN jsonb_typeof(c.step_progress->'steps') = 'array' "
                "THEN c.step_progress->'steps' ELSE '[]'::jsonb END) s "
                f"WHERE {_holder_calls(holder.kind)} AND c.step_progress IS NOT NULL "
                "AND (s->>'step') ~ '^[0-9]{1,3}$' "
                "GROUP BY 1 ORDER BY 1 LIMIT :n"
            ),
            {"hid": holder.id, "since": _since(now), "n": MAX_STEPS},
        )
    ).all()
    steps = with_losses(
        [
            StepCount(
                step=int(r.step),
                name=str(r.name or ""),
                reached=int(r.reached),
                not_reached=int(r.not_reached),
                unclear=int(r.unclear),
            )
            for r in rows
        ]
    )
    # Every judged call holds a reading of every step of its script, so the most readings
    # any one step has is the number of calls judged.
    judged = max((s.reached + s.not_reached + s.unclear for s in steps), default=0)
    worst = max(steps, key=lambda s: (s.lost_here, -s.step), default=None)
    return DropOff(
        judged_calls=judged,
        steps=steps,
        worst_step=(
            worst.step
            if worst is not None and worst.lost_here > 0 and judged >= MIN_JUDGED_CALLS
            else None
        ),
    )


# --- Mistakes on this holder's calls -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HolderMistake:
    kind: str
    label: str
    calls: int
    last_call_id: UUID
    last_seen_at: datetime
    status: FixStatus


async def holder_mistakes(
    session: AsyncSession, holder: Holder, *, now: datetime | None = None
) -> list[HolderMistake]:
    rows = (
        await session.execute(
            text(
                "SELECT m.kind, count(DISTINCT m.call_id) AS calls, "
                "(array_agg(m.call_id ORDER BY m.call_started_at DESC, m.call_id DESC))[1] "
                "AS last_call, max(m.call_started_at) AS last_at "
                "FROM call_mistakes m JOIN calls c ON c.id = m.call_id "
                f"WHERE {_holder_calls(holder.kind)} AND m.call_started_at >= :since "
                "AND m.kind = ANY(:kinds) "
                "GROUP BY m.kind ORDER BY calls DESC, m.kind LIMIT :n"
            ),
            {"hid": holder.id, "since": _since(now), "kinds": sorted(LESSONS), "n": TOP_MISTAKES},
        )
    ).all()
    out: list[HolderMistake] = []
    for r in rows:
        kind = str(r.kind)
        # Judged against the latest call showing it, as that call's own page judges it.
        fix = (
            await script_heal.call_fix_states(
                session,
                campaign_id=holder.id if holder.kind == "campaign" else None,
                inbound_line_id=holder.id if holder.kind == "inbound_line" else None,
                call_started_at=r.last_at,
                kinds=[kind],
            )
        ).get(kind)
        out.append(
            HolderMistake(
                kind=kind,
                label=LESSONS[kind].label,
                calls=int(r.calls),
                last_call_id=r.last_call,
                last_seen_at=r.last_at,
                status=fix or "told",
            )
        )
    return out


# --- Openings that lose people -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EarlyHangUps:
    answered: int
    early: int
    #: The same over the account's other campaigns (or other lines), pooled.
    others_answered: int
    others_early: int

    @property
    def rate(self) -> float | None:
        return self.early / self.answered if self.answered >= MIN_ANSWERED_CALLS else None

    @property
    def others_rate(self) -> float | None:
        if self.others_answered < MIN_ANSWERED_CALLS:
            return None
        return self.others_early / self.others_answered


async def early_hang_ups(
    session: AsyncSession, holder: Holder, *, now: datetime | None = None
) -> EarlyHangUps:
    """Answered calls that hung up within `EARLY_HANG_UP_S` seconds, here and on the
    account's other holders of the same kind. A call with no duration is not counted as
    early: it is not known to be."""
    column = _id_column(holder.kind)
    rows = (
        await session.execute(
            text(
                f"SELECT {column} = :hid AS mine, count(*) AS answered, "
                "count(*) FILTER (WHERE c.outcome_tag = 'hung_up_early' "
                "AND c.duration_s <= :early) AS early "
                f"FROM calls c WHERE {column} IS NOT NULL AND {_real_calls(holder.kind)} "
                f"AND {ANSWERED_SQL} AND COALESCE(c.started_at, c.created_at) >= :since "
                "GROUP BY 1"
            ),
            {"hid": holder.id, "since": _since(now), "early": EARLY_HANG_UP_S},
        )
    ).all()
    found = {bool(r.mine): (int(r.answered), int(r.early)) for r in rows}
    mine, others = found.get(True, (0, 0)), found.get(False, (0, 0))
    return EarlyHangUps(
        answered=mine[0], early=mine[1], others_answered=others[0], others_early=others[1]
    )


# --- Why people said no --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReasonCount:
    reason: RefusalReason
    calls: int


async def refusal_reasons(
    session: AsyncSession, holder: Holder, *, now: datetime | None = None
) -> list[ReasonCount]:
    """The post-call reading's reasons (`calls.refusal_reason`), most calls first: one row
    per category of `REFUSAL_REASONS` at most."""
    rows = (
        await session.execute(
            text(
                "SELECT c.refusal_reason, count(*) AS calls FROM calls c "
                f"WHERE {_holder_calls(holder.kind)} AND c.refusal_reason IS NOT NULL "
                "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT :n"
            ),
            {"hid": holder.id, "since": _since(now), "n": len(REFUSAL_REASONS)},
        )
    ).all()
    return [
        ReasonCount(reason=r.refusal_reason, calls=int(r.calls))
        for r in rows
        if r.refusal_reason in REFUSAL_REASONS
    ]


__all__ = [
    "EARLY_HANG_UP_S",
    "MAX_STEPS",
    "MIN_ANSWERED_CALLS",
    "MIN_JUDGED_CALLS",
    "TOP_MISTAKES",
    "WINDOW_DAYS",
    "DropOff",
    "EarlyHangUps",
    "FixStatus",
    "HolderMistake",
    "ReasonCount",
    "StepCount",
    "drop_off",
    "early_hang_ups",
    "holder_mistakes",
    "refusal_reasons",
    "with_losses",
]
