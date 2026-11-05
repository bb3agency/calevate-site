"""The Indian-language words the call checks look for, read from `call_words.json`.

The founder's rule (5 Nov 2026): no Telugu, Hindi or other Indian-language word is written
in code. The checks that read a real call's transcript — the turn checks behind "Mistakes on
real calls", the knowledge-gap detector, the language pass's romanised-text test, the offline
extractor — keep their logic in code and take their words from the data file beside this
module, which the founder owns and corrects. `spoken_style.json` is the same arrangement for
how agents speak; this file is for what the checks listen for.

It is the ONE file for words a check listens for: the do-not-call phrases, the AI and
recording words of an opening, the script checks and the practice-run and teach detectors
read it too. `spoken_lines.json` holds only what is said.

Each entry is keyed `<module>.<name>` and is a string (a regular-expression fragment,
alternatives separated by `|`, or one word), a list of words, or a table by language. A key
the code asks for and the file lacks is a defect and raises at import, so a missing entry
fails the build rather than a call. An entry the founder empties is a check switched off:
`say` answers a pattern that never matches, `words` an empty tuple, and `extend` the English
alternatives alone, so a pattern whose English stays in code keeps its English check.
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


def extend(english: str, key: str) -> str:
    """`english`, a pattern of alternatives kept in code, with the string entry `key`'s
    alternatives after it; `english` alone when the founder has emptied the entry. Rather
    than `say` with `NEVER` appended, so the result is also a valid PostgreSQL pattern."""
    value = _entries()[key]
    if not isinstance(value, str):
        raise TypeError(f"call_words entry {key!r} is not a string")
    return f"{english}|{value}" if value else english


def _frozen(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return {k: _frozen(v) for k, v in value.items()}
    return value


def table(key: str) -> dict[str, Any]:
    """The table entry `key`, keyed as the file keys it (a language code), lists as tuples.
    A fresh dict each call."""
    value = _entries()[key]
    if not isinstance(value, dict):
        raise TypeError(f"call_words entry {key!r} is not a table")
    return {k: _frozen(v) for k, v in value.items()}


def keys() -> frozenset[str]:
    return frozenset(_entries())


__all__ = ["NEVER", "extend", "keys", "say", "table", "words"]
