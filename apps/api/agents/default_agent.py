"""The default agent: the name and voice a new account's first agent starts with.

It is the free-trial agent and the starter agent on paid tiers (founder, 16 Nov 2026). Today
it is the first run's own starter, "Anjali" (`first_run/names.FIRST_AGENT_NAME`), with no voice
fixed: the voice is the woman's Studio voice `agents/voice_pick.pick_voice` finds for the
agent's language. The admin console is to make both settable; this module is the one reader,
so that change lands here and every caller follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.first_run.names import FIRST_AGENT_NAME

#: The voice's gender the default name suits; `voice_pick` prefers a woman's voice for it.
DEFAULT_AGENT_GENDER: Final = "female"


@dataclass(frozen=True, slots=True)
class DefaultAgent:
    name: str
    #: A catalogue voice id, or None to pick one for the agent's language at creation.
    voice_id: str | None
    gender: str


async def read_default_agent(session: AsyncSession) -> DefaultAgent:
    """The default agent as the platform holds it today."""
    del session
    return DefaultAgent(name=FIRST_AGENT_NAME, voice_id=None, gender=DEFAULT_AGENT_GENDER)


__all__ = ["DEFAULT_AGENT_GENDER", "DefaultAgent", "read_default_agent"]
