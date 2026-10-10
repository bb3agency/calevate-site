"""Where the agents struggled on real calls, found from the calls themselves.

Two sources, one list:

1. Open knowledge gaps (`insights/`): a caller asked something and the agent said it did not
   know, or pushed it to a call back or WhatsApp. Grouped by topic, with the latest call.
2. Calls that ended needing the owner (`calls.outcome_tag = 'needs_you'`, derived from facts
   by `crm/outcomes.py`: a hand-over that reached nobody, or a need the agent could not meet)
   on which no gap was found, so the owner still sees them.

Every quote is redacted text (hard rule 6): gap quotes come from redacted columns, and a
call contributes only its headline, which the call list already shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: How far back the "needed you" calls go. Older ones were followed up or are history.
NEEDS_YOU_DAYS: Final = 30
MAX_GAPS: Final = 50
MAX_CALLS: Final = 20

StruggleKind = Literal["didnt_know", "put_off", "unanswered", "needed_you"]

_GAP_KIND: Final[dict[str, StruggleKind]] = {
    "dont_know": "didnt_know",
    "deferred_channel": "put_off",
    "unanswered_question": "unanswered",
}


@dataclass(frozen=True, slots=True)
class Struggle:
    #: The gap's id, or the call's id for a "needed you" call.
    id: UUID
    kind: StruggleKind
    gap_id: UUID | None
    agent_id: UUID
    agent_name: str | None
    topic: str
    #: What the caller asked (redacted), when known.
    question: str | None
    #: What the agent said (redacted), when known.
    answer: str | None
    times: int
    calls: int
    last_call_id: UUID | None
    last_seen_at: datetime


async def list_struggles(session: AsyncSession, *, agent_id: UUID | None = None) -> list[Struggle]:
    agent_clause = "AND g.agent_id = :aid" if agent_id else ""
    params: dict[str, object] = {"limit": MAX_GAPS}
    if agent_id:
        params["aid"] = agent_id
    gap_rows = (
        await session.execute(
            text(
                "SELECT g.id, g.agent_id, a.name, g.topic_label, g.top_signal, "
                "  g.example_question_redacted, g.example_answer_redacted, "
                "  g.occurrence_count, g.call_count, g.last_seen_at, "
                "  (SELECT o.call_id FROM knowledge_gap_occurrences o "
                "   WHERE o.agent_id = g.agent_id AND o.topic_key = g.topic_key "
                "   ORDER BY o.created_at DESC LIMIT 1) AS last_call_id "
                "FROM knowledge_gaps g LEFT JOIN agents a ON a.id = g.agent_id "
                f"WHERE g.status = 'open' {agent_clause} "
                "ORDER BY g.occurrence_count DESC, g.last_seen_at DESC LIMIT :limit"
            ),
            params,
        )
    ).all()
    out = [
        Struggle(
            id=r[0],
            kind=_GAP_KIND.get(str(r[4]), "didnt_know"),
            gap_id=r[0],
            agent_id=r[1],
            agent_name=r[2],
            topic=r[3],
            question=r[5] or None,
            answer=r[6] or None,
            times=int(r[7]),
            calls=int(r[8]),
            last_call_id=r[10],
            last_seen_at=r[9],
        )
        for r in gap_rows
    ]
    call_clause = "AND c.agent_id = :aid" if agent_id else ""
    call_params: dict[str, object] = {"limit": MAX_CALLS, "days": NEEDS_YOU_DAYS}
    if agent_id:
        call_params["aid"] = agent_id
    call_rows = (
        await session.execute(
            text(
                "SELECT c.id, c.agent_id, a.name, c.headline, "
                "  COALESCE(c.ended_at, c.started_at, c.created_at) AS at "
                "FROM calls c LEFT JOIN agents a ON a.id = c.agent_id "
                "WHERE c.outcome_tag = 'needs_you' "
                "  AND COALESCE(c.started_at, c.created_at) > now() - make_interval(days => :days) "
                "  AND c.erased_subject_ref IS NULL "
                "  AND NOT EXISTS (SELECT 1 FROM knowledge_gap_occurrences o "
                "                  WHERE o.call_id = c.id) "
                f"  {call_clause} "
                "ORDER BY at DESC LIMIT :limit"
            ),
            call_params,
        )
    ).all()
    out.extend(
        Struggle(
            id=r[0],
            kind="needed_you",
            gap_id=None,
            agent_id=r[1],
            agent_name=r[2],
            topic=r[3] or "The call needed you",
            question=None,
            answer=None,
            times=1,
            calls=1,
            last_call_id=r[0],
            last_seen_at=r[4],
        )
        for r in call_rows
    )
    return out


__all__ = ["MAX_CALLS", "MAX_GAPS", "NEEDS_YOU_DAYS", "Struggle", "StruggleKind", "list_struggles"]
