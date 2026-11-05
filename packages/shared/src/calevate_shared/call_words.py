"""The Indian-language words the call checks look for, read from `call_words.json`.

The founder's rule (5 Nov 2026): no Telugu, Hindi or other Indian-language word is written
in code. The checks that read a real call's transcript — the turn checks behind "Mistakes on
real calls", the knowledge-gap detector, the language pass's romanised-text test, the offline
extractor — keep their logic in code and take their words from the data file beside this
module, which the founder owns and corrects. `spoken_style.json` is the same arrangement for
how agents speak; this file is for what the checks listen for.

Each entry is keyed `<module>.<name>` and is either a string (a regular-expression fragment,
alternatives separated by `|`, or one word) or a list of words. A key the code asks for and
the file lacks is a defect and raises at import, so a missing entry fails the build rather
than a call. An entry the founder empties is a check switched off: `say` answers a pattern
that never matches, and `words` an empty tuple.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any, Final

#: A regular expression that matches nothing: what an emptied entry becomes, so the check
#: it feeds finds nothing rather than everything.
NEVER: Final = "(?!)"


@cache
def _entries() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        resources.files(__package__).joinpath("call_words.json").read_text(encoding="utf-8")
    )
    entries: dict[str, Any] = raw["entries"]
    return entries


def say(key: str) -> str:
    """The string entry `key`; `NEVER` when the founder has emptied it."""
    value = _entries()[key]
    if not isinstance(value, str):
        raise TypeError(f"call_words entry {key!r} is a list; read it with words()")
    return value or NEVER


def words(key: str) -> tuple[str, ...]:
    """The list entry `key`, in file order."""
    value = _entries()[key]
    if not isinstance(value, list):
        raise TypeError(f"call_words entry {key!r} is a string; read it with say()")
    return tuple(str(item) for item in value)


def keys() -> frozenset[str]:
    return frozenset(_entries())


__all__ = ["NEVER", "keys", "say", "words"]
