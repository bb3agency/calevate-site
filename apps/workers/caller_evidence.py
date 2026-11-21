"""Text values the caller never said, copied from the business's side of the call.

The extraction request carries the business's own description of itself and of what the
agent is for (`MomentsBrief`), and the agent explains the product on the call. A model
asked "purpose of using it" then fills the field from that description: the caller said
"I selected Telugu" and the lead read "To manage farm details and expenses" (21 Nov 2026
call review). The prompt forbids it; this is the check that runs after the model, so the
rule holds whatever the model reads.

The test is where a value's words come from. A caller states a value in one answer, so the
caller side is scored by its single best line; the business side is every agent line plus
the brief. A value most of whose words only the business side says, with no caller line
saying more than one of them, was not the caller's. Short values are not judged: "Paddy"
for a caller's "vari" shares nothing with either side and is the ordinary case of a value
translated from the call's language.

A transcript whose caller lines carry no Latin-letter words (a Telugu-script reading) cannot
be compared with an English value at all, so it is not judged either. Dropping a real value
loses a detail the owner can still hear on the recording; keeping a borrowed one tells the
owner something the caller never said, which is the error this exists to stop.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from calevate_shared.extraction import ExtractionSchemaSpec, MomentsBrief

from apps.workers.moments import Turn, content_words

#: A value needs this many content words before where they come from says anything.
MIN_JUDGED_WORDS: Final = 3

#: The most words of a value one caller line may share and the value still be borrowed: a
#: caller using one of the product's own words ("farm") in passing does not state a purpose.
MAX_CALLER_SHARED: Final = 1


def _latin(words: Iterable[str]) -> set[str]:
    return {word for word in words if word.isascii()}


def brief_texts(brief: MomentsBrief) -> list[str]:
    """The business's own wording the extraction request carried."""
    return [brief.business_type, brief.business_line, brief.agent_goal, *brief.script_steps]


def borrowed_keys(
    data: Mapping[str, Any],
    spec: ExtractionSchemaSpec,
    *,
    turns: Sequence[Turn],
    business_texts: Iterable[str],
) -> set[str]:
    """The text fields in `data` whose value came from the business's side, not the caller."""
    caller_lines = [_latin(content_words(t.text)) for t in turns if t.speaker == "caller"]
    if not any(caller_lines):
        return set()
    business_words: set[str] = set()
    for text in [*(t.text for t in turns if t.speaker != "caller"), *business_texts]:
        business_words |= _latin(content_words(text))
    borrowed: set[str] = set()
    for field in spec.fields:
        value = data.get(field.key)
        if field.type != "text" or not isinstance(value, str):
            continue
        words = _latin(content_words(value))
        if len(words) < MIN_JUDGED_WORDS:
            continue
        caller_best = max(len(words & line) for line in caller_lines)
        if caller_best > MAX_CALLER_SHARED:
            continue
        if 2 * len(words & business_words) >= len(words):
            borrowed.add(field.key)
    return borrowed


def without_borrowed(
    data: Mapping[str, Any],
    spec: ExtractionSchemaSpec,
    *,
    turns: Sequence[Turn],
    business_texts: Iterable[str],
) -> tuple[dict[str, Any], set[str]]:
    """`data` without its borrowed values, and their keys. Removed rather than blanked so the
    call reads "Not said", which is what happened."""
    keys = borrowed_keys(data, spec, turns=turns, business_texts=business_texts)
    return {k: v for k, v in data.items() if k not in keys}, keys


__all__ = [
    "MAX_CALLER_SHARED",
    "MIN_JUDGED_WORDS",
    "borrowed_keys",
    "brief_texts",
    "without_borrowed",
]
