"""What a campaign's own calls teach it (D-992): which hours people answer, and which of two
opening lines reaches the goal more often.

Both read only ids, times and the enum columns of `calls` (`outcome_tag`, `goal_reached`);
never transcript text (hard rule 6). Hours are IST (D-709), named in the SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: An hour needs this many calls before its answer rate is shown as a best time: fewer is
#: chance, and a "best hour" from two calls would steer a campaign on noise.
MIN_CALLS_PER_HOUR: Final = 5
#: Below this many answered people per opening, the test says it is too early to tell.
MIN_PEOPLE_PER_OPENING: Final = 20

#: A call someone answered: it has an outcome and it is not "not answered".
ANSWERED_SQL: Final = "(c.outcome_tag IS NOT NULL AND c.outcome_tag <> 'missed')"


@dataclass(frozen=True)
class HourRate:
    hour: int
    calls: int
    answered: int

    @property
    def rate(self) -> float:
        return self.answered / self.calls if self.calls else 0.0


async def answer_rate_by_hour(session: AsyncSession, campaign_id: UUID) -> list[HourRate]:
    rows = (
        await session.execute(
            text(
                "SELECT EXTRACT(HOUR FROM COALESCE(c.started_at, c.created_at) "
                "AT TIME ZONE 'Asia/Kolkata')::int AS hour, count(*) AS calls, "
                f"count(*) FILTER (WHERE {ANSWERED_SQL}) AS answered "
                "FROM calls c WHERE c.campaign_id = :cid AND c.direction = 'outbound' "
                "GROUP BY 1 ORDER BY 1"
            ),
            {"cid": campaign_id},
        )
    ).all()
    return [HourRate(hour=int(r.hour), calls=int(r.calls), answered=int(r.answered)) for r in rows]


def best_hours(rates: list[HourRate], *, top: int = 3) -> list[HourRate]:
    """The hours with the highest answer rate among those with enough calls to judge."""
    judged = [r for r in rates if r.calls >= MIN_CALLS_PER_HOUR]
    return sorted(judged, key=lambda r: (r.rate, r.calls), reverse=True)[:top]


@dataclass(frozen=True)
class OpeningResult:
    variant: str
    people: int
    answered: int
    goal_reached: int

    @property
    def goal_rate(self) -> float | None:
        return self.goal_reached / self.answered if self.answered else None


async def opening_results(session: AsyncSession, campaign_id: UUID) -> list[OpeningResult]:
    """Per opening: the people who heard it, how many answered, how many reached the goal
    (on their latest call, the one `campaign_contacts.last_call_id` names)."""
    rows = (
        await session.execute(
            text(
                "SELECT cc.opening_variant, count(*) AS people, "
                f"count(*) FILTER (WHERE {ANSWERED_SQL}) AS answered, "
                "count(*) FILTER (WHERE c.goal_reached = 'yes') AS reached "
                "FROM campaign_contacts cc LEFT JOIN calls c ON c.id = cc.last_call_id "
                "WHERE cc.campaign_id = :cid AND cc.opening_variant IS NOT NULL "
                "GROUP BY cc.opening_variant ORDER BY cc.opening_variant"
            ),
            {"cid": campaign_id},
        )
    ).all()
    found = {
        str(r.opening_variant): OpeningResult(
            variant=str(r.opening_variant),
            people=int(r.people),
            answered=int(r.answered),
            goal_reached=int(r.reached),
        )
        for r in rows
    }
    return [
        found.get(v, OpeningResult(variant=v, people=0, answered=0, goal_reached=0))
        for v in ("a", "b")
    ]


def opening_verdict(results: list[OpeningResult]) -> str:
    """One plain sentence. No winner until each opening has enough answered people."""
    a, b = results
    if min(a.answered, b.answered) < MIN_PEOPLE_PER_OPENING:
        return (
            f"Too early to tell: each opening needs {MIN_PEOPLE_PER_OPENING} people who "
            "answered before the two can be compared."
        )
    ra, rb = a.goal_rate or 0.0, b.goal_rate or 0.0
    if abs(ra - rb) < 0.05:
        return "So far both openings reach the goal about as often."
    better = "The second opening" if rb > ra else "The script's own opening"
    high, low = max(ra, rb), min(ra, rb)
    return f"{better} reaches the goal more often so far ({high:.0%} against {low:.0%})."
