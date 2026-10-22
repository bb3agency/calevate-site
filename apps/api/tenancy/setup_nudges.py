"""When the setup checklist belongs on the dashboard (founder, 22 Oct 2026).

On the account's first day it shows whatever is left. After that it comes back only when
recent calls show that a missing step cost something, and each step it comes back for says
why. Nagging every day about a skipped step the calls do not miss is what this replaces.

Evidence is read from the calls themselves:
- a knowledge gap (`insights/detection`) whose topic a setup step answers: the agent was
  asked about opening hours, the address, prices and so on, and could not answer;
- a call that ended needing the owner (`calls.outcome_tag = 'needs_you'`) while nobody is
  set up to take calls.

Only evidence newer than the owner's "Hide this list" counts, so hiding it holds until a
new call gives a new reason. Runs in the tenant's own session (RLS).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: How long after the account is created the list shows with no evidence at all.
FIRST_DAY: Final = timedelta(hours=24)
#: How far back a call counts as a reason to show the list again.
EVIDENCE_WINDOW: Final = timedelta(days=14)

#: The setup step that answers each canonical gap topic (`insights.detection._TOPICS`). A
#: topic not named here was a question the business never answered: "Common questions".
GAP_TOPIC_STEP: Final[dict[str, str]] = {
    "timings": "hours",
    "location": "branches",
    "pricing": "services",
    "availability": "services",
    "offers": "services",
    "booking": "booking",
}
_FALLBACK_STEP: Final = "faqs"

#: What callers asked about, per step, in the owner's words.
_ASKED_ABOUT: Final[dict[str, str]] = {
    "hours": "your opening hours",
    "branches": "where you are",
    "services": "your prices or services",
    "booking": "booking",
}

_GAP_CALLS_SQL: Final = (
    "SELECT g.topic_key, count(DISTINCT o.call_id) "
    "FROM knowledge_gap_occurrences o "
    "JOIN knowledge_gaps g ON g.tenant_id = o.tenant_id AND g.agent_id = o.agent_id "
    "  AND g.topic_key = o.topic_key "
    "WHERE o.tenant_id = :tid AND g.status = 'open' AND o.created_at > :since "
    "GROUP BY g.topic_key"
)
_NEEDS_YOU_SQL: Final = (
    "SELECT count(*) FROM calls WHERE tenant_id = :tid AND outcome_tag = 'needs_you' "
    "AND COALESCE(ended_at, created_at) > :since"
)


@dataclass(frozen=True, slots=True)
class Nudge:
    step: str
    message: str


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _gap_message(step: str, calls: int) -> str:
    who = _plural(calls, "caller", "callers")
    if step in _ASKED_ABOUT:
        return (
            f"{who} asked about {_ASKED_ABOUT[step]} in the last 14 days and your agent "
            "could not answer."
        )
    return f"{who} asked questions in the last 14 days that your agent could not answer."


async def setup_nudges(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    open_steps: set[str],
    dismissed_at: datetime | None,
    now: datetime | None = None,
) -> list[Nudge]:
    """The steps recent calls show are missing, among `open_steps` (not done), each with
    the reason in the owner's words."""
    if not open_steps:
        return []
    now = now or datetime.now(UTC)
    since = now - EVIDENCE_WINDOW
    if dismissed_at is not None and dismissed_at > since:
        since = dismissed_at
    params = {"tid": tenant_id, "since": since}
    by_step: dict[str, int] = {}
    for topic, calls in (await session.execute(text(_GAP_CALLS_SQL), params)).all():
        step = GAP_TOPIC_STEP.get(str(topic), _FALLBACK_STEP)
        by_step[step] = by_step.get(step, 0) + int(calls)
    nudges = [
        Nudge(step=step, message=_gap_message(step, calls))
        for step, calls in by_step.items()
        if step in open_steps
    ]
    if "contacts" in open_steps:
        needed = int((await session.execute(text(_NEEDS_YOU_SQL), params)).scalar_one())
        if needed:
            nudges.append(
                Nudge(
                    step="contacts",
                    message=(
                        f"{_plural(needed, 'call', 'calls')} in the last 14 days needed a "
                        "person, and nobody is set up to take calls."
                    ),
                )
            )
    return nudges


def on_dashboard(
    *,
    finished: bool,
    created_at: datetime,
    dismissed: bool,
    nudges: list[Nudge],
    now: datetime | None = None,
) -> bool:
    """The first day: whatever is left, unless hidden. After it: only with a reason."""
    if finished:
        return False
    if (now or datetime.now(UTC)) - created_at < FIRST_DAY:
        return not dismissed
    return bool(nudges)


__all__ = [
    "EVIDENCE_WINDOW",
    "FIRST_DAY",
    "GAP_TOPIC_STEP",
    "Nudge",
    "on_dashboard",
    "setup_nudges",
]
