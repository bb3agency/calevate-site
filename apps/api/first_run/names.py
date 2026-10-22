"""The name "Meet your agent" suggests for a new agent (D-855).

The founder's rule (23 Oct 2026): the name suits the voice it was given and the language it
speaks, so the name on the screen and the name the agent gives on the call are the same one
(Outpero's screen said "Gayatri" while its agent called itself "Sanjana"). The owner can rename
it before the first call.

Common given names, easy to say in all three languages, and never a real person of ours. A
voice whose gender the provider does not state gets a name used for either.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Literal

Gender = Literal["female", "male"]

_NAMES: Final[Mapping[tuple[str, Gender | None], str]] = {
    ("te-IN", "female"): "Sravani",
    ("te-IN", "male"): "Karthik",
    ("te-IN", None): "Kiran",
    ("hi-IN", "female"): "Priya",
    ("hi-IN", "male"): "Arjun",
    ("hi-IN", None): "Kiran",
    ("en-IN", "female"): "Ananya",
    ("en-IN", "male"): "Rohan",
    ("en-IN", None): "Kiran",
}
#: For a language this table has no row for yet: a name used for either, in every one.
FALLBACK_NAME: Final = "Kiran"


def gender_of(stated: str | None) -> Gender | None:
    """The provider's free-text gender as one of ours, or None when it does not say."""
    word = (stated or "").strip().casefold()
    if word.startswith(("f", "w")):
        return "female"
    if word.startswith("m"):
        return "male"
    return None


def suggested_name(language: str, gender: Gender | None) -> str:
    return _NAMES.get((language, gender)) or _NAMES.get((language, None)) or FALLBACK_NAME


_NAME_LINE: Final = re.compile(r"^Your name is [^.\n]{1,80}\.\s*")


def identity_with_name(identity: str, name: str) -> str:
    """The script's identity section opening with the agent's name, so the name the owner sees
    is the one it gives when it introduces itself or is asked. A name line an earlier build or
    rename wrote is replaced, never stacked."""
    rest = _NAME_LINE.sub("", identity.strip(), count=1)
    # `CallScript.identity` holds 1000 characters.
    return f"Your name is {name.strip()}. {rest}".strip()[:1000]


__all__ = ["FALLBACK_NAME", "Gender", "gender_of", "identity_with_name", "suggested_name"]
