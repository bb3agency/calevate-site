"""The agent readiness score, 0-100, and what to fix to raise it (D-870, weights D-873).

The gauge on each agent and on the dashboard (founder decision f7d9f716, point 2). It is
computed on every read from what is already stored; nothing is written and nothing is
cached, so the number moves the moment a test finishes or knowledge is added.

THE FORMULA (five components, 100 points; `score()` is the whole of it and is pure):

| component  | max | points                                                                 |
|------------|-----|------------------------------------------------------------------------|
| tests      |  35 | 35 * passed / counted, rounded half up, on the latest finished run,   |
|            |     | the owner's score (`trial_results.owner_score`); 0 with no such run    |
| knowledge  |  25 | D-870's 20-point reading scaled by 25/20, rounded half up. That        |
|            |     | reading is 10 for live knowledge (live sources + facts on file: 0 → 0, |
|            |     | 1-4 → 5, 5+ → 10) plus max(0, 10 - 2 * this agent's open knowledge     |
|            |     | gaps); the sum is scaled once, so the rounding happens once           |
| opening    |  15 | 15 when the opening line is set, at most `OPENING_LINE_MAX_CHARS` and  |
|            |     | fits the greeting budget with the notices as they are; 5 when set but  |
|            |     | too long; 0 when empty                                                 |
| live       |  15 | 15 when not live (D-916); live: 8, and 7 more when no draft is waiting |
|            |     | and the calling system's copy is not out of sync                       |
|            |     | (`DRIFT_STATES_OUT_OF_SYNC`)                                           |
| missed     |  10 | max(0, 10 - 2 * questions it could not answer in the last 7 days)      |

Why these weights: the practice tests are the closest thing to a real caller and carry the
most; knowledge and missed questions are the two halves of "does it know the business";
the opening line is what every caller hears first; a live agent whose callers hear an
out-of-date version is not ready, while one not live yet is not marked down for it (D-916).

The opening notices (D-163) are not a component: whether an agent volunteers "I am an AI"
or "this call is recorded" is the owner's choice and does not make it more or less ready
(D-873). The truthful answers when a caller asks (hard rule 5) are on every agent whatever
the switches say, so there is nothing for the score to measure there either. A component
never goes below 0, so the total is 0-100.

Every component that is not full contributes one `fix` with a realm-relative link to the
screen where it is fixed. Fixes are ordered by the points they would recover, largest
first, and ties by the table order above, so the list is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import test_conversations
from apps.api.agents.call_rules import OPENING_LINE_MAX_CHARS
from apps.api.agents.reconciliation import DRIFT_STATES_OUT_OF_SYNC
from apps.api.agents.roster import agent_by_id
from apps.api.agents.schemas import AgentOut
from apps.api.core.errors import ProblemError

ComponentKey = Literal["tests", "knowledge", "opening", "live", "missed"]
ComponentState = Literal["full", "partial", "none"]

MAX_POINTS: Final[dict[ComponentKey, int]] = {
    "tests": 35,
    "knowledge": 25,
    "opening": 15,
    "live": 15,
    "missed": 10,
}
COMPONENT_ORDER: Final[tuple[ComponentKey, ...]] = tuple(MAX_POINTS)
COMPONENT_LABELS: Final[dict[ComponentKey, str]] = {
    "tests": "Practice tests",
    "knowledge": "What it knows",
    "opening": "Opening line",
    "live": "Callers hear the latest version",
    "missed": "Questions it missed this week",
}
MISSED_WINDOW: Final = timedelta(days=7)
#: How many knowledge items count as "plenty" for the first half of the knowledge points.
KNOWLEDGE_PLENTY: Final = 5
#: D-870's knowledge reading, which D-873 scales to `MAX_POINTS["knowledge"]`.
KNOWLEDGE_READING_MAX: Final = 20
#: The share of the live points for being published and live; the rest is for being in sync.
LIVE_POINTS_PUBLISHED: Final = 8


class ReadinessFixOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: ComponentKey
    #: One plain sentence naming the next step.
    action: str
    #: Realm-relative link to the screen where it is fixed ("/agents/{id}?section=script").
    href: str
    #: The points this fix would add, at most.
    points: int


class ReadinessComponentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ComponentKey
    label: str
    points: int
    max_points: int
    state: ComponentState
    #: What was measured, in a sentence ("8 of 10 practice tests passed").
    detail: str


class AgentReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    agent_name: str
    score: int
    max_score: int = 100
    components: list[ReadinessComponentOut]
    #: Every component short of full, the biggest gain first.
    fixes: list[ReadinessFixOut]
    computed_at: datetime


class AccountReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The mean of the agents' scores, rounded; None with no agents.
    score: int | None
    agents: list[AgentReadinessOut]
    #: The biggest fixes across every agent, at most `MAX_ACCOUNT_FIXES`.
    top_fixes: list[ReadinessFixOut]
    computed_at: datetime


MAX_ACCOUNT_FIXES: Final = 5


@dataclass(frozen=True, slots=True)
class ReadinessInputs:
    """Everything the score reads, gathered by `gather()`; `score()` is pure over it."""

    agent_id: UUID
    agent_name: str
    tests_passed: int
    tests_counted: int
    has_test_run: bool
    knowledge_items: int
    open_gaps: int
    opening_chars: int
    #: Room the greeting leaves for the opening line with the notices as they are; None when
    #: the calling system sets no ceiling.
    opening_room: int | None
    published: bool
    live: bool
    draft_waiting: bool
    out_of_sync: bool
    missed_7d: int


def _state(points: int, maximum: int) -> ComponentState:
    return "full" if points >= maximum else "none" if points <= 0 else "partial"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _scaled_half_up(value: int, maximum: int, of: int) -> int:
    """`maximum * value / of`, rounded half up, in integers."""
    return (2 * maximum * value + of) // (2 * of)


def score(i: ReadinessInputs, *, now: datetime) -> AgentReadinessOut:
    """The D-873 formula over one agent's inputs. Pure and deterministic."""
    base = f"/agents/{i.agent_id}"
    components: list[ReadinessComponentOut] = []
    fixes: list[ReadinessFixOut] = []

    def add(key: ComponentKey, points: int, detail: str, fix: tuple[str, str] | None) -> None:
        maximum = MAX_POINTS[key]
        points = max(0, min(points, maximum))
        components.append(
            ReadinessComponentOut(
                key=key,
                label=COMPONENT_LABELS[key],
                points=points,
                max_points=maximum,
                state=_state(points, maximum),
                detail=detail,
            )
        )
        if points < maximum and fix is not None:
            fixes.append(
                ReadinessFixOut(component=key, action=fix[0], href=fix[1], points=maximum - points)
            )

    # tests
    if not i.has_test_run or i.tests_counted == 0:
        add(
            "tests",
            0,
            "No practice test has finished yet.",
            (
                "Run the practice tests to see how it handles real questions.",
                f"{base}?section=training",
            ),
        )
    else:
        add(
            "tests",
            _scaled_half_up(i.tests_passed, MAX_POINTS["tests"], i.tests_counted),
            f"{i.tests_passed} of {i.tests_counted} practice tests passed.",
            ("Fix the practice tests that failed, then test again.", f"{base}?section=training"),
        )

    # knowledge
    stock = 0 if i.knowledge_items == 0 else 5 if i.knowledge_items < KNOWLEDGE_PLENTY else 10
    gaps = max(0, 10 - 2 * i.open_gaps)
    if stock < 10:
        knowledge_fix = ("Add your prices, services and answers to common questions.", "/knowledge")
    else:
        knowledge_fix = ("Answer the questions it could not.", f"{base}?section=training")
    add(
        "knowledge",
        _scaled_half_up(stock + gaps, MAX_POINTS["knowledge"], KNOWLEDGE_READING_MAX),
        f"{_plural(i.knowledge_items, 'thing', 'things')} added for your agents; "
        f"{_plural(i.open_gaps, 'open question', 'open questions')} to answer.",
        knowledge_fix,
    )

    # opening line
    fits = i.opening_room is None or i.opening_chars <= i.opening_room
    if i.opening_chars == 0:
        add(
            "opening",
            0,
            "No opening line yet.",
            ("Write the opening line callers hear first.", f"{base}?section=script"),
        )
    elif i.opening_chars > OPENING_LINE_MAX_CHARS or not fits:
        add(
            "opening",
            5,
            f"The opening line is {i.opening_chars} characters, too long to be spoken in full.",
            ("Shorten the opening line to a greeting and one question.", f"{base}?section=script"),
        )
    else:
        add("opening", 15, f"The opening line is {i.opening_chars} characters.", None)

    # live
    if not (i.published and i.live):
        # Readiness is whether it is ready to put live, so not being live yet costs nothing
        # (D-916); only a live agent's callers can hear an out-of-date version.
        add("live", MAX_POINTS["live"], "Not live yet.", None)
    elif i.draft_waiting or i.out_of_sync:
        add(
            "live",
            LIVE_POINTS_PUBLISHED,
            "Live, with changes callers do not hear yet.",
            ("Apply your saved changes to live calls.", f"{base}?section=script"),
        )
    else:
        add("live", MAX_POINTS["live"], "Live, and callers hear the latest version.", None)

    # missed questions
    add(
        "missed",
        10 - 2 * i.missed_7d,
        f"{_plural(i.missed_7d, 'question', 'questions')} it could not answer in the last 7 days.",
        ("Teach it the answers callers asked for.", f"{base}?section=training"),
    )

    order = {key: n for n, key in enumerate(COMPONENT_ORDER)}
    fixes.sort(key=lambda f: (-f.points, order[f.component]))
    return AgentReadinessOut(
        agent_id=i.agent_id,
        agent_name=i.agent_name,
        score=sum(c.points for c in components),
        components=components,
        fixes=fixes,
        computed_at=now,
    )


