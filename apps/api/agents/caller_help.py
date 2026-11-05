"""Does this agent's caller follow along on their own phone? Judged per agent (founder, 5 Nov 2026).

Two settings exist for that caller: the screen guide (D-906, `caller_has_screen`), which lets
the agent name what is on the caller's screen and give one step at a time, and "Give callers
time" (D-907, `agents/patient_caller`), which stops the agent hanging up on a caller who has
gone quiet to do what it asked. Whether an agent needs them depends on what THAT agent does:
Rytu Khata's agent that walks farmers through installing an app needs both; the same
account's receptionist needs neither. So the judgement reads the agent, not the business:

* its latest saved script (who it is, what it is for, its steps and small steps, its FAQs);
* the purpose and goal of its campaigns;
* the business's own analysis (`business_copy.screen_guide`), as one more input, never the
  decider: a business whose customers use its app can still have an agent that only books.

A pass (`workers/caller_help`) writes `{screen_guide, give_time}` onto the agent, each
`{suggested, reason}`, the reason one sentence drawn from the script. It rides the D-889 pass
queue (`agents/agent_pass`): queued on a script save, the first publish, a campaign's brief
being written, and the first time anyone reads it; a pass whose inputs hash as before spends
nothing. Nothing is switched on by the pass; the owner turns it on from the Overview or the
Settings rows. "Not now" on the Overview is kept per item on the row, so it is not asked
again there; the Settings rows still say it is suggested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass
from apps.api.agents.agent_pass import dead_sql
from apps.api.agents.models import CALLER_HELP_ITEMS
from apps.api.core.errors import ProblemError

#: The ARQ name of the pass (`workers/caller_help`).
JOB: Final = "judge_caller_help"
SLOT: Final = agent_pass.PassSlot("caller_help", JOB)
REASON_MAX: Final = 160

Item = Literal["screen_guide", "give_time"]
PassState = Literal["none", "queued", "running", "done", "failed", "skipped"]


class Judgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested: bool
    #: Why, to the owner, in plain English, from what the agent does; empty when not suggested.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=REASON_MAX)] = ""


class CallerHelp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_guide: Judgement
    give_time: Judgement


NOT_SUGGESTED: Final = Judgement(suggested=False)


def parse_stored(raw: Any) -> CallerHelp | None:
    """The column as a model; None for a missing or malformed one, which reads as "no
    judgement yet" rather than failing the agent's page."""
    if not isinstance(raw, dict):
        return None
    try:
        return CallerHelp.model_validate(raw)
    except ValidationError:
        return None


@dataclass(frozen=True, slots=True)
class ItemState:
    suggested: bool
    reason: str
    #: The setting is in force on the agent now.
    on: bool
    #: The owner answered "Not now" on the Overview.
    dismissed: bool

    @property
    def ask(self) -> bool:
        """Is this one for the Overview to ask about?"""
        return self.suggested and not self.on and not self.dismissed


@dataclass(frozen=True, slots=True)
class CallerHelpState:
    state: PassState
    screen_guide: ItemState
    give_time: ItemState
    checked_at: datetime | None


_SELECT: Final = (
    "SELECT caller_help, caller_help_state, caller_help_at, caller_help_dismissed, "
    f"caller_has_screen, {dead_sql(SLOT)} FROM agents WHERE id = :aid AND deleted_at IS NULL"
)


async def _give_time_on(session: AsyncSession, agent_id: UUID) -> bool:
    # Imported here: `patient_caller` reaches `agents/service`, which reaches the script
    # builder that imports this module to queue a pass.
    from apps.api.agents import call_handling, patient_caller

    state = await call_handling.read_agent_call_handling(session, agent_id)
    return (await patient_caller.read_patient_caller(session, state)).applied


async def read_state(session: AsyncSession, *, agent_id: UUID) -> CallerHelpState:
    """The judgement and where each setting stands. 404 for an agent this session cannot see."""
    row = (await session.execute(text(_SELECT), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    judged = parse_stored(row[0])
    dismissed = {str(d) for d in row[3] or []}
    state: PassState = "failed" if row[5] else (row[1] or "none")

    def item(name: Item, on: bool) -> ItemState:
        verdict = getattr(judged, name) if judged is not None else NOT_SUGGESTED
        return ItemState(
            suggested=verdict.suggested,
            reason=verdict.reason if verdict.suggested else "",
            on=on,
            dismissed=name in dismissed,
        )

    return CallerHelpState(
        state=state,
        screen_guide=item("screen_guide", bool(row[4])),
        give_time=item("give_time", await _give_time_on(session, agent_id)),
        checked_at=row[2] if state in ("done", "failed", "skipped") else None,
    )


async def dismiss(session: AsyncSession, *, agent_id: UUID) -> list[Item]:
    """ "Not now": every item the Overview is asking about is not asked about again. Answers
    the items newly dismissed; none when nothing was being asked."""
    current = await read_state(session, agent_id=agent_id)
    asked: list[Item] = [
        name for name in ("screen_guide", "give_time") if getattr(current, name).ask
    ]
    if asked:
        # Merged in SQL so two answers racing each keep theirs; the CHECK bounds the array.
        await session.execute(
            text(
                "UPDATE agents SET caller_help_dismissed = ("
                "  SELECT COALESCE(jsonb_agg(DISTINCT v ORDER BY v), '[]'::jsonb) FROM ("
                "    SELECT jsonb_array_elements_text(caller_help_dismissed) AS v "
                "    UNION SELECT jsonb_array_elements_text(CAST(:add AS jsonb))) AS t "
                "  WHERE v = ANY(:known)), updated_at = now() WHERE id = :aid"
            ),
            {"aid": agent_id, "add": json.dumps(asked), "known": list(CALLER_HELP_ITEMS)},
        )
    return asked


async def queue_pass(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, force: bool = False
) -> bool:
    """Ask for a judgement of this agent, in the caller's transaction (`agent_pass.queue`)."""
    return await agent_pass.queue(
        session, SLOT, tenant_id=tenant_id, agent_id=agent_id, force=force
    )


async def queue_first_pass(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    """The agent's first judgement, once: for an agent whose script was saved before this
    existed, read on its Overview or published."""
    return await agent_pass.queue_first(session, SLOT, tenant_id=tenant_id, agent_id=agent_id)


__all__ = [
    "JOB",
    "NOT_SUGGESTED",
    "REASON_MAX",
    "SLOT",
    "CallerHelp",
    "CallerHelpState",
    "Item",
    "ItemState",
    "Judgement",
    "dismiss",
    "parse_stored",
    "queue_first_pass",
    "queue_pass",
    "read_state",
]
