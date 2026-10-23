"""The deterministic language rules for text an AI WRITES into a script or a test (D-831).

Two rules, one per kind of text:

* A line somebody SAYS on a call (the agent's opening, a step's example line, sample phrases,
  the example call, a practice caller's line, a business's example line) uses the everyday
  word, never the textbook one `spoken_style.json` lists. `textbook_words` is the one matcher:
  the test loop's reply check (`agents/turn_checks.formal_swaps`) reads it too, so a word the
  founder adds to the list is caught everywhere at once.
* An INSTRUCTION to the in-call model (the business line, the role, the goal, a step's
  instruction, an objection's answer, the ending, the tone) is plain English, because the
  in-call model follows English instructions best and the caller never hears them (founder,
  19 Oct 2026, language-pack decision). Written in Telugu, those fields also carried the very
  textbook words the platform removes from speech. `has_indic_letters` is that check.

Both bind the AI's output only. The owner may type anything into their own script: nothing
here is called from a save path, and an edit is checked only on the fields the AI changed.

`generation_guidance` is the one place a model that writes spoken lines gets the language's
spoken guidance from, so the per-language packs replace its body and every writer follows.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Literal

from calevate_shared.spoken_style import (
    caller_guidance,
    pack_facts_rule,
    pack_lines,
    shipped_pack_choice,
    style_for,
    writer_guidance,
)


def _starts_word(text: str, at: int) -> bool:
    """Indic letters carry combining marks, so `\\b` does not mark a word start: a word counts
    when it opens the text or follows whitespace, a separator or any punctuation (Unicode P*
    and Z*), so curly quotes, dashes, a slash and an ellipsis count as the ASCII marks do.
    `re` has no Unicode property classes, hence a predicate rather than a lookbehind."""
    if at == 0:
        return True
    before = text[at - 1]
    return before.isspace() or unicodedata.category(before)[0] in "PZ"


def _uses_word(text: str, word: str) -> bool:
    return any(_starts_word(text, m.start()) for m in re.finditer(re.escape(word), text))


#: Every Indic script India uses, Devanagari (U+0900) through Malayalam (U+0D7F), except the
#: danda and double danda (U+0964-5), which are punctuation.
_INDIC_LETTER: Final = re.compile("[ऀ-ॣ०-ൿ]")


def textbook_words(text: str, tag: str | None) -> list[tuple[str, str]]:
    """(textbook word, what people say instead) for each word of the language's spoken-style
    list that `text` uses, in the list's order. Empty for a language with no list."""
    style = style_for(tag)
    if style is None or not text:
        return []
    return [(formal, spoken) for formal, spoken in style.word_swaps if _uses_word(text, formal)]


def textbook_note(swaps: Sequence[tuple[str, str]]) -> str:
    """The words and their spoken forms as one phrase: “మరియు” (join with ఇంకా, or leave it
    out); “వివరాలు” (say “details”)."""
    return "; ".join(
        f"“{formal}” ({spoken.strip('()') if spoken.startswith('(') else f'say “{spoken}”'})"
        for formal, spoken in swaps
    )


def textbook_problem(where: str, text: str, tag: str | None, *, allowed: str = "") -> str | None:
    """A problem naming the field and each textbook word with its spoken form, for a model's
    repair; None when the line is clean. A word that also appears in `allowed` (the owner's
    own words the line was written from) is the owner's, not the model's, and is not named."""
    owners = set(textbook_words(allowed, tag))
    swaps = [swap for swap in textbook_words(text, tag) if swap not in owners]
    if not swaps:
        return None
    return f"{where}: uses textbook words callers do not say: {textbook_note(swaps)}"


def has_indic_letters(text: str) -> bool:
    return bool(_INDIC_LETTER.search(text))


#: The languages whose spoken lines write every word in the language's own letters, English
#: words included (D-861): the ones whose spoken style was rewritten that way. The staged
#: languages keep Latin-letter loanwords until the founder rules on them, and English has no
#: other letters.
OWN_LETTER_LANGUAGES: Final = frozenset({"te", "hi"})
_LATIN_WORD: Final = re.compile(r"[A-Za-z]+")


def latin_words(text: str, tag: str | None, *, names: Sequence[str] = ()) -> list[str]:
    """The words of a spoken line written in English letters where its language writes them
    in its own (D-861), in order and once each. `names` (the business's and the agent's) are
    left as written: their spoken forms are not built yet (D-861's open item)."""
    if not tag or tag.split("-")[0].lower() not in OWN_LETTER_LANGUAGES:
        return []
    for name in sorted((n.strip() for n in names if n.strip()), key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return list(dict.fromkeys(_LATIN_WORD.findall(text)))


def latin_word_problem(
    where: str, text: str, tag: str | None, *, names: Sequence[str] = ()
) -> str | None:
    """A problem naming each English-letter word of a spoken line, for a model's repair;
    None when every word is in the language's own letters."""
    found = latin_words(text, tag, names=names)
    if not found:
        return None
    quoted = ", ".join(f"“{word}”" for word in found)
    return (
        f"{where}: writes {quoted} in English letters; write every word in the language's "
        "own letters, English words too"
    )


def english_problem(where: str, text: str) -> str | None:
    """A problem for an instruction field written in an Indic script; None when it is not."""
    if not has_indic_letters(text):
        return None
    return (
        f"{where}: write this instruction in plain English; only the lines the agent says are "
        "in the call language"
    )


Side = Literal["agent", "caller"]


def generation_guidance(
    tag: str | None, business_type: str | None = None, *, side: Side = "agent"
) -> str:
    """How the call language is spoken, for a model that writes lines in it: the agent's side
    (the script writer, the business copy) or the caller's (the practice-caller writer).
    Empty for a language with no style row."""
    if side == "caller":
        return caller_guidance(tag, business_type)
    # A founder-approved language pack (D-830) is the one statement of how the language is
    # spoken, so the agent-side writers follow it once it ships, in the form the live prompt
    # carries. Until a pack is approved, `shipped_pack_choice` is None and writers keep the
    # register guidance.
    choice = shipped_pack_choice(tag)
    if tag is not None and choice is not None:
        lines = pack_lines(tag, choice)
        if lines:
            return "\n".join([*lines, pack_facts_rule(tag, choice)])
    return writer_guidance(tag, business_type)


__all__ = [
    "OWN_LETTER_LANGUAGES",
    "Side",
    "english_problem",
    "generation_guidance",
    "has_indic_letters",
    "latin_word_problem",
    "latin_words",
    "textbook_note",
    "textbook_problem",
    "textbook_words",
]
