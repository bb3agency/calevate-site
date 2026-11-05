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

THE FILE IS THE SHIPPED DEFAULT; THE FOUNDER EDITS ON THE CONSOLE (G-C2). Ops > Call words
saves an entry as a revision in the database (`apps/api/ops/call_words_store.py`), and each
API and worker process installs the newest revisions over the file with `install`. A check
therefore never compiles its pattern at import: it holds a `Live` (or a `LivePattern`), which
rebuilds from the entries the first time it is used after an install, so an edit reaches a
running process without a deploy and an unchanged process pays one integer comparison per use.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import weakref
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final

#: A regular expression that matches nothing: what an emptied entry becomes, so the check
#: it feeds finds nothing rather than everything.
NEVER: Final = "(?!)"


log = logging.getLogger(__name__)


@cache
def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        resources.files(__package__).joinpath("call_words.json").read_text(encoding="utf-8")
    )
    return raw


def shipped() -> Mapping[str, Any]:
    """Every entry as the file ships it: the default an edit is measured against."""
    entries: dict[str, Any] = _raw()["entries"]
    return entries


def about() -> str:
    """The file's own description of the lists."""
    return str(_raw().get("about", ""))


def missing_notes() -> Mapping[str, str]:
    """The file's `missing` section: what the founder is asked to write, by key. A key ending
    `.*` covers every entry under that prefix."""
    notes: dict[str, str] = _raw().get("missing", {})
    return notes


def entry_notes() -> Mapping[str, str]:
    """The file's `notes` section: how an entry is used, by key."""
    notes: dict[str, str] = _raw().get("notes", {})
    return notes


#: The file with the console's revisions layered over it, or None for the file alone.
_installed: dict[str, Any] | None = None
#: Bumped by every `install`; what each `Live` compares against.
_generation = 0
#: Set only while `trial` builds every check against a candidate edit.
_trial: ContextVar[Mapping[str, Any] | None] = ContextVar("call_words_trial", default=None)


def _entries() -> Mapping[str, Any]:
    trial = _trial.get()
    if trial is not None:
        return trial
    return _installed if _installed is not None else shipped()


def problems(key: str, value: Any) -> list[str]:
    """Why `value` cannot stand as entry `key`, in plain words; empty when it can.

    The value must keep the shape the file ships (a pattern stays a pattern, a list a list, a
    table a table of the same make), because the code reading the entry depends on it, and
    every word or pattern in it must compile as a regular expression."""
    default = shipped().get(key)
    if default is None:
        return ["The code does not read a word list by that name."]
    found: list[str] = []
    if not _conforms(value, default, top=True):
        found.append(f"This entry must be {_shape_name(default)}.")
        return found
    for text in strings_of(value):
        try:
            compiled = re.compile(text)
        except re.error as exc:
            found.append(f"“{text[:60]}” is not a valid pattern: {exc}.")
            continue
        # An emptied entry is a check switched off (`say` turns it into NEVER); a pattern
        # that matches empty text is the opposite, a check that fires on every call.
        if text and compiled.fullmatch("") is not None:
            found.append(f"“{text[:60]}” matches empty text, so it would match every call.")
    return found


def _shape_name(default: Any) -> str:
    if isinstance(default, str):
        return "one pattern"
    if isinstance(default, list):
        return "a list of words"
    return "a table by language in the same form as the shipped one"


def _conforms(value: Any, template: Any, *, top: bool = False) -> bool:
    if isinstance(template, str):
        return isinstance(value, str)
    if isinstance(template, list):
        if not isinstance(value, list):
            return False
        item = template[0] if template else ""
        if isinstance(item, list):
            # A row of fixed width, such as a do-not-call rule's [id, pattern] pair.
            return all(
                isinstance(v, list) and len(v) == len(item) and _conforms(v, item) for v in value
            )
        return all(_conforms(v, item) for v in value)
    if isinstance(template, dict):
        if not isinstance(value, dict):
            return False
        if top:
            # A table by language: any language code, each in the shape the shipped
            # languages share, so the founder can add a language without a release.
            shapes = list(template.values())
            return bool(shapes) and all(
                isinstance(k, str) and re.fullmatch(r"[a-z]{2,3}", k) and _conforms(v, shapes[0])
                for k, v in value.items()
            )
        return set(value) == set(template) and all(_conforms(value[k], template[k]) for k in value)
    return False


