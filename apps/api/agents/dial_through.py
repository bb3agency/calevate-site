"""Which engine agent a direct call rings through (D-1019).

An agent is an employee: a name, a voice, languages, actions and settings. Only its
ASSIGNMENTS hold an engine agent in the client's workspace: a live inbound line, and a
running or paused campaign. A direct call (a call-back, Call again, Make a call, a new lead's
call, a follow-up's call) is therefore placed through one of them, chosen in this order:

a. the campaign that produced the person, while it holds its own engine agent;
b. the live inbound line the earlier call came in on;
c. a live inbound line in the same agent's voice;
d. the agent's own engine agent, while it still has one (agents published before D-1019);
e. nothing: the call is refused `NO_ASSIGNMENT_RULE` (D1), in words naming the fix.

Why the holder and not a per-call override of the agent: a per-call override holds 4,000
characters and replaces the built-in call rules, while an engine agent's instructions hold
20,000 (`campaigns/engine_agent.py` cites the vendor pages). The holder speaks in the agent's
voice either way, so the person hears the same employee.

Every read here runs on the caller's tenant session, so RLS leaves another account's
campaigns, lines and calls invisible; each holder must also be the same agent's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import PUBLISHED_STATUSES, number_on_hold_sql
from apps.api.agents.service import (
    CAMPAIGN_HOLDING_STATUSES,
    INBOUND_SILENCE_TRUTHFUL_ANSWER,
    CampaignDial,
    LineDial,
)
from apps.api.compliance.service import NO_ASSIGNMENT_REASON, NO_ASSIGNMENT_RULE
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: What the client does about `NO_ASSIGNMENT_RULE`, as a remediation line.
NO_ASSIGNMENT_REMEDIATION: Final = "Start a campaign or put an inbound line live for this agent."


#: `PUBLISHED_STATUSES` as SQL, typed out so only our own text reaches the string
#: (`scripts/check_raw_sql`); the assertion keeps the two spellings one fact.
_READY_SQL: Final = "('live', 'paused')"
if "(" + ", ".join(f"'{s}'" for s in PUBLISHED_STATUSES) + ")" != _READY_SQL:
    raise RuntimeError("_READY_SQL no longer spells PUBLISHED_STATUSES")


def live_line_sql(alias: str) -> str:
    """SQL true while the `inbound_lines` row aliased `alias` is live: published, holding its
    engine agent, not archived. A draft's test holder has a ref and no `published_at`."""
    return (
        f"{alias}.archived_at IS NULL AND {alias}.published_at IS NOT NULL "
        f"AND {alias}.engine_agent_ref IS NOT NULL AND {alias}.engine_agent_ref <> ''"
    )


def holder_resolves_sql(agent: str) -> str:
    """SQL true while a direct call of the `agents` row aliased `agent` has something to ring
    through when no campaign holds the person: its own engine agent (step d), or, while it is
    ready, a live line in its voice (step c). The question speed-to-lead and follow-ups ask
    before they choose an agent."""
    return (
        f"(({agent}.engine_agent_ref IS NOT NULL AND {agent}.engine_agent_ref <> '') "
        f"OR ({agent}.status IN {_READY_SQL} AND EXISTS (SELECT 1 FROM inbound_lines dl "
        f"WHERE dl.agent_id = {agent}.id AND {live_line_sql('dl')})))"
    )


#: The call a direct call follows: the one named, else the person's latest call that came
#: through a campaign or a line.
_ORIGIN_CALL_SQL: Final = (
    "SELECT campaign_id, inbound_line_id FROM calls WHERE id = :cid AND agent_id = :aid"
)
_LEAD_ORIGIN_SQL: Final = (
    "SELECT campaign_id, inbound_line_id FROM calls WHERE lead_id = :lid AND agent_id = :aid "
    "AND (campaign_id IS NOT NULL OR inbound_line_id IS NOT NULL) "
    "ORDER BY created_at DESC, id DESC LIMIT 1"
)
_CAMPAIGN_HOLDER_SQL: Final = (
    "SELECT engine_agent_ref, number_id FROM campaigns WHERE id = :cid AND agent_id = :aid "
    "AND archived_at IS NULL AND status = ANY(:holding) "
    "AND engine_agent_ref IS NOT NULL AND engine_agent_ref <> ''"
)
_LINE_SQL: Final = (
    "SELECT l.id, l.engine_agent_ref FROM inbound_lines l WHERE l.agent_id = :aid "
    f"AND {live_line_sql('l')} AND (CAST(:lid AS uuid) IS NULL OR l.id = :lid) "
    "ORDER BY l.published_at, l.created_at, l.id LIMIT 1"
)
#: The line's numbers its engine agent answers right now (`inbound/publish`'s rule): not
#: while its voice is off, deleted or silenced, nor a number on hold. A call from one of them
#: needs no lend.
_ROUTED_SQL: Final = (
    "SELECT n.id FROM phone_numbers n JOIN inbound_lines l ON l.id = n.inbound_line_id "
    "JOIN agents a ON a.id = l.agent_id WHERE l.id = :lid AND n.released_at IS NULL "
    "AND a.status = 'live' AND a.deleted_at IS NULL "
    "AND a.inbound_silence_reason IS DISTINCT FROM :truthful "
    f"AND NOT {number_on_hold_sql('n')}"
)


