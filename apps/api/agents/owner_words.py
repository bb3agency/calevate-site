"""What an owner's own description of a job states, read by code and quoted, never guessed.

An owner who types "Help them install it, log in, set the language, add their farm, then
enter their first expense and their first sale. The app is free. Call only between 9am and
6pm. Never promise a call-back time." has given four kinds of thing at once: the tasks of
the call in their order, facts a caller may ask about, a calling window, and rules. Pasted
whole as a main task, only the script writer read them, and it was free to bundle the tasks
and drop the rest (first run of 28 Nov 2026, Rytu Khata). These readers pull each kind out
so it can land where the repo already keeps it: the plan's steps (`script_plan`), the pinned
facts (`teach/pinned`), the campaign's calling window (`campaigns.service.validated_window`).

Code rather than a model, for the same reason the opening's checks are code: every value is
the owner's own words, copied (a fact or rule is a whole sentence of theirs, a window is the
times they typed), so nothing can be invented and a test can say exactly what is read. The
cost is reach: these read English descriptions only. A description in another language
yields nothing here, and the script writer still reads it whole, as before.
"""

from __future__ import annotations

import re
from datetime import time
from typing import Final

#: A sentence ends at a full stop, question or exclamation mark followed by a space (so a
#: web address keeps its dots), or at a line break.
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+|\s*\n+\s*")
_PARENTHESES: Final = re.compile(r"\s*\([^()]*\)")
#: A sentence that tells the agent what to do only in some case is a branch, not a task.
_CONDITIONAL: Final = re.compile(r"^(?:if|when|unless|once|in case|whenever)\b", re.I)
#: A sentence that sets a rule for the agent. "Only" is a rule when it opens the sentence
#: ("Only call ...", "Only speak ..."); elsewhere it is a fact's ordinary word.
_RULE_START: Final = re.compile(
    r"^(?:never|do not|don't|dont|avoid|always|only|must not|mustn't)\b", re.I
)
#: Words of a statement about the business rather than an instruction to the agent.
_STATEMENT: Final = re.compile(
    r"\b(?:is|are|was|has|have|costs?|charges?|offers?|works?|runs?|opens?|closes?|"
    r"based|located|free|available)\b",
    re.I,
)
#: A sentence that tells the agent what to do opens with a verb said to it. A statement
#: opens with its subject, so these never make a fact.
_INSTRUCTION_START: Final = re.compile(
    r"^(?:call|ring|help|ask|go|wait|explain|offer|tell|say|guide|walk|keep|make|be|"
    r"speak|talk|start|end|close|thank|greet|introduce|follow|check|confirm|remind|"
    r"invite|book|note|collect|find|get|let|see|try|please)\b",
    re.I,
)

#: Things a person does on the call, said at the start of a clause. Only a sentence that
#: holds two or more of them is read as a list of tasks, so one verb in an ordinary sentence
#: is never a task.
_TASK_VERB: Final = re.compile(
    r"^(?:install|download|open|log\s*in(?:to)?|sign\s+(?:in|up)|register|set(?:\s+up)?|"
    r"change|choose|select|pick|add|enter|record|fill(?:\s+in)?|upload|create|book|pay|"
    r"verify|update|save|submit|connect|link|activate|scan|turn\s+on|switch\s+on|allow|"
    r"type|tap|start\s+using)\b",
    re.I,
)
#: What leads a task inside a sentence: "Help them install ...", "then enter ...".
_TASK_LEAD: Final = re.compile(
    r"^(?:(?:and|then|also|next|finally|after\s+that|lastly)\s+)*"
    r"(?:(?:help|ask|guide|get|tell|walk|have|show)\s+"
    r"(?:them|him|her|people|everyone|each\s+one|the\s+\w+|\w+s)\s+"
    r"(?:to\s+|through\s+|how\s+to\s+)?)?"
    r"(?:(?:and|then)\s+)*(?:to\s+)?",
    re.I,
)
_CLAUSE_SPLIT: Final = re.compile(r"\s*[,;]\s*|\s+(?:and\s+)?then\s+", re.I)
_AND: Final = re.compile(r"\s+and\s+", re.I)

#: A time of day as an owner types it: 9, 9am, 9 am, 9:30, 9.30 a.m., 18:00.
_TIME: Final = r"(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"
_WINDOW: Final = re.compile(
    rf"(?<![\d:.]){_TIME}\s*(?:-|\u2013|\u2014|to|till|until|and)\s*{_TIME}(?![\d:])", re.I
)
#: A window is read only from words about placing calls.
_ABOUT_CALLING: Final = re.compile(r"\b(?:call(?:s|ing|ed)?|ring|dial(?:l?ing)?|phone)\b", re.I)


def sentences(text: str) -> list[str]:
    """`text` as its sentences, each on one line, empty ones dropped."""
    return [" ".join(part.split()) for part in _SENTENCE_END.split(text or "") if part.strip()]