_AGENT_FACTS_SQL: Final = (
    "SELECT a.status = 'live' AS live, "
    "a.system_prompt_id IS DISTINCT FROM a.live_prompt_id AS draft_waiting, "
    "(SELECT count(*) FROM knowledge_gaps g WHERE g.agent_id = a.id AND g.status = 'open') "
    "  AS open_gaps, "
    "(SELECT count(*) FROM knowledge_gap_occurrences o WHERE o.agent_id = a.id "
    "  AND o.created_at >= :since) AS missed, "
    # The routing bridge is RLS-exempt, so the tenant is in the predicate rather than trusted
    # to the exemption (`compliance.service.truthful_answer_drift_blocker` reads it the same way).
    "EXISTS (SELECT 1 FROM engine_agent_routes r WHERE r.tenant_id = a.tenant_id "
    "  AND r.agent_id = a.id AND r.active AND r.drift_state = ANY(:out_of_sync)) AS out_of_sync "
    "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL"
)
_FACTS_SQL: Final = "SELECT count(*) FROM kb_facts WHERE removed_at IS NULL"


async def knowledge_items(session: AsyncSession) -> int:
    """Live sources whose words reach the agents, and facts on file. Account-wide: knowledge
    belongs to the client and every agent carries it (D-689). A PDF or a link counts only
    while its read words are sent (`kb.service.delivered_source_count`)."""
    from apps.api.kb.service import delivered_source_count

    facts = int((await session.execute(text(_FACTS_SQL))).scalar_one())
    return await delivered_source_count(session) + facts


