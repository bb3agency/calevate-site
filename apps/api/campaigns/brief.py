"""What a campaign is for: its purpose and its goal, in the business's own words.

`purpose` says why these people are being called ("our new drip irrigation subsidy");
`goal` says what a good call ends with ("they book a free soil test"). Both ride every call
the campaign places, as that call's reason (`campaign_call_reason`), and the goal is what the
post-call reading judges each answered call against (`calls.goal_reached`).

The limits are the call's, not the screen's. The reason travels as ONE Place Call variable,
which the vendor cuts at `CALL_VARIABLE_VALUE_MAX` (150) characters, so the two limits are
set so the whole reason always fits uncut: a goal cut off mid-sentence would leave the agent
aiming at half a goal. There is no third "key points" field for the same reason: it would not
fit beside these two, and a value the agent never hears is not worth asking for.

Both are spoken material (the agent reads them as its own context), so they are one line of
plain words: no markdown, bullets or emoji, which a voice would read out or trip on.
"""

from __future__ import annotations

import re
from typing import Final

from calevate_shared.invisible_text import strip_invisible

PURPOSE_MIN: Final = 3
PURPOSE_MAX: Final = 90
GOAL_MIN: Final = 3
GOAL_MAX: Final = 50

#: How the reason joins the two. Its length counts against `CALL_VARIABLE_VALUE_MAX`.
GOAL_JOIN: Final = ". Aim: "
#: The longest reason the two limits allow, with its closing full stop.
REASON_MAX: Final = PURPOSE_MAX + len(GOAL_JOIN) + GOAL_MAX + 1

#: Formatting a voice would read out: markdown marks, bullets, braces (our variable syntax).
_FORMATTING: Final = re.compile(r"[*#`_~|\[\]<>{}]|^\s*(?:[-•]|\d+[.)])\s")
_EMOJI: Final = re.compile("[☀-➿\U0001f000-\U0001faff️]")


class BriefLineError(ValueError):
    """A purpose or goal that cannot be spoken as written. The message is shown to the client."""


def clean_brief_line(value: str | None, *, what: str, low: int, high: int) -> str | None:
    """`value` as one trimmed line, or None when it is blank. Raises `BriefLineError` with a
    sentence the client can act on when it is too short, too long or carries formatting."""
    if value is None:
        return None
    line = " ".join(strip_invisible(value).split())
    if not line:
        return None
    if len(line) < low:
        raise BriefLineError(f"Write a few more words for the {what}.")
    if len(line) > high:
        raise BriefLineError(f"Keep the {what} to {high} characters.")
    if _FORMATTING.search(line) or _EMOJI.search(line):
        raise BriefLineError(f"Write the {what} as plain words, without symbols or emoji.")
    return line


def clean_purpose(value: str | None) -> str | None:
    return clean_brief_line(value, what="reason for calling", low=PURPOSE_MIN, high=PURPOSE_MAX)


def clean_goal(value: str | None) -> str | None:
    return clean_brief_line(value, what="goal", low=GOAL_MIN, high=GOAL_MAX)


def campaign_call_reason(purpose: str | None, goal: str | None) -> str | None:
    """The reason a campaign's dial carries (`CallContext.context_note` -> `REASON_LINE`):
    "<purpose>. Aim: <goal>.", either half alone when only one is set, None when neither is.

    At most `REASON_MAX` characters, inside `CALL_VARIABLE_VALUE_MAX`, so the adapter's own
    cut never shortens it."""
    why = (purpose or "").strip().rstrip(".").strip()
    aim = (goal or "").strip().rstrip(".").strip()
    if why and aim:
        return f"{why}{GOAL_JOIN}{aim}."
    if why:
        return f"{why}."
    if aim:
        return f"Aim: {aim}."
    return None


__all__ = [
    "GOAL_JOIN",
    "GOAL_MAX",
    "GOAL_MIN",
    "PURPOSE_MAX",
    "PURPOSE_MIN",
    "REASON_MAX",
    "BriefLineError",
    "campaign_call_reason",
    "clean_brief_line",
    "clean_goal",
    "clean_purpose",
]
