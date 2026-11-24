"""What a campaign's own calls teach it (D-992): which block of the day people answer in,
and which of two opening lines keeps them on the call.

Both count PEOPLE, never calls: a person rung three times at 10am is one person tried at
10am, so the retry ladder cannot inflate the hours it rings in. Both read only ids, phone
numbers as join keys, times, durations and the enum columns of `calls`; never transcript
text (hard rule 6). Hours are IST (D-709), named in the SQL.

THE STATISTICS. Each comparison is a Beta-Binomial one: with a uniform prior, a rate seen
as `s` successes in `n` people has the posterior Beta(1 + s, 1 + n - s), and
`chance_better` is the exact probability that one posterior draw beats the other, by Evan
Miller's closed form (evanmiller.org/bayesian-ab-testing.html, read 24 Nov 2026; the sum
over i < alpha_B of B(alpha_A + i, beta_A + beta_B) / ((beta_B + i) B(1 + i, beta_B)
B(alpha_A, beta_A)), computed in logs). A chance is reported, never a verdict, and an
automatic change needs both a high chance AND a minimum sample, so a lucky first fifty
calls cannot decide anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, exp, lgamma, log, sqrt
from statistics import NormalDist
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.call_timing import Block, blocks_within
from apps.api.crm.outcomes import HUNG_UP_EARLY_S


def _log_beta(a: float, b: float) -> float:
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def chance_better(
    *, base_successes: int, base_people: int, other_successes: int, other_people: int
) -> float:
    """The probability that the OTHER rate is higher than the BASE one, both under a
    uniform prior (Miller's closed form; see the module docstring). 0.5 when nothing is
    known about either."""
    alpha_a, beta_a = 1 + base_successes, 1 + base_people - base_successes
    alpha_b, beta_b = 1 + other_successes, 1 + other_people - other_successes
    total = 0.0
    for i in range(alpha_b):
        total += exp(
            _log_beta(alpha_a + i, beta_b + beta_a)
            - log(beta_b + i)
            - _log_beta(1 + i, beta_b)
            - _log_beta(alpha_a, beta_a)
        )
    return min(1.0, max(0.0, total))


def people_needed(p1: float, p2: float, *, alpha: float = 0.05, power: float = 0.8) -> int:
    """People per side to tell rate `p1` from `p2` with a two-sided test at `alpha` and the
    given power: Fleiss, Tytun and Ury (1980), Biometrics 36:343-6, without the continuity
    correction (the method `Hmisc::bpower` implements, its documentation read 24 Nov 2026).
    0.4 against 0.5 needs 388 a side."""
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    mean = (p1 + p2) / 2
    spread = z_alpha * sqrt(2 * mean * (1 - mean)) + z_beta * sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return ceil(spread**2 / (p1 - p2) ** 2)


# --- Best hours ---------------------------------------------------------------------------

#: A block, and the rest of the day it is compared with, each need this many people tried
#: before a block can be recommended.
MIN_PEOPLE_PER_BLOCK: Final = 50
#: The chance a block's answer rate beats the rest of the day's before it is recommended.
#: Up to four blocks are compared, so 5% shared among them (Bonferroni) is 1.25% each.
BLOCK_CHANCE: Final = 0.9875

#: A person picked up: the call connected (`crm/outcomes.CONNECTED_STATUSES`).
_PICKED_UP: Final = "c.status = 'completed'"
#: A call someone answered: it has an outcome and it is not "not answered".
ANSWERED_SQL: Final = "(c.outcome_tag IS NOT NULL AND c.outcome_tag <> 'missed')"


@dataclass(frozen=True)
class HourRate:
    hour: int
    #: People tried in this hour (each counted once, however many times they were rung).
    people: int
    #: Of them, people who picked up in this hour.
    reached: int

    @property
    def rate(self) -> float:
        return self.reached / self.people if self.people else 0.0


async def answer_rate_by_hour(session: AsyncSession, campaign_id: UUID) -> list[HourRate]:
    """Per IST hour, the people tried and the people who picked up then."""
    rows = (
        await session.execute(
            text(
                "SELECT hour, count(*) AS people, count(*) FILTER (WHERE picked_up) AS reached "
                "FROM (SELECT c.to_e164, EXTRACT(HOUR FROM COALESCE(c.started_at, c.created_at) "
                "AT TIME ZONE 'Asia/Kolkata')::int AS hour, "
                f"bool_or({_PICKED_UP}) AS picked_up "
                "FROM calls c WHERE c.campaign_id = :cid AND c.direction = 'outbound' "
                "AND c.to_e164 IS NOT NULL GROUP BY 1, 2) tried "
                "GROUP BY hour ORDER BY hour"
            ),
            {"cid": campaign_id},
        )
    ).all()
    return [HourRate(hour=int(r.hour), people=int(r.people), reached=int(r.reached)) for r in rows]


BestHoursState = Literal["empty", "too_few", "measuring", "actionable"]


@dataclass(frozen=True)
class BlockRate:
    block: Block
    people: int
    reached: int
    #: The chance this block's answer rate beats the rest of the day's; None until both
    #: have enough people to judge.
    chance: float | None

    @property
    def rate(self) -> float:
        return self.reached / self.people if self.people else 0.0


@dataclass(frozen=True)
class BestHours:
    state: BestHoursState
    blocks: list[BlockRate]
    #: The block to call in, when `actionable`.
    best: BlockRate | None


def best_block(rates: list[HourRate], calling_hours: dict[str, Any] | None) -> BestHours:
    """Which block of the campaign's calling day people answer in, compared with the rest.

    A person tried in two blocks counts in both, as each hour counts them once. Only a block
    with `MIN_PEOPLE_PER_BLOCK` people, against a rest of the day with as many, is judged;
    it is recommended at `BLOCK_CHANCE`."""
    if not rates:
        return BestHours(state="empty", blocks=[], best=None)
    by_hour = {r.hour: r for r in rates}
    total_people = sum(r.people for r in rates)
    total_reached = sum(r.reached for r in rates)
    out: list[BlockRate] = []
    for block in blocks_within(calling_hours):
        people = sum(by_hour[h].people for h in block.hours() if h in by_hour)
        reached = sum(by_hour[h].reached for h in block.hours() if h in by_hour)
        judged = people >= MIN_PEOPLE_PER_BLOCK and (total_people - people >= MIN_PEOPLE_PER_BLOCK)
        chance = (
            chance_better(
                base_successes=total_reached - reached,
                base_people=total_people - people,
                other_successes=reached,
                other_people=people,
            )
            if judged
            else None
        )
        out.append(BlockRate(block=block, people=people, reached=reached, chance=chance))
    judged_blocks = [b for b in out if b.chance is not None]
    if not judged_blocks:
        return BestHours(state="too_few", blocks=out, best=None)
    top = max(judged_blocks, key=lambda b: b.chance or 0.0)
    if (top.chance or 0.0) >= BLOCK_CHANCE:
        return BestHours(state="actionable", blocks=out, best=top)
    return BestHours(state="measuring", blocks=out, best=None)


# --- The opening test ---------------------------------------------------------------------

#: A meaningful difference the test must be able to see: ten points in the share of people
#: who stay past the first twenty seconds, at the 50% where it takes the most people.
MEANINGFUL_FROM: Final = 0.5
MEANINGFUL_TO: Final = 0.6
#: People who picked up, per opening, before the test may decide (388).
MIN_ANSWERED_PER_OPENING: Final = people_needed(MEANINGFUL_FROM, MEANINGFUL_TO)
#: The chance one opening keeps more people on the call before it wins on its own.
WIN_CHANCE: Final = 0.95

#: A person stayed: a connected call that ran past the length `crm/outcomes` reads as hung
#: up early. The opening is said after pickup, so whether a call is answered cannot differ
#: between openings, and staying is the first thing an opening can change.
_STAYED: Final = f"({_PICKED_UP} AND c.duration_s >= {HUNG_UP_EARLY_S})"


@dataclass(frozen=True)
class OpeningResult:
    variant: str
    #: People who were given this opening.
    people: int
    #: Of them, people who picked up.
    answered: int
    #: Of them, people who stayed past the first twenty seconds.
    stayed: int
    goal_reached: int

    @property
    def stayed_rate(self) -> float | None:
        return self.stayed / self.answered if self.answered else None

    @property
    def goal_rate(self) -> float | None:
        return self.goal_reached / self.answered if self.answered else None


async def opening_results(session: AsyncSession, campaign_id: UUID) -> list[OpeningResult]:
    """Per opening, over every call each person was given (all their tries) since the test
    began (`campaigns.opening_test_started_at`), the people who heard it, picked up, stayed,
    and reached the goal. A person's label is fixed by their contact id and outlives a test,
    so a person counts only with a call inside this test; a test begun before the start was
    recorded counts every call."""
    rows = (
        await session.execute(
            text(
                "SELECT variant, count(*) AS people, "
                "count(*) FILTER (WHERE picked_up) AS answered, "
                "count(*) FILTER (WHERE stayed) AS stayed, count(*) FILTER (WHERE reached) "
                "AS reached FROM (SELECT cc.id, cc.opening_variant AS variant, "
                f"COALESCE(bool_or({_PICKED_UP}), false) AS picked_up, "
                f"COALESCE(bool_or({_STAYED}), false) AS stayed, "
                "COALESCE(bool_or(c.goal_reached = 'yes'), false) AS reached "
                "FROM campaigns camp JOIN campaign_contacts cc ON cc.campaign_id = camp.id "
                "LEFT JOIN calls c ON c.campaign_id = cc.campaign_id "
                "AND c.to_e164 = cc.phone_e164 AND c.direction = 'outbound' "
                "AND (camp.opening_test_started_at IS NULL "
                "OR c.created_at >= camp.opening_test_started_at) "
                "WHERE camp.id = :cid AND cc.opening_variant IS NOT NULL "
                "GROUP BY cc.id, cc.opening_variant, camp.opening_test_started_at "
                "HAVING camp.opening_test_started_at IS NULL OR count(c.id) > 0"
                ") person GROUP BY variant"
            ),
            {"cid": campaign_id},
        )
    ).all()
    found = {
        str(r.variant): OpeningResult(
            variant=str(r.variant),
            people=int(r.people),
            answered=int(r.answered),
            stayed=int(r.stayed),
            goal_reached=int(r.reached),
        )
        for r in rows
    }
    return [
        found.get(v, OpeningResult(variant=v, people=0, answered=0, stayed=0, goal_reached=0))
        for v in ("a", "b")
    ]


OpeningState = Literal["too_few", "measuring", "decided"]


@dataclass(frozen=True)
class OpeningVerdict:
    state: OpeningState
    #: The chance the second opening keeps more people past twenty seconds.
    chance_b_better: float
    #: The chance the second opening reaches the goal more often (secondary, never decides).
    goal_chance_b_better: float
    winner: Literal["a", "b"] | None


def opening_verdict(results: list[OpeningResult]) -> OpeningVerdict:
    """The chance, and a winner only with `MIN_ANSWERED_PER_OPENING` a side and the chance
    past `WIN_CHANCE` either way."""
    a, b = results
    chance = chance_better(
        base_successes=a.stayed,
        base_people=a.answered,
        other_successes=b.stayed,
        other_people=b.answered,
    )
    goal_chance = chance_better(
        base_successes=a.goal_reached,
        base_people=a.answered,
        other_successes=b.goal_reached,
        other_people=b.answered,
    )
    if min(a.answered, b.answered) < MIN_ANSWERED_PER_OPENING:
        return OpeningVerdict("too_few", chance, goal_chance, None)
    if chance >= WIN_CHANCE:
        return OpeningVerdict("decided", chance, goal_chance, "b")
    if chance <= 1 - WIN_CHANCE:
        return OpeningVerdict("decided", chance, goal_chance, "a")
    return OpeningVerdict("measuring", chance, goal_chance, None)


#: Below this many people tried, the campaign's own answer rate is not used to size a test.
MIN_PEOPLE_FOR_ANSWER_RATE: Final = 30


@dataclass(frozen=True)
class ListSize:
    #: People the campaign may still call or has called (included, not opted out).
    people: int
    #: The share who pick up, from this campaign's own calls; None until enough are tried.
    answer_rate: float | None
    #: People who must pick up across both openings before the test can decide.
    answered_needed: int
    #: True or False when it can be said; None when it depends on an answer rate not known.
    large_enough: bool | None


async def list_size(session: AsyncSession, campaign_id: UUID) -> ListSize:
    """Whether this list can tell the two openings apart: both sides need
    `MIN_ANSWERED_PER_OPENING` people who picked up."""
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND included AND status <> 'dnc_blocked') AS people, "
                "(SELECT count(DISTINCT c.to_e164) FROM calls c WHERE c.campaign_id = :cid "
                "AND c.direction = 'outbound') AS tried, "
                "(SELECT count(DISTINCT c.to_e164) FROM calls c WHERE c.campaign_id = :cid "
                f"AND c.direction = 'outbound' AND {_PICKED_UP}) AS reached"
            ),
            {"cid": campaign_id},
        )
    ).one()
    people, tried, reached = int(row.people), int(row.tried), int(row.reached)
    needed = 2 * MIN_ANSWERED_PER_OPENING
    rate = reached / tried if tried >= MIN_PEOPLE_FOR_ANSWER_RATE else None
    if people < needed:
        enough: bool | None = False
    elif rate is None:
        enough = None
    else:
        enough = people * rate >= needed
    return ListSize(people=people, answer_rate=rate, answered_needed=needed, large_enough=enough)


__all__ = [
    "BLOCK_CHANCE",
    "MIN_ANSWERED_PER_OPENING",
    "MIN_PEOPLE_PER_BLOCK",
    "WIN_CHANCE",
    "BestHours",
    "BlockRate",
    "HourRate",
    "ListSize",
    "OpeningResult",
    "OpeningVerdict",
    "answer_rate_by_hour",
    "best_block",
    "chance_better",
    "list_size",
    "opening_results",
    "opening_verdict",
    "people_needed",
]
