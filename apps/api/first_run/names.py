"""The name "Meet your agent" gives a new agent (D-855).

Always "Anjali" (founder, 23 Oct 2026, replacing the per-language and per-gender list): one
name that is easy to say in Telugu, Hindi and English, so the voice the build picks is a
woman's (`agents/voice_pick.choose_voice`). The name on the screen and the name the agent gives
on the call are the same one (Outpero's screen said "Gayatri" while its agent called itself
"Sanjana"). The owner can rename it before the first call.
"""

from __future__ import annotations

import re
from typing import Final

FIRST_AGENT_NAME: Final = "Anjali"


_NAME_LINE: Final = re.compile(r"^Your name is [^.\n]{1,80}\.\s*")


def identity_with_name(identity: str, name: str) -> str:
    """The script's identity section opening with the agent's name, so the name the owner sees
    is the one it gives when it introduces itself or is asked. A name line an earlier build or
    rename wrote is replaced, never stacked."""
    rest = _NAME_LINE.sub("", identity.strip(), count=1)
    # `CallScript.identity` holds 1000 characters.
    return f"Your name is {name.strip()}. {rest}".strip()[:1000]


__all__ = ["FIRST_AGENT_NAME", "identity_with_name"]
