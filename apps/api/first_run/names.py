"""The name a new agent gives on its calls (D-855).

The name itself is the admin's default agent (`agents/default_agent.read_default_agent`;
"Anjali" until the console sets another). The name on the screen and the name the agent gives
on the call are the same one (Outpero's screen said "Gayatri" while its agent called itself
"Sanjana"), so the script's identity section opens with it. The owner can rename it before the
first call.
"""

from __future__ import annotations

import re
from typing import Final

_NAME_LINE: Final = re.compile(r"^Your name is [^.\n]{1,80}\.\s*")


def identity_with_name(identity: str, name: str) -> str:
    """The script's identity section opening with the agent's name, so the name the owner sees
    is the one it gives when it introduces itself or is asked. A name line an earlier build or
    rename wrote is replaced, never stacked."""
    rest = _NAME_LINE.sub("", identity.strip(), count=1)
    # `CallScript.identity` holds 1000 characters.
    return f"Your name is {name.strip()}. {rest}".strip()[:1000]


__all__ = ["identity_with_name"]
