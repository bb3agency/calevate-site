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

from calevate_shared.call_script import substitute_variables
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
    # Case-insensitive (PIP-11): "kindly" mid-sentence is the same textbook word as "Kindly".
    # A listed word also matches the start of a longer word ("revert" in "reverting"); whether
    # it should is the founder's open question, pinned per language in the tests.
    found = re.finditer(re.escape(word), text, re.IGNORECASE)
    return any(_starts_word(text, m.start()) for m in found)


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
    # A merge field (`{{lead_name}}`, a list column) is replaced by the dial before anything
    # is spoken, so its key is never heard; the person's name it holds is a name like `names`.
    text = substitute_variables(text, {})
    for name in sorted((n.strip() for n in names if n.strip()), key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return list(dict.fromkeys(_LATIN_WORD.findall(text)))


#: The opening-line rules in the words both the writer's instruction and the problems sent
#: back for its repair use, so the model is told a rule and refused for it in one sentence.
OWN_LETTERS_RULE: Final = "write every word in the language's own letters, English words too"
TEXTBOOK_RULE: Final = (
    "never a textbook word callers do not say: the spoken-style guide lists each with the "
    "word to say instead"
)
QUESTION_END_RULE: Final = (
    "end on a question with a “?”, so the caller knows it is their turn to speak"
)
INTRODUCED_GREETING_RULE: Final = (
    "the agent's introduction just before it already greeted, so start with why you are "
    "calling or with the question"
)
INTRODUCED_NAMES_RULE: Final = (
    "the agent's introduction just before it already said who is calling and from which "
    "business, so leave the names out"
)
UNINTRODUCED_RULE: Final = (
    "nothing is said before this line, so greet the caller or say which business this is"
)


def latin_word_problem(
    where: str, text: str, tag: str | None, *, names: Sequence[str] = ()
) -> str | None:
    """A problem naming each English-letter word of a spoken line, for a model's repair;
    None when every word is in the language's own letters."""
    found = latin_words(text, tag, names=names)
    if not found:
        return None
    quoted = ", ".join(f"“{word}”" for word in found)
    return f"{where}: writes {quoted} in English letters; {OWN_LETTERS_RULE}"


def question_end_problem(where: str, text: str) -> str | None:
    """An opening line that does not hand the turn over with a question; None when it does."""
    if text.strip().endswith("?"):
        return None
    return f"{where}: does not end on a question; {QUESTION_END_RULE}"


#: A line that opens with a greeting, with the honorific that may follow it ("నమస్కారం అండి,",
#: "नमस्ते जी,") and the punctuation after it. One pattern for the practice check that a reply
#: greeted a second time (`agents/turn_checks.opened_again`, D-864), the writers' check that an
#: opening said after the agent's introduction does not greet (D-865), and the composer that
#: drops a greeting the introduction already said (`engine.join_first_words`).
_GREETING_HEAD: Final = re.compile(
    r"^\W*(?:hello|hi|hey|namaste|namaskar(?:am)?|good (?:morning|afternoon|evening)|"
    r"నమస్కారం|నమస్కారాలు|నమస్తే|హలో|హాయ్|नमस्ते|नमस्कार|हैलो|हेलो)(?=[\s,.!?।]|$)"
    r"(?:\s+(?:అండి|గారు|जी|ji|andi|garu|sir|madam)(?=[\s,.!?।]|$))?[\s,.!?।]*",
    re.IGNORECASE,
)


def opens_with_greeting(text: str) -> bool:
    return bool(_GREETING_HEAD.search(text))


def without_greeting(text: str) -> str:
    """`text` with a greeting at its start removed, honorific and punctuation too."""
    return _GREETING_HEAD.sub("", text.strip(), count=1).strip()


def names_used(text: str, names: Sequence[str]) -> list[str]:
    """Which of `names` (a business's, an agent's) `text` says, ignoring case."""
    folded = text.casefold()
    return [name.strip() for name in names if name.strip() and name.strip().casefold() in folded]


def introduced_opening_problem(where: str, text: str, *, names: Sequence[str] = ()) -> str | None:
    """What an opening line said right after the agent's own introduction must not do (D-865):
    greet, or say who is calling or from which business. None when it does neither."""
    if opens_with_greeting(text):
        return f"{where}: starts with a greeting; {INTRODUCED_GREETING_RULE}"
    said = names_used(text, names)
    if said:
        quoted = ", ".join(f"“{name}”" for name in said)
        return f"{where}: says {quoted}; {INTRODUCED_NAMES_RULE}"
    return None


def unintroduced_opening_problem(where: str, text: str, *, names: Sequence[str] = ()) -> str | None:
    """What an opening line said FIRST, with no introduction before it, must do (D-865):
    greet, or say one of `names`, so the caller hears who answered. None when it does."""
    if opens_with_greeting(text) or names_used(text, names):
        return None
    return f"{where}: neither greets nor says who is calling; {UNINTRODUCED_RULE}"


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
    "INTRODUCED_GREETING_RULE",
    "INTRODUCED_NAMES_RULE",
    "OWN_LETTERS_RULE",
    "OWN_LETTER_LANGUAGES",
    "QUESTION_END_RULE",
    "TEXTBOOK_RULE",
    "UNINTRODUCED_RULE",
    "Side",
    "english_problem",
    "generation_guidance",
    "has_indic_letters",
    "introduced_opening_problem",
    "latin_word_problem",
    "latin_words",
    "names_used",
    "opens_with_greeting",
    "question_end_problem",
    "textbook_note",
    "textbook_problem",
    "textbook_words",
    "unintroduced_opening_problem",
    "without_greeting",
]
