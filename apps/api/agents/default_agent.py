"""The agent a new account starts with, as the admin console sets it (founder, 16 Nov 2026).

It is the free trial's agent and the starter agent on the paid tiers: one name and one voice
for both, kept as two platform settings (`Settings.default_agent_name`,
`Settings.default_agent_voice_id`) so they carry the console's revision check and audit row.
Unset, they are what the product shipped with: "Anjali", and the best woman's voice for the
agent's language, Studio first (`agents/voice_pick`).

What the settings change is only what a NEW first agent gets. An agent already made keeps its
own name and voice, and nothing here republishes anything.

The voice is a preference, not a promise. Whether one account can be given it depends on that
account (Studio not open to it, its trial's Studio minutes used, a voice that does not speak
its language), so `voice_pick.pick_voice` takes this and falls back to the ranked choice. A
voice the admin later disables is not handed out: `read_default_agent` drops a voice that is no
longer on the client picker's list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import offered_hosted_voices
from apps.api.agents.voice_pick import gender_of
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

#: The gender a first agent's voice is chosen by when no voice is set, or the set voice's
#: provider states none: the shipped default agent is a woman named Anjali.
DEFAULT_GENDER: Final = "female"


@dataclass(frozen=True)
class DefaultAgent:
    name: str
    #: The admin's voice, while it is still offered to clients; None picks one per account.
    voice_id: str | None
    #: `female` or `male`: the set voice's own gender, else `DEFAULT_GENDER`. Picking a
    #: stand-in voice prefers this one, so the name and the voice the caller hears agree.
    gender: str


async def read_default_agent(session: AsyncSession) -> DefaultAgent:
    """The name, voice and gender a new account's first agent starts with.

    The voice catalogue is platform-scoped, so any session reads it."""
    settings = get_settings()
    name = settings.default_agent_name.strip()
    wanted = settings.default_agent_voice_id
    if not wanted:
        return DefaultAgent(name=name, voice_id=None, gender=DEFAULT_GENDER)
    row = next((r for r in await offered_hosted_voices(session) if r.voice_id == wanted), None)
    if row is None:
        return DefaultAgent(name=name, voice_id=None, gender=DEFAULT_GENDER)
    return DefaultAgent(
        name=name, voice_id=row.voice_id, gender=gender_of(row.gender) or DEFAULT_GENDER
    )


DEFAULT_VOICE_NOT_OFFERED: Final = "default_agent_voice_not_offered"
DEFAULT_NAME_BLANK: Final = "default_agent_name_blank"


async def assert_default_voice_offered(session: AsyncSession, voice_id: str | None) -> None:
    """Refuse a default voice clients could not be given: one that is not added, enabled and
    still listed. Unset is always allowed (the voice is picked per account)."""
    if voice_id is None:
        return
    if any(row.voice_id == voice_id for row in await offered_hosted_voices(session)):
        return
    raise ProblemError.business_rule(
        DEFAULT_VOICE_NOT_OFFERED,
        "That voice is not enabled for clients, so a new agent cannot be given it.",
        remediation="Enable it on the Voices page first, or choose one of the voices listed.",
    )


def assert_default_name_usable(name: str) -> None:
    """Refuse a name that is only spaces: the agent would introduce itself as nobody."""
    if not name.strip():
        raise ProblemError.business_rule(
            DEFAULT_NAME_BLANK,
            "The first agent needs a name.",
            remediation="Type the name new accounts' first agent should have.",
        )


__all__ = [
    "DEFAULT_GENDER",
    "DEFAULT_NAME_BLANK",
    "DEFAULT_VOICE_NOT_OFFERED",
    "DefaultAgent",
    "assert_default_name_usable",
    "assert_default_voice_offered",
    "read_default_agent",
]