def strings_of(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings_of(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_of(item)


def install(overrides: Mapping[str, Any] | None) -> None:
    """Layer the console's entries over the file in this process (None: the file alone).

    An override for a key the file no longer has, or in a shape the file no longer ships, is
    skipped and logged: the code that reads it changed in a release, and the shipped entry is
    what that code was written against."""
    global _installed, _generation
    merged: dict[str, Any] | None = None
    if overrides:
        merged = dict(shipped())
        for key, value in overrides.items():
            if problems(key, value):
                log.warning("call_words_override_skipped", extra={"entry_key": key})
                continue
            merged[key] = value
    _installed = merged
    _generation += 1


def generation() -> int:
    """How many times entries were installed in this process."""
    return _generation


#: Every `Live` built so far, for `trial`.
_LIVES: weakref.WeakSet[Live[Any]] = weakref.WeakSet()


class Live[T]:
    """A value built from the entries, rebuilt the first time it is used after `install`.

    Built once when made, so a module that asks for a key the file lacks still fails at
    import. If a rebuild raises, the last good value stays and the failure is logged: a check
    keeps listening for the words it had rather than taking a call's processing down with it.
    `postgres` marks a pattern handed to PostgreSQL rather than Python, which `trial` reports
    so the console can test it there."""

    __slots__ = ("__weakref__", "_at", "_build", "_value", "postgres")

    def __init__(self, build: Callable[[], T], *, postgres: bool = False) -> None:
        self._build = build
        self.postgres = postgres
        self._value = build()
        self._at = _generation
        _LIVES.add(self)

    def __call__(self) -> T:
        if _trial.get() is not None:
            return self._build()
        at = _generation
        if self._at != at:
            try:
                self._value = self._build()
            except (re.error, KeyError, TypeError, ValueError):
                log.exception(
                    "call_words_rebuild_failed", extra={"builder": self._build.__module__}
                )
            self._at = at
        return self._value


class LivePattern:
    """A compiled regular expression over the entries, used as one: `search`, `match`,
    `findall` and the rest answer from the pattern built from the newest installed words."""

    __slots__ = ("_live",)

    def __init__(self, source: Callable[[], str], flags: int | re.RegexFlag = 0) -> None:
        self._live: Live[re.Pattern[str]] = Live(lambda: re.compile(source(), flags))

    @property
    def compiled(self) -> re.Pattern[str]:
        return self._live()

    @property
    def pattern(self) -> str:
        return self._live().pattern

    def search(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> re.Match[str] | None:
        return self._live().search(string, pos, endpos)

    def match(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> re.Match[str] | None:
        return self._live().match(string, pos, endpos)

    def fullmatch(
        self, string: str, pos: int = 0, endpos: int = sys.maxsize
    ) -> re.Match[str] | None:
        return self._live().fullmatch(string, pos, endpos)

    def finditer(
        self, string: str, pos: int = 0, endpos: int = sys.maxsize
    ) -> Iterator[re.Match[str]]:
        return self._live().finditer(string, pos, endpos)

    def findall(self, string: str, pos: int = 0, endpos: int = sys.maxsize) -> list[Any]:
        return self._live().findall(string, pos, endpos)

    def split(self, string: str, maxsplit: int = 0) -> list[str | Any]:
        return self._live().split(string, maxsplit)

    def sub(self, repl: str | Callable[[re.Match[str]], str], string: str, count: int = 0) -> str:
        return self._live().sub(repl, string, count)


@dataclass(frozen=True, slots=True)
class Trial:
    """What building every check against a candidate edit found."""

    #: (the module whose check failed, the error), one per check that would not build.
    failures: tuple[tuple[str, str], ...]
    #: The patterns PostgreSQL will be handed, as the candidate would build them.
    postgres_patterns: tuple[str, ...]


def trial(key: str, value: Any) -> Trial:
    """Build every check this process has loaded with entry `key` set to `value` (None: the
    shipped entry), without installing it. A fragment that compiles alone can still break the
    pattern it is joined into; this is where that shows, before the edit is saved."""
    candidate = dict(_entries())
    candidate[key] = shipped()[key] if value is None else value
    failures: list[tuple[str, str]] = []
    postgres: list[str] = []
    token = _trial.set(candidate)
    try:
        for live in list(_LIVES):
            try:
                built = live._build()
            except (re.error, KeyError, TypeError, ValueError) as exc:
                failures.append((live._build.__module__, str(exc)))
                continue
            if live.postgres and isinstance(built, str):
                postgres.append(built)
    finally:
        _trial.reset(token)
    return Trial(failures=tuple(failures), postgres_patterns=tuple(postgres))


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


__all__ = [
    "NEVER",
    "Live",
    "LivePattern",
    "Trial",
    "about",
    "entry_notes",
    "extend",
    "generation",
    "install",
    "keys",
    "missing_notes",
    "problems",
    "say",
    "shipped",
    "strings_of",
    "table",
    "trial",
    "words",
]
