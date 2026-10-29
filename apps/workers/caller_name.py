"""Which captured names are really the caller's.

A caller who asks "who is this?" repeats the agent's name back ("Anjali?"), and the
extraction model has filed that as the caller's own name. This module is the deterministic
check that runs after the model, so the agent's name never becomes a lead's name whatever
the model reads. Pure functions: the pipeline loads the agent's names and applies them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from calevate_shared.call_script import pronunciations_of
from calevate_shared.events import TranscriptTurn

#: The extraction keys that hold the caller's name (`lead_fields.CORE_LEAD_FIELDS` and the
#: older `caller_name` spelling `_upsert_lead` still reads).
NAME_KEYS: Final = ("name", "caller_name")

#: Everything that is not part of a word. `\w` alone misses the Indic vowel signs and
#: viramas (they are marks, not letters), so the Devanagari and Telugu blocks are named,
#: less the two dandas, which are punctuation.
_NOT_WORD: Final = re.compile(r"(?:[^\ẁ-ͯऀ-ॣ०-ॿఀ-౿]|_)+")


def fold(text: str) -> str:
    """`text` for comparison: case, spacing and punctuation dropped, and Latin diacritics
    stripped ("Añjali" is "anjali"). Combining marks are stripped only after a Latin letter,
    because in Telugu and Devanagari they are the vowels, and dropping them would make
    different names equal."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    kept: list[str] = []
    for ch in decomposed:
        if unicodedata.combining(ch) and kept and kept[-1].isascii():
            continue
        kept.append(ch)
    return " ".join(_NOT_WORD.sub(" ", unicodedata.normalize("NFC", "".join(kept))).split())


def _has_run(haystack: str, needle: str) -> bool:
    """Whether `needle` is a whole-word run inside `haystack` (both folded)."""
    return bool(needle) and f" {needle} " in f" {haystack} "


def self_names(
    *, agent_name: str | None, business_name: str | None, script_body: str | None
) -> tuple[frozenset[str], frozenset[str]]:
    """The agent's own names and the business's, folded: each as written plus the spelling
    the owner taught the voice for it on the script's pronunciation line, which is how a
    Latin "Anjali" is also matched as the "అంజలి" a Telugu transcript carries. There is no
    general transliterator in this repo, so a script spelling nobody taught is not matched."""
    agent = fold(agent_name or "")
    business = fold(business_name or "")
    agents = {agent} if agent else set()
    businesses = {business} if business else set()
    for word, said in pronunciations_of(script_body):
        folded_word, folded_said = fold(word), fold(said)
        if not folded_said:
            continue
        if folded_word and folded_word in agents:
            agents.add(folded_said)
        if folded_word and folded_word in businesses:
            businesses.add(folded_said)
    return frozenset(agents), frozenset(businesses)


def _agent_said_it_first(name: str, turns: Sequence[TranscriptTurn]) -> bool:
    for turn in sorted(turns, key=lambda t: t.idx):
        if _has_run(fold(turn.text), name):
            return turn.speaker == "agent"
    return False


def is_self_name(
    captured: str,
    *,
    agent_names: Iterable[str],
    business_names: Iterable[str],
    turns: Sequence[TranscriptTurn],
    caller_names: Iterable[str] = (),
) -> bool:
    """Whether a captured "caller name" is really the agent's or the business's.

    The agent's name is matched as a whole-word run ("Anjali" against an agent called
    "Anjali Sales"), the business name only whole, because a caller named "Sai" must not lose
    their name to "Sri Sai Properties". A name the agent said before the caller ever did is
    the agent's introduction being echoed; a name the caller said first and the agent
    repeated back to confirm stays theirs.

    `caller_names` are the names we already hold for the person: the lead's, the
    campaign row's. The agent says that name first because it opens with it ("Umesh garu,
    ..."), so the said-first test would otherwise take every confirmed name from an
    outbound call, and a campaign lead would be created with none.
    """
    name = fold(captured)
    if not name:
        return False
    if any(_has_run(agent, name) for agent in agent_names):
        return True
    if name in set(business_names):
        return True
    if name in {fold(known) for known in caller_names}:
        return False
    return _agent_said_it_first(name, turns)


def without_self_names(
    data: Mapping[str, Any],
    *,
    agent_names: Iterable[str],
    business_names: Iterable[str],
    turns: Sequence[TranscriptTurn],
    caller_names: Iterable[str] = (),
) -> tuple[dict[str, Any], bool]:
    """`data` with any caller-name key that holds a self name removed, and whether one was.
    Removed rather than blanked so the call reads "Not said", which is what happened."""
    agents, businesses = frozenset(agent_names), frozenset(business_names)
    callers = tuple(caller_names)
    cleaned = dict(data)
    dropped = False
    for key in NAME_KEYS:
        value = cleaned.get(key)
        if isinstance(value, str) and is_self_name(
            value,
            agent_names=agents,
            business_names=businesses,
            turns=turns,
            caller_names=callers,
        ):
            del cleaned[key]
            dropped = True
    return cleaned, dropped


__all__ = ["NAME_KEYS", "fold", "is_self_name", "self_names", "without_self_names"]