@dataclass(frozen=True, slots=True)
class DialThrough:
    """What `dial_through` found: the holder to ring, or none. `own` is step d (the agent's
    own engine agent, as before D-1019); neither holder nor `own` is step e."""

    holder: CampaignDial | LineDial | None = None
    own: bool = False

    @property
    def campaign(self) -> CampaignDial | None:
        return self.holder if isinstance(self.holder, CampaignDial) else None

    @property
    def campaign_id(self) -> UUID | None:
        return self.holder.campaign_id if isinstance(self.holder, CampaignDial) else None

    @property
    def number_id(self) -> UUID | None:
        """The number a campaign holder calls from, for the gate and the dial alike."""
        return self.holder.number_id if isinstance(self.holder, CampaignDial) else None

    @property
    def line(self) -> LineDial | None:
        return self.holder if isinstance(self.holder, LineDial) else None

    @property
    def unassigned(self) -> bool:
        return self.holder is None and not self.own


async def campaign_holder(
    session: AsyncSession, *, agent_id: UUID, campaign_id: UUID
) -> CampaignDial | None:
    """The campaign's own engine agent while it holds one, with the number it calls from;
    None otherwise. Reads only: it never makes the engine agent (`campaigns.engine_agent`
    `.dial_for` does)."""
    row = (
        await session.execute(
            text(_CAMPAIGN_HOLDER_SQL),
            {"cid": campaign_id, "aid": agent_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).first()
    if row is None:
        return None
    return CampaignDial(
        ref=str(row[0]),
        campaign_id=campaign_id,
        number_id=UUID(str(row[1])) if row[1] is not None else None,
    )


async def _line_dial(
    session: AsyncSession, *, agent_id: UUID, line_id: UUID | None
) -> LineDial | None:
    row = (await session.execute(text(_LINE_SQL), {"aid": agent_id, "lid": line_id})).first()
    if row is None:
        return None
    found = UUID(str(row[0]))
    routed = await session.execute(
        text(_ROUTED_SQL), {"lid": found, "truthful": INBOUND_SILENCE_TRUTHFUL_ANSWER}
    )
    return LineDial(
        ref=str(row[1]),
        line_id=found,
        routed_number_ids=frozenset(UUID(str(number)) for number in routed.scalars()),
    )


async def dial_through(
    session: AsyncSession,
    *,
    agent_id: UUID,
    lead_id: UUID | None = None,
    origin_call_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> DialThrough:
    """The holder a direct call of `agent_id` rings through, steps a to e of the module.

    `campaign_id` is the campaign the caller already knows produced the person (a call-back
    it promised); otherwise it, and the line, are read from `origin_call_id`, else from the
    person's latest call that came through one."""
    origin_line: UUID | None = None
    origin: Row[Any] | None = None
    if origin_call_id is not None:
        origin = (
            await session.execute(text(_ORIGIN_CALL_SQL), {"cid": origin_call_id, "aid": agent_id})
        ).first()
    if origin is None and lead_id is not None:
        origin = (
            await session.execute(text(_LEAD_ORIGIN_SQL), {"lid": lead_id, "aid": agent_id})
        ).first()
    if origin is not None:
        campaign_id = campaign_id or (UUID(str(origin[0])) if origin[0] else None)
        origin_line = UUID(str(origin[1])) if origin[1] else None

    if campaign_id is not None:
        campaign = await campaign_holder(session, agent_id=agent_id, campaign_id=campaign_id)
        if campaign is not None:
            return DialThrough(holder=campaign)
    if origin_line is not None:
        line = await _line_dial(session, agent_id=agent_id, line_id=origin_line)
        if line is not None:
            return DialThrough(holder=line)
    line = await _line_dial(session, agent_id=agent_id, line_id=None)
    if line is not None:
        return DialThrough(holder=line)
    own = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar_one_or_none()
    if own:
        return DialThrough(own=True)
    log.info("dial_has_no_assignment", extra={"agent_id": str(agent_id)})
    return DialThrough()


def no_assignment_error() -> ProblemError:
    """Step e as an error, for a path that raises rather than renders a decision."""
    return ProblemError.business_rule(
        NO_ASSIGNMENT_RULE, NO_ASSIGNMENT_REASON, remediation=NO_ASSIGNMENT_REMEDIATION
    )


async def resolve_dial_holder(
    session: AsyncSession,
    *,
    agent_id: UUID,
    lead_id: UUID | None = None,
    origin_call_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> CampaignDial | LineDial | None:
    """`dial_through` as the holder to ring: a campaign's or a line's engine agent, or None
    for the agent's own. Raises `NO_ASSIGNMENT_RULE` when there is nothing to ring through."""
    found = await dial_through(
        session,
        agent_id=agent_id,
        lead_id=lead_id,
        origin_call_id=origin_call_id,
        campaign_id=campaign_id,
    )
    if found.unassigned:
        raise no_assignment_error()
    return found.holder


__all__ = [
    "NO_ASSIGNMENT_REMEDIATION",
    "DialThrough",
    "campaign_holder",
    "dial_through",
    "holder_resolves_sql",
    "live_line_sql",
    "no_assignment_error",
    "resolve_dial_holder",
]
