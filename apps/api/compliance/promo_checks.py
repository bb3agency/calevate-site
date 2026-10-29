"""Where the promo lint meets stored scripts: the agent screen, the campaign gate, Pip (D-943).

`call_purpose.py` is pure; this module loads what it reads. Two readings, on purpose:

* The AGENT check reads the script being EDITED — the autosaved draft when there is one,
  else the saved version — because it answers "if I put this live, is it promotional?"
  It WARNS and never blocks: an agent's script also answers inbound calls, which the
  caller started and which are not commercial communication we send, and an inbound-only
  agent places no calls at all.
* The CAMPAIGN check reads the LIVE script (`applied=True`), because that is what every
  call the campaign places will say. A service campaign whose live script is promotional
  is refused at launch (`SCRIPT_PROMOTIONAL_RULE`): the call would be promotional in law
  whatever the campaign was filed as, and Calevate does not place promotional calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.call_purpose import (
    PromoReport,
    PurposeVerdict,
    ScriptPart,
    campaign_purpose,
    lint,
    script_parts,
)
from apps.api.core.errors import ProblemError

#: The launch blocker's rule name, shared by the launch screen, the dispatch refusal list
#: and Pip so all three say the same thing.
SCRIPT_PROMOTIONAL_RULE: Final = "script_promotional"
SCRIPT_PROMOTIONAL_REASON: Final = (
    "The agent's script talks about offers or selling, which would make every call in this "
    "campaign a promotional call. Calevate places service calls only. Take the offer out of "
    "the script, or ask Pip to rewrite it as a service call."
)


@dataclass(frozen=True, slots=True)
class AgentPromoCheck:
    agent_id: UUID
    direction: str
    #: False for an agent that only answers calls: the lint still runs, the warning is moot.
    places_calls: bool
    #: Which script was read: the unpublished draft, or the saved version.
    reading: str
    report: PromoReport


async def _direction(session: AsyncSession, agent_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT direction FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return str(row[0])


async def agent_check(session: AsyncSession, agent_id: UUID) -> AgentPromoCheck:
    """The script being edited, read as a call this agent PLACES would say it."""
    from apps.api.agents import script_builder

    direction = await _direction(session, agent_id)
    draft = await script_builder.read_draft(session, agent_id)
    if draft is not None:
        script, reading = draft.script, "draft"
    else:
        script, reading = (
            (await script_builder.load_agent_script(session, agent_id)).script,
            "saved",
        )
    return AgentPromoCheck(
        agent_id=agent_id,
        direction=direction,
        places_calls=direction != "inbound",
        reading=reading,
        report=lint(script_parts(script, outbound=True)),
    )


async def live_script_report(session: AsyncSession, agent_id: UUID) -> PromoReport:
    """What every call this agent places now says, read as a placed call."""
    from apps.api.agents import script_builder

    loaded = await script_builder.load_agent_script(session, agent_id, applied=True)
    return lint(script_parts(loaded.script, outbound=True))


def wording_report(parts: list[ScriptPart]) -> PromoReport:
    return lint(parts)


@dataclass(frozen=True, slots=True)
class CampaignPurposeCheck:
    campaign_id: UUID
    agent_id: UUID
    purpose: PurposeVerdict
    report: PromoReport

    @property
    def blocks_launch(self) -> bool:
        return self.purpose.purpose != "promotional" and self.report.blocks_launch


async def campaign_check(session: AsyncSession, campaign_id: UUID) -> CampaignPurposeCheck:
    row = (
        await session.execute(
            text(
                "SELECT c.agent_id, c.classification, c.consent_source FROM campaigns c "
                "WHERE c.id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    agent_id = UUID(str(row[0]))
    return CampaignPurposeCheck(
        campaign_id=campaign_id,
        agent_id=agent_id,
        purpose=campaign_purpose(str(row[1]), row[2]),
        report=await live_script_report(session, agent_id),
    )


async def script_promotional_blocker(
    session: AsyncSession, *, agent_id: UUID, classification: str
) -> tuple[str, str] | None:
    """The launch refusal for a NON-promotional campaign whose live script is promotional.

    A campaign filed as promotional is not asked: it is already refused by the national
    preference scrub until one is recorded, and the lint would only repeat the obvious.
    """
    if classification == "promotional":
        return None
    report = await live_script_report(session, agent_id)
    if report.blocks_launch:
        return SCRIPT_PROMOTIONAL_RULE, SCRIPT_PROMOTIONAL_REASON
    return None


__all__ = [
    "SCRIPT_PROMOTIONAL_REASON",
    "SCRIPT_PROMOTIONAL_RULE",
    "AgentPromoCheck",
    "CampaignPurposeCheck",
    "agent_check",
    "campaign_check",
    "live_script_report",
    "script_promotional_blocker",
    "wording_report",
]
