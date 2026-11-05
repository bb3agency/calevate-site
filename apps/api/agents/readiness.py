"""The agent readiness score, 0-100, and what to fix to raise it (D-870, weights D-873).

The gauge on each agent and on the dashboard (founder decision f7d9f716, point 2). It is
computed on every read from what is already stored; nothing is written and nothing is
cached, so the number moves the moment knowledge is added or a change goes live.

THE FORMULA (four components, 100 points; `score()` is the whole of it and is pure):

| component  | max | points                                                                 |
|------------|-----|------------------------------------------------------------------------|
| knowledge  |  40 | D-870's 20-point reading scaled by 40/20, rounded half up. That        |
|            |     | reading is 10 for live knowledge (live sources + facts on file + the   |
|            |     | profile's offerings and common questions, D-968: 0 → 0, 1-4 → 5,       |
|            |     | 5+ → 10) plus max(0, 10 - 2 * this agent's open knowledge              |
|            |     | gaps); the sum is scaled once, so the rounding happens once           |
| opening    |  20 | 20 when the opening line is set, at most `OPENING_LINE_MAX_CHARS` and  |
|            |     | fits the greeting budget with the notices as they are; 7 when set but  |
|            |     | too long; 0 when empty                                                 |
| live       |  25 | 25 when not live (D-916); live: 13, and 12 more when no draft is       |
|            |     | waiting and the calling system's copy is not out of sync              |
|            |     | (`DRIFT_STATES_OUT_OF_SYNC`)                                           |
| missed     |  15 | max(0, 15 - 3 * questions it could not answer in the last 7 days)      |

Practice tests are not scored (founder, 4 Nov 2026): running them is optional, and a score
that asked for them added work before a client could start calling. Knowledge and missed
questions are the two halves of "does it know the business"; the opening line is what every
caller hears first; a live agent whose callers hear an out-of-date version is not ready, while
one not live yet is not marked down for it (D-916).

The opening notices (D-163) are not a component: whether an agent volunteers "I am an AI"
or "this call is recorded" is the owner's choice and does not make it more or less ready
(D-873). The truthful answers when a caller asks (hard rule 5) are on every agent whatever
the switches say, so there is nothing for the score to measure there either. A component
never goes below 0, so the total is 0-100.

Every component that is not full contributes one `fix` with a realm-relative link to the
screen where it is fixed. Fixes are ordered by the points they would recover, largest
first, and ties by the table order above, so the list is deterministic.

ADVICE IS NOT SCORED (D-945). `advice` carries what the owner should still do but no point
measures: a calendar for an agent that places calls and books visits (founder, 30 Oct 2026:
only where it matters, never for an agent that mostly answers calls), and what the script
lint finds in the draft (`agents/script_lint`). One short line and a button each.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from calevate_shared.call_script import upgrade_to_v2
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.calendar import calendar_configured
from apps.api.agents import script_builder
from apps.api.agents.call_rules import OPENING_LINE_MAX_CHARS
from apps.api.agents.capability_manifest import books_visits, lint_context_for
from apps.api.agents.reconciliation import DRIFT_STATES_OUT_OF_SYNC
from apps.api.agents.roster import agent_by_id
from apps.api.agents.schemas import AgentOut
from apps.api.agents.script_lint import plain, script_problems
from apps.api.core.errors import ProblemError

ComponentKey = Literal["knowledge", "opening", "live", "missed"]
ComponentState = Literal["full", "partial", "none"]

MAX_POINTS: Final[dict[ComponentKey, int]] = {
    "knowledge": 40,
    "opening": 20,
    "live": 25,
    "missed": 15,
}
#: An opening line that is set but too long to be spoken in full.
OPENING_TOO_LONG_POINTS: Final = 7
#: Points lost per question it could not answer in the last 7 days.
MISSED_POINTS_EACH: Final = 3
COMPONENT_ORDER: Final[tuple[ComponentKey, ...]] = tuple(MAX_POINTS)
COMPONENT_LABELS: Final[dict[ComponentKey, str]] = {
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
LIVE_POINTS_PUBLISHED: Final = 13


class ReadinessFixOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: ComponentKey
    #: One plain sentence naming the next step.
    action: str
    #: Realm-relative link to the screen where it is fixed ("/agents/{id}?section=script").
    href: str
    #: The points this fix would add, at most.
    points: int


AdviceKind = Literal["calendar", "script"]


class ReadinessAdviceOut(BaseModel):
    """Something to do that the score does not count (D-945)."""

    model_config = ConfigDict(extra="forbid")

    kind: AdviceKind
    #: The button's label: the step, in a few words.
    action: str
    #: Realm-relative link to the screen where it is done.
    href: str
    #: Why, in one sentence, shown behind a tap; null when the label says it all.
    detail: str | None = None


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
    #: What to do that the score does not count (D-945).
    advice: list[ReadinessAdviceOut] = Field(default_factory=list)


class AccountReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The mean of the agents' scores, rounded; None with no agents.
    score: int | None
    agents: list[AgentReadinessOut]
    #: The biggest fixes across every agent, at most `MAX_ACCOUNT_FIXES`.
    top_fixes: list[ReadinessFixOut]
    computed_at: datetime


MAX_ACCOUNT_FIXES: Final = 5


#: What a too-long opening line is cut down to, by who hears it first.
ANSWERED_OPENING_FIX: Final = "Shorten the opening line to a greeting and one question."
PLACED_OPENING_FIX: Final = (
    "Shorten the opening line to their name, who is calling and why, and asking if they can "
    "talk now."
)


@dataclass(frozen=True, slots=True)
class ReadinessInputs:
    """Everything the score reads, gathered by `gather()`; `score()` is pure over it."""

    agent_id: UUID
    agent_name: str
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
    #: Not scored (D-945): passed through to `AgentReadinessOut.advice`.
    advice: tuple[ReadinessAdviceOut, ...] = ()
    #: An outbound agent's opening line is said on calls it places, so its fix names what a
    #: placed call's opening holds (`call_rules.OPENING_LINE_RULE`).
    places_calls: bool = False


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

    # knowledge
    stock = 0 if i.knowledge_items == 0 else 5 if i.knowledge_items < KNOWLEDGE_PLENTY else 10
    gaps = max(0, 10 - 2 * i.open_gaps)
    if stock < 10:
        # The knowledge screen adds both, into the business profile (D-968). Named without
        # "service" or "price": each business has its own words for them (`profile_wording`).
        knowledge_fix = ("Add what you offer and what callers often ask.", "/knowledge")
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
            OPENING_TOO_LONG_POINTS,
            f"The opening line is {i.opening_chars} characters, too long to be spoken in full.",
            (
                PLACED_OPENING_FIX if i.places_calls else ANSWERED_OPENING_FIX,
                f"{base}?section=script",
            ),
        )
    else:
        add(
            "opening",
            MAX_POINTS["opening"],
            f"The opening line is {i.opening_chars} characters.",
            None,
        )

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
        MAX_POINTS["missed"] - MISSED_POINTS_EACH * i.missed_7d,
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
        advice=list(i.advice),
    )


#: Lint findings shown at most; the script page shows where each is.
MAX_SCRIPT_ADVICE: Final = 2


async def advice_for(session: AsyncSession, agent: AgentOut) -> tuple[ReadinessAdviceOut, ...]:
    """The calendar reminder and the script lint's findings for one agent (D-945)."""
    base = f"/agents/{agent.id}"
    tenant_id = (
        await session.execute(
            text("SELECT tenant_id FROM agents WHERE id = :aid"), {"aid": agent.id}
        )
    ).scalar_one()
    script = upgrade_to_v2((await script_builder.load_agent_script(session, agent.id)).script)
    context = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent.id)
    out: list[ReadinessAdviceOut] = []
    manifest = context.manifest
    if (
        manifest is not None
        and not manifest.booking_tool
        and calendar_configured()
        and books_visits(agent.direction, script)
    ):
        out.append(
            ReadinessAdviceOut(
                kind="calendar",
                action="Connect a calendar",
                href=f"{base}?section=actions",
                detail="Your agent then offers times you are really free.",
            )
        )
    out += [
        ReadinessAdviceOut(
            kind="script",
            action="Fix a line in the script",
            href=f"{base}?section=script",
            detail=plain(problem),
        )
        for problem in script_problems(script, context)[:MAX_SCRIPT_ADVICE]
    ]
    return tuple(out)


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
#: What the business offers and its common questions, from the business profile: their one
#: home (D-968). Under the caller's tenant session, so RLS scopes it to the account.
_PROFILE_ENTRIES_SQL: Final = (
    "SELECT coalesce(sum("
    "  CASE WHEN jsonb_typeof(services) = 'array' THEN jsonb_array_length(services) ELSE 0 END"
    "  + CASE WHEN jsonb_typeof(faqs) = 'array' THEN jsonb_array_length(faqs) ELSE 0 END"
    "), 0) FROM business_profiles"
)


