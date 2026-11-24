"""The company training as fixed sections, each item backed by a quote the code finds.

WHY. Asked for the training as free text, the writer blended whatever sources it read: given
a guide written for one campaign, Rytu Khata's training described the company as "helping
farmers install the app" and carried the campaign's opening and call steps, and said nothing
was missing (founder, 24 Nov 2026). A sentence in the ask does not stop that; a shape does.

HOW. Two established patterns. Voice-agent prompts are written as labelled sections that
keep the business and how to speak apart from the task and call flow (OpenAI realtime
prompting guide, developers.openai.com/cookbook/examples/realtime_prompting_guide; ElevenLabs
prompting guide, elevenlabs.io/docs/conversational-ai/best-practices/prompting-guide; read 24
Nov 2026). Grounded extraction asks for a verbatim quote per field and has the code check it,
treating a field with no checked quote as absent rather than filled ("Traceable by Design",
arxiv.org/pdf/2605.30995; SafePassage, arxiv.org/html/2510.00276v1; read 24 Nov 2026). So:

* the writer returns items under fixed keys, each with the source passage it rests on; there
  is no key for a call's opening, steps or reason for calling, so they have nowhere to go;
* an item whose quote is not a passage of what the writer was given (`quoted_in`, the check
  the campaign script review uses) is dropped, never kept on the model's word;
* the text agents read is built here under fixed headings, so every training has the same
  shape and nothing is written that no source says;
* a part only material about the business can give (`MISSING_PARTS`) with no checked item is
  named, and the owner is asked for it rather than the part being guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from apps.workers.campaign_script_ask import quoted_in

#: (key, heading) in the order agents read them. The first three are what the business is;
#: the rest are true on every call. Nothing here is about one piece of work.
SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("business", "About the business"),
    ("offer", "What it offers"),
    ("customers", "Who its customers are"),
    ("speaking", "How agents speak"),
    ("names", "Names and how to say them"),
    ("policies", "Policies"),
    ("questions", "Questions callers ask"),
    ("objections", "Objections and how to answer them"),
)
#: The parts only material about the business can give; one with no checked item is asked of
#: the owner (founder, 24 Nov 2026).
MISSING_PARTS: Final = ("business", "offer", "customers")
_ITEMS_PER_SECTION: Final = 20
_ITEM_CHARS: Final = 600

_ITEM: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["text", "quote"],
    "additionalProperties": False,
}
_QUESTION: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["question", "answer", "quote"],
    "additionalProperties": False,
}
SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        key: {"type": "array", "items": _QUESTION if key == "questions" else _ITEM}
        for key, _heading in SECTIONS
    },
    "required": [key for key, _heading in SECTIONS],
    "additionalProperties": False,
}

#: What each key holds, for the ask. Kept beside `SECTIONS` so the two cannot drift.
FIELDS_ASK: Final = (
    "Return JSON with these keys, each a list of items; an item has text (one plain English "
    "sentence an agent reads) and quote (the exact words of the material it comes from, "
    "copied character for character, in whatever language the material uses). "
    "business: what the business is and what it does, as a company. "
    "offer: what it sells or provides. "
    "customers: who it serves. "
    "speaking: how its agents talk on any call (tone, how to address people, words to use or "
    "avoid). "
    "names: names and how to say them. "
    "policies: prices, hours, delivery, payment, returns, privacy. "
    "questions: questions any caller may ask, each with question, a short spoken answer and "
    "quote. "
    "objections: what a caller may object and how to answer. "
    "Never put in any list what one call or one piece of work is for, who it calls, how it "
    "opens or its steps: each script holds those. Leave a list empty rather than fill it from "
    "material that does not say it."
)


@dataclass(frozen=True, slots=True)
class Written:
    """The training as agents read it, and the parts the material did not give."""

    text: str
    missing: tuple[str, ...]
    #: Items dropped because their quote is not in the material.
    unsourced: int


def _clean(value: object) -> str:
    return " ".join(value.split())[:_ITEM_CHARS] if isinstance(value, str) else ""


def _sentence(text: str) -> str:
    return text if text[-1:] in ".?!" else f"{text}."


def _kept(raw: Mapping[str, Any], key: str, corpus: str) -> tuple[list[str], int]:
    """(lines, dropped) of one section: items whose quote is a passage of `corpus`."""
    value = raw.get(key)
    lines: list[str] = []
    dropped = 0
    for item in (value if isinstance(value, list) else [])[:_ITEMS_PER_SECTION]:
        if not isinstance(item, Mapping):
            continue
        quote = _clean(item.get("quote"))
        if key == "questions":
            question, answer = _clean(item.get("question")), _clean(item.get("answer"))
            if not (question and answer):
                continue
            line = f"Asked: {_sentence(question)} Answer: {_sentence(answer)}"
        else:
            text = _clean(item.get("text"))
            if not text:
                continue
            line = _sentence(text)
        if not quoted_in(quote, corpus):
            dropped += 1
            continue
        if line not in lines:
            lines.append(line)
    return lines, dropped


def written(raw: Mapping[str, Any], corpus: str) -> Written:
    """The sections of `raw` checked against `corpus` (what the writer was given about the
    business, never the current training: quoting it would carry forward what no source
    says) and built into the text agents read."""
    blocks: list[str] = []
    missing: list[str] = []
    unsourced = 0
    for key, heading in SECTIONS:
        lines, dropped = _kept(raw, key, corpus)
        unsourced += dropped
        if lines:
            blocks.append("\n".join([f"{heading}:", *lines]))
        elif key in MISSING_PARTS:
            missing.append(key)
    return Written("\n\n".join(blocks), tuple(missing), unsourced)


def corpus_of(sources: str, owner_words: Sequence[str]) -> str:
    """Where a quote may come from: the material and the owner's own edits."""
    return "\n\n".join([sources, *owner_words])


__all__ = [
    "FIELDS_ASK",
    "MISSING_PARTS",
    "SCHEMA",
    "SECTIONS",
    "Written",
    "corpus_of",
    "written",
]
