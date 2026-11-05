"""Words that are Pip's machinery, not an owner's world (founder, 6 Nov 2026).

Asked to print an agent's script, Pip told an owner "the system does not provide a tool to
print the entire multi-stage script". The prompt forbids that register
(`prompt.PLAIN_WORDS_RULE`); this list is how a sentence is checked against it, by
`owner_words_test.py` over the sentences we write for owners and by the live eval
(`scripts/copilot_tool_eval.py --live`) over the answers the model writes.

Plain words with a next step rather than jargon is NN/g's error-message guidance
(https://www.nngroup.com/articles/error-message-guidelines/).
"""

from __future__ import annotations

import re
from typing import Final

#: `(what leaked, pattern)`. Each is a class of leak, not a word list for its own sake.
MACHINE_WORDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("a tool", re.compile(r"\btools?\b", re.I)),
    ("the system", re.compile(r"\bthe system\b", re.I)),
    ("a function", re.compile(r"\bfunctions?\b", re.I)),
    ("our stack", re.compile(r"\bAPI\b(?! key)|\bJSON\b|\bendpoints?\b|\bpayloads?\b")),
    ("a schema", re.compile(r"\bschemas?\b", re.I)),
    ("an argument", re.compile(r"\barguments?\b|\bparams?\b|\bnull\b", re.I)),
    # Lower case only: "their ID" is an identity document, an owner's word.
    ("an id", re.compile(r"\bids?\b|\buuids?\b")),
    ("a code name", re.compile(r"`|\b[a-z]+_[a-z0-9_]+\b")),
    ("the model", re.compile(r"\bthe model\b|\bLLM\b|\bprompt\b", re.I)),
    # Not Google: Google Calendar and Sheets are connections the owner makes themselves.
    (
        "a provider",
        re.compile(r"\b(?:gemini|sarvam|azure|openai|thinnest(?:ai)?|cartesia)\b", re.I),
    ),
)


def machine_words(text: str) -> list[str]:
    """Each class of machinery `text` names, with the word that showed it. `{}` (an
    f-string's hole, as the source scanner reads one) is never a word."""
    body = text.replace("{}", " ")
    return [f"{name}: {m.group(0)!r}" for name, rule in MACHINE_WORDS if (m := rule.search(body))]


__all__ = ["MACHINE_WORDS", "machine_words"]
