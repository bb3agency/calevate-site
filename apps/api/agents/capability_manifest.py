"""What an agent can actually do on a call, and the facts its owner gave, read from the account
(D-945) for the script writer, the script lint and the calendar reminder.

One reader for all three, so the writer is never told an agent can book while the readiness
card says it cannot.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import service as action_service
from apps.api.agents import hot_facts, script_builder
from apps.api.agents.script_lint import CapabilityManifest, LintContext
from apps.api.agents.starters import TRADES
from apps.api.core.errors import ProblemError
from apps.api.teach import pinned as pinned_store
from apps.api.team_alerts import service as team_alerts
from apps.api.tenancy.business_profile import profile_fact_lines

#: Lead sources the writer is told about, most first.
MAX_LEAD_SOURCES: Final = 5
#: The writer's facts, cut whole items at this many characters: enough for the value step's
#: choice, small enough to leave the draft's token budget to the script.
MAX_FACT_CHARS: Final = 3_000


async def manifest_for(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> CapabilityManifest:
    """This agent's capability manifest, from its live in-call actions, the account's call
    backs, its hand-over switch, its team alerts and its leads' sources."""
    tools = await action_service.in_call_tools(session, agent_id=agent_id)
    kinds = {tool.kind for tool in tools}
    hand_over = (
        await session.execute(
            text("SELECT handoff_enabled FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar()
    sources = (
        await session.execute(
            text(
                "SELECT source FROM leads WHERE agent_id = :aid AND source IS NOT NULL "
                "GROUP BY source ORDER BY count(*) DESC, source LIMIT :n"
            ),
            {"aid": agent_id, "n": MAX_LEAD_SOURCES},
        )
    ).scalars()
    return CapabilityManifest(
        booking_tool="calendar" in kinds,
        whatsapp="whatsapp" in kinds,
        call_backs=await script_builder.call_backs_available(session, tenant_id),
        hand_over=bool(hand_over),
        team_alerts=agent_id in await team_alerts.agents_with_rules(session),
        lead_sources=tuple(str(s) for s in sources),
    )


async def owner_facts(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> tuple[str, ...]:
    """The facts the owner gave, one line each: the business profile, the pinned facts and the
    agent's known facts (D-896), in that order, duplicates dropped, cut whole at
    `MAX_FACT_CHARS`."""
    lines = [
        *await profile_fact_lines(session, tenant_id=tenant_id),
        *(
            f"{fact.question} {fact.answer}".strip()
            for fact in await pinned_store.list_pinned(session)
        ),
        *await hot_facts.load_texts(session, agent_id=agent_id),
    ]
    out: list[str] = []
    used = 0
    for line in dict.fromkeys(" ".join(item.split()) for item in lines):
        if not line:
            continue
        if used + len(line) > MAX_FACT_CHARS:
            break
        out.append(line)
        used += len(line)
    return tuple(out)


async def lint_context_for(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> LintContext:
    """What this agent's script is checked against (`script_lint.script_problems`)."""
    row = (
        await session.execute(
            text(
                "SELECT a.language_primary, a.name, o.name FROM agents a "
                "JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return LintContext(
        language=str(row[0]),
        manifest=await manifest_for(session, tenant_id=tenant_id, agent_id=agent_id),
        facts=" ".join(await owner_facts(session, tenant_id=tenant_id, agent_id=agent_id)),
        agent_name=str(row[1] or ""),
        business_name=str(row[2] or ""),
    )


#: Words of a step that books something: the generic ones and each trade's own booking noun
#: (`starters.TRADES`), so a new trade's word is read from its table. An order is not a
#: time with the business, so a shop is never reminded.
_BOOKS: Final = re.compile(
    r"\b(?:"
    + "|".join(
        re.escape(word)
        for word in sorted(
            {"book", "booking", "visit", "slot"}
            | {t.booking.split(" ", 1)[-1] for t in TRADES.values() if "order" not in t.booking},
            key=len,
            reverse=True,
        )
    )
    + r")\b",
    re.IGNORECASE,
)


def books_visits(direction: str, script: CallScript) -> bool:
    """Whether a calendar would change this agent's calls (D-945, founder, 30 Oct 2026): it
    places calls, it may take bookings, and a step of its plan books a time with the
    business. An agent that only answers calls is never nudged, whatever it books."""
    if direction not in ("outbound", "both") or not script.policies.take_bookings:
        return False
    # Step names only: every calling plan's offer instruction mentions a booking tool.
    return any(_BOOKS.search(stage.name) for stage in script.stages)


__all__ = [
    "MAX_FACT_CHARS",
    "MAX_LEAD_SOURCES",
    "books_visits",
    "lint_context_for",
    "manifest_for",
    "owner_facts",
]