def _first_word(text: str) -> str:
    words = text.split()
    return words[0].casefold() if words else ""


def _sentence_tasks(sentence: str) -> list[str]:
    """The tasks one sentence lists, each "verb what": "enter their first expense and their
    first sale" is two, the verb shared, because both objects open alike; "log in with their
    number and password" stays one."""
    tasks: list[str] = []
    verb = ""
    obj = ""
    for clause in _CLAUSE_SPLIT.split(_PARENTHESES.sub("", sentence).rstrip(".!?")):
        for index, part in enumerate(_AND.split(clause)):
            said = _TASK_LEAD.sub("", part.strip(), count=1)
            found = _TASK_VERB.match(said)
            if found:
                verb, obj = found.group(0), said[found.end() :].strip()
                tasks.append(f"{verb} {obj}".strip())
            elif tasks and index > 0 and obj and _first_word(said) == _first_word(obj):
                obj = said
                tasks.append(f"{verb} {said}")
            elif tasks:
                joint = " and " if index > 0 else ", "
                tasks[-1] = f"{tasks[-1]}{joint}{part.strip()}"
    return tasks


def owner_tasks(text: str) -> list[str]:
    """The things the description asks the person to do, in its order: each sentence that
    lists two or more of them, read clause by clause. [] when it lists none."""
    out: list[str] = []
    for sentence in sentences(text):
        if _CONDITIONAL.match(sentence) or _RULE_START.match(sentence):
            continue
        found = _sentence_tasks(sentence)
        if len(found) >= 2:
            out += found
    return out


def stated_rules(text: str) -> list[str]:
    """The sentences that set the agent a rule ("Never ...", "Do not ...", "Always ..."),
    word for word."""
    return [s for s in sentences(text) if _RULE_START.match(s)]


def stated_facts(text: str, *, longest: int = 200) -> list[str]:
    """The sentences that state something about the business ("The app is free for
    farmers.", "We are based in Hyderabad."), word for word: not a rule, not an instruction
    to the agent, not a case, not a list of tasks, and short enough to be one fact."""
    out: list[str] = []
    for sentence in sentences(text):
        if len(sentence) > longest or sentence.endswith("?"):
            continue
        if _RULE_START.match(sentence) or _CONDITIONAL.match(sentence):
            continue
        if _INSTRUCTION_START.match(sentence) or len(_sentence_tasks(sentence)) >= 2:
            continue
        if _STATEMENT.search(sentence) and calling_window(sentence) is None:
            out.append(sentence)
    return out


def _clock(hour: str, minute: str | None, meridiem: str | None) -> tuple[int, int, str] | None:
    h, m = int(hour), int(minute or 0)
    if m > 59 or h > 23:
        return None
    return h, m, (meridiem or "").replace(".", "").casefold()


def _as_time(h: int, m: int, meridiem: str) -> time | None:
    if meridiem:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if meridiem == "pm" else 0)
    return time(h, m)


def _window(match: re.Match[str]) -> tuple[time, time] | None:
    first = _clock(match.group(1), match.group(2), match.group(3))
    second = _clock(match.group(4), match.group(5), match.group(6))
    if first is None or second is None:
        return None
    (h1, m1, x1), (h2, m2, x2) = first, second
    end = _as_time(h2, m2, x2)
    # "9 to 6pm": the start takes the end's half of the day unless that puts it at or after
    # the end, when it is the morning. Two bare numbers read as a working day: "9 to 6" is
    # 9am to 6pm, "9 to 18" is already a clock.
    if not x1 and x2:
        x1 = x2
        same_half = _as_time(h1, m1, x1)
        if same_half is None or end is None or same_half >= end:
            x1 = "am"
    if not x1 and not x2 and h2 <= 12 and h2 < h1:
        x1, x2 = "am", "pm"
        end = _as_time(h2, m2, x2)
    start = _as_time(h1, m1, x1)
    if start is None or end is None or start >= end:
        return None
    return start, end


def calling_window(text: str) -> tuple[time, time] | None:
    """The calling window the description gives ("Call only between 9am and 6pm"), or None:
    read only from a sentence about placing calls, and only when it gives one window."""
    found: list[tuple[time, time]] = []
    for sentence in sentences(text):
        if not _ABOUT_CALLING.search(sentence):
            continue
        for match in _WINDOW.finditer(sentence):
            window = _window(match)
            if window is not None and window not in found:
                found.append(window)
    return found[0] if len(found) == 1 else None


def narrowed(window: tuple[time, time], within: tuple[time, time]) -> tuple[time, time] | None:
    """`window` inside `within` (the platform's lawful hours), or None when nothing of it is
    left: an owner's window may only narrow the law's, never widen it."""
    start, end = max(window[0], within[0]), min(window[1], within[1])
    return (start, end) if start < end else None


__all__ = [
    "calling_window",
    "narrowed",
    "owner_tasks",
    "sentences",
    "stated_facts",
    "stated_rules",
]