async def knowledge_items(session: AsyncSession) -> int:
    """Live sources whose words reach the agents, facts on file, and each thing offered and
    common question in the business profile. Account-wide: knowledge belongs to the client
    and every agent carries it (D-689). A PDF or a link counts only while its read words are
    sent (`kb.service.delivered_source_count`)."""
    from apps.api.kb.service import delivered_source_count

    facts = int((await session.execute(text(_FACTS_SQL))).scalar_one())
    profile = int((await session.execute(text(_PROFILE_ENTRIES_SQL))).scalar_one())
    return await delivered_source_count(session) + facts + profile


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
    budget = agent.greeting_budget
    return ReadinessInputs(
        agent_id=agent.id,
        agent_name=agent.name,
        knowledge_items=await knowledge_items(session) if knowledge is None else knowledge,
        open_gaps=int(facts.open_gaps),
        opening_chars=len(agent.script_opening_line.strip()),
        opening_room=None if budget is None else budget.opening_room,
        published=agent.published,
        live=bool(facts.live),
        draft_waiting=bool(facts.draft_waiting),
        out_of_sync=bool(facts.out_of_sync),
        missed_7d=int(facts.missed),
        places_calls=agent.direction == "outbound",
        advice=await advice_for(session, agent),
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
    "ReadinessAdviceOut",
    "ReadinessComponentOut",
    "ReadinessFixOut",
    "ReadinessInputs",
    "account_readiness",
    "advice_for",
    "agent_readiness",
    "gather",
    "score",
]