async def gather(
    session: AsyncSession,
    agent: AgentOut,
    *,
    now: datetime,
    knowledge: int | None = None,
) -> ReadinessInputs:
    facts = (
        await session.execute(
            text(_AGENT_FACTS_SQL),
            {
                "aid": agent.id,
                "since": now - MISSED_WINDOW,
                "out_of_sync": sorted(DRIFT_STATES_OUT_OF_SYNC),
            },
        )
    ).one()
    runs = await test_conversations.recent_runs(session, agent.id)
    latest = runs[0] if runs else None
    owner = latest.score if latest is not None else None
    budget = agent.greeting_budget
    return ReadinessInputs(
        agent_id=agent.id,
        agent_name=agent.name,
        tests_passed=owner.passed if owner else 0,
        tests_counted=owner.counted if owner else 0,
        has_test_run=latest is not None,
        knowledge_items=await knowledge_items(session) if knowledge is None else knowledge,
        open_gaps=int(facts.open_gaps),
        opening_chars=len(agent.script_opening_line.strip()),
        opening_room=None if budget is None else budget.opening_room,
        published=agent.published,
        live=bool(facts.live),
        draft_waiting=bool(facts.draft_waiting),
        out_of_sync=bool(facts.out_of_sync),
        missed_7d=int(facts.missed),
    )


async def agent_readiness(
    session: AsyncSession, agent_id: UUID, *, now: datetime | None = None
) -> AgentReadinessOut:
    agent = await agent_by_id(session, agent_id)
    if agent is None:
        raise ProblemError.not_found("Agent")
    at = now or datetime.now(UTC)
    return score(await gather(session, agent, now=at), now=at)


async def account_readiness(
    session: AsyncSession, agents: list[AgentOut], *, now: datetime | None = None
) -> AccountReadinessOut:
    """Every agent given (the caller passes the working roster, archive excluded), the mean
    score and the biggest fixes across them."""
    at = now or datetime.now(UTC)
    knowledge = await knowledge_items(session)
    scored = [
        score(await gather(session, agent, now=at, knowledge=knowledge), now=at) for agent in agents
    ]
    every_fix = [fix for one in scored for fix in one.fixes]
    order = {key: n for n, key in enumerate(COMPONENT_ORDER)}
    every_fix.sort(key=lambda f: (-f.points, order[f.component], f.href))
    return AccountReadinessOut(
        score=_scaled_half_up(sum(s.score for s in scored), 1, len(scored)) if scored else None,
        agents=scored,
        top_fixes=every_fix[:MAX_ACCOUNT_FIXES],
        computed_at=at,
    )


__all__ = [
    "COMPONENT_ORDER",
    "MAX_ACCOUNT_FIXES",
    "MAX_POINTS",
    "AccountReadinessOut",
    "AgentReadinessOut",
    "ReadinessComponentOut",
    "ReadinessFixOut",
    "ReadinessInputs",
    "account_readiness",
    "agent_readiness",
    "gather",
    "score",
]
