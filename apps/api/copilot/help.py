"""`help_lookup`: "how do I…" about Calevate itself, answered from the product's own words (D-938).

Pip already carries the screen directory in its prompt, so it can say WHERE a screen is. What
it could not do was answer "how do I add a team member" without composing a procedure of its
own, and an invented procedure is a wrong answer delivered confidently. This read returns only
text the product already ships:

* the screen that does it — its sidebar name, where it sits and its one-line summary
  (`screens.CLIENT_SCREENS`, guarded against `clientNav.ts` by `screens_test.py`);
* the term, if the question names one — the console's own glossary (`GLOSSARY`, a mirror of
  `apps/web/src/lib/glossary.tsx`, guarded by `help_test.py` so the two cannot drift);
* what Pip can do about it for this person — the area action's own line and the screen its
  result lands on (`areas.ENTRY_LINES`, `ActionTool.where`), filtered by the caller's role,
  so "I can do that for you" is never offered to someone the action would refuse.

Matching is word overlap against names, summaries, aliases and action lines, not a model: the
answer must be one of these entries or nothing, and "nothing matched" is said as such.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.screens import CLIENT_SCREENS, Screen, where_is
from apps.api.copilot.tools import ReadTool, ToolContext, _clean
from apps.api.core.rbac import role_has


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    term: str
    gloss: str


#: `apps/web/src/lib/glossary.tsx` `GLOSSARY`, client wording (`gloss`), key for key.
#: `help_test.py` parses that file and fails when the two differ.
GLOSSARY: Final[dict[str, GlossaryEntry]] = {
    "dlt": GlossaryEntry("DLT", "India's telecom message registry"),
    "pe": GlossaryEntry(
        "Principal Entity",
        "the business the registrar recognises as responsible for these campaigns",
    ),
    "tm": GlossaryEntry(
        "Telemarketer",
        "the business registered to place calls on another business's behalf — that is us",
    ),
    "dpdp": GlossaryEntry("DPDP", "India's Digital Personal Data Protection Act"),
    "dnc": GlossaryEntry("DNC", "do-not-call list"),
    "dnd": GlossaryEntry("DND", "India's national Do Not Disturb registry"),
    "kyc": GlossaryEntry(
        "KYC", "the identity check a business has to pass before an account is opened"
    ),
    "series140": GlossaryEntry("140", "India's marketing-call number range"),
    "series160": GlossaryEntry("160", "India's service-call number range"),
    "dataFiduciary": GlossaryEntry(
        "data fiduciary", "the business responsible for this data under India's privacy law"
    ),
}

#: Words that say nothing about WHICH screen: "how do I", "can you", "my", "the".
_STOP: Final = frozenset(
    (
        "a", "an", "and", "are", "as", "at", "be", "can", "could", "do", "does", "for",
        "from", "get", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "our",
        "please", "set", "show", "tell", "that", "the", "there", "this", "to", "up",
        "want", "we", "what", "when", "where", "which", "who", "why", "will", "with", "you",
        "your",
    )
)  # fmt: skip
_WORD: Final = re.compile(r"[a-z0-9]+")
_SCREENS_SHOWN: Final = 2
_ACTIONS_SHOWN: Final = 3


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def _stem(word: str) -> str:
    """Plural and -ing folded, so "invites" meets "invite" and "calling" meets "call"."""
    for suffix in ("ing", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _score(question: set[str], *texts: str) -> int:
    asked = {_stem(w) for w in question}
    found = set().union(*(_words(t) for t in texts))
    return len(asked & {_stem(w) for w in found})


def _best[T](scored: Iterable[tuple[int, T]], limit: int) -> list[T]:
    ranked = sorted((pair for pair in scored if pair[0] > 0), key=lambda p: -p[0])
    return [item for _score_, item in ranked[:limit]]


def _screen_lines(question: set[str], role: str | None) -> list[str]:
    hits = _best(
        ((_score(question, s.name, s.summary, " ".join(s.aliases)) * 2, s) for s in CLIENT_SCREENS),
        _SCREENS_SHOWN,
    )
    return [_screen_line(s, role) for s in hits]


def _screen_line(screen: Screen, role: str | None) -> str:
    closed = (
        screen.permission is not None and role is not None and not role_has(role, screen.permission)
    )
    return f"- Screen: {where_is(screen)}. {screen.summary}" + (
        " Their role cannot open it; the account owner can." if closed else ""
    )


def _glossary_lines(question: set[str]) -> list[str]:
    hits = _best(((_score(question, e.term, key), e) for key, e in GLOSSARY.items()), len(GLOSSARY))
    return [f"- {e.term}: {e.gloss}." for e in hits]


def _action_lines(question: set[str], role: str | None) -> list[str]:
    """Pip's own abilities that match, as `<area>_do <action>`, only those this role holds."""
    from apps.api.copilot import write_tools
    from apps.api.copilot.areas import AREA_OF, ENTRY_LINES, do_name

    def offered(name: str) -> bool:
        tool = write_tools.tool_named(name)
        return tool is not None and role is not None and role_has(role, tool.permission)

    hits = _best(
        (
            (_score(question, name.replace("_", " "), line), name)
            for name, line in ENTRY_LINES.items()
            if offered(name)
        ),
        _ACTIONS_SHOWN,
    )
    return [
        f"- You can do it: {do_name(AREA_OF[name])} {name} ({ENTRY_LINES[name]})." for name in hits
    ]


async def _help_lookup(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    del session
    question = _words(str(args.get("question") or ""))
    if not question:
        return "`question` was empty: pass what the person wants to do, in their words."
    lines = [
        *_screen_lines(question, context.role),
        *_glossary_lines(question),
        *_action_lines(question, context.role),
    ]
    if not lines:
        return (
            "No help entry matches. Say you do not know how, and name the closest screen from "
            "the directory if one fits; never describe steps that are not written here."
        )
    return _clean(
        "Calevate's own help. Answer from these lines only; never add steps they do not "
        "state. Offer to do it if an action is listed, or open_screen to take them there.\n"
        + "\n".join(lines)
    )


HELP_LOOKUP: Final = ReadTool(
    name="help_lookup",
    description="How to do something in Calevate: the screen, the term, and what Pip can do.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    },
    # Every client role holds it: the answer is the product's own help, and each line is
    # filtered by the caller's role before it is shown.
    permission="org:read",
    run=_help_lookup,
)


__all__ = ["GLOSSARY", "HELP_LOOKUP", "GlossaryEntry"]
