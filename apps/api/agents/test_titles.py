"""A practice test's name, short enough for a card on a phone (D-917).

One rule for every source of a title: the AI-written practice callers, the fixed callers
we wrote, tests saved from a call or by hand, and those Pip prepares. A title is the
caller's need in about six words. `title_problem` is what the writer is held to (it is sent
back once with the problem); `short_title` is the deterministic form used where a title
is too long and cannot be sent back, and for the card of every stored title.

Stored titles keep their full words: the judge, the fix suggester and Pip read them, and
"Why?" shows them. The card reads `short_title`, computed when the result is served, so a
title stored before this rule needs no migration.
"""

from __future__ import annotations

from typing import Final

#: Words in a title the card shows whole. Six fit one line of a phone card at body size.
MAX_TITLE_WORDS: Final = 6
#: Characters in the short form, for a run of long words six words would not hold.
MAX_SHORT_CHARS: Final = 48

#: Openings that name who acts rather than what the caller needs ("The agent takes ...",
#: "Caller asks ..."); the card drops them, since every test is a caller and an agent.
_FRAMING: Final = ("the agent ", "agent ", "the caller ", "a caller ", "caller ")

#: Words a cut title must not end on: "Takes the full number before…" reads as broken.
_DANGLING: Final = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "to",
        "for",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "before",
        "after",
        "about",
        "from",
        "if",
        "is",
        "it",
        "its",
        "that",
        "then",
        "when",
        "while",
        "so",
        "as",
        "their",
        "his",
        "her",
        "your",
        "you",
    ]
)


def _words(title: str) -> list[str]:
    return title.split()


def title_problem(title: str) -> str | None:
    """Why `title` is too long for a card, in words the writer can act on, or None."""
    words = _words(title)
    if len(words) > MAX_TITLE_WORDS:
        return f"{len(words)} words; use {MAX_TITLE_WORDS} or fewer"
    if len(" ".join(words)) > MAX_SHORT_CHARS:
        return f"over {MAX_SHORT_CHARS} characters; use shorter words"
    return None


def _unframed(words: list[str]) -> list[str]:
    line = " ".join(words).lower() + " "
    for opening in _FRAMING:
        rest = len(opening.split())
        if line.startswith(opening) and len(words) > rest + 1:
            kept = words[rest:]
            return [kept[0][:1].upper() + kept[0][1:], *kept[1:]]
    return words


def short_title(title: str) -> str:
    """`title` as the card shows it: whitespace collapsed, a leading "The agent"/"Caller"
    dropped, then cut to `MAX_TITLE_WORDS` words and `MAX_SHORT_CHARS` characters at a word
    boundary with an ellipsis. A title already inside both comes back unchanged but for
    whitespace. Empty in, empty out."""
    words = _words(title)
    if title_problem(title) is None:
        return " ".join(words)
    words = _unframed(words)
    kept: list[str] = []
    for word in words[:MAX_TITLE_WORDS]:
        if len(" ".join([*kept, word])) > MAX_SHORT_CHARS - 1:
            break
        kept.append(word)
    if len(kept) == len(words):
        return " ".join(kept)
    while len(kept) > 1 and kept[-1].lower().strip(",;:.-") in _DANGLING:
        kept.pop()
    if not kept:
        # One word longer than the card: cut inside it rather than show nothing.
        return words[0][: MAX_SHORT_CHARS - 1] + "…"
    return " ".join(kept).rstrip(" ,;:.-") + "…"


__all__ = ["MAX_SHORT_CHARS", "MAX_TITLE_WORDS", "short_title", "title_problem"]
