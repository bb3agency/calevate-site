"""What a suggested test fix may never do (D-899, D-909): take away something the agent can
do, narrow what it handles, chase a test a platform rule owns, or report an effect nobody
has tested.

The founder's example (Sri Estates, 27-28 Oct 2026), for the failed test "Gives part of
another number": the step "Find out what they need" rewritten to "If they ask to send
information to a phone number, tell them you cannot do that as you only handle property
enquiries and site visits ... Never accept or confirm partial or full phone numbers", with
the reason "I have restricted the agent to only handling property enquiries". The agent
takes numbers and sends WhatsApp live; part of a number is a platform rule (ask for the
rest, wait, read all ten back), so that test is ours and never the script's.

Two callers, one rule set. The improver (`apps/workers/agent_test_ai.proposal_from_model`)
checks each edit with `grounding_problem`, which also knows the agent's in-call actions and
the test's good answer. A proposal already stored is checked again with `stored_problem`
before it is offered or applied (`script_routes`), so a suggestion written before a rule
existed is never shown as current. Pure regular expressions over English: a suggested
instruction is in plain English (`script_edits.language_problem`), and only the words an
edit ADDS are read, so a step the owner wrote is never held against the suggestion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from calevate_shared.call_script import CallScript
from pydantic import ValidationError

from apps.api.agents.script_edits import ScriptEdit, added_text, kept_problem, sentences
from apps.api.agents.trial_results import PLATFORM_RULE_TESTS

if TYPE_CHECKING:
    from apps.api.agents.test_conversations import AgentBrief

#: A sentence that refuses or forbids doing something: "never accept", "tell them you cannot
#: do that", "do not send".
_REFUSES: Final = re.compile(
    r"\b(?:never|not|no longer|cannot|can't|can not|don't|do not|won't|must not|refuse|"
    r"decline|unable to)\b\W+(?:\w+\W+){0,3}?(?:accept|take|taking|collect|note|confirm|"
    r"send|share|use|offer|book|arrange|transfer|connect|hand|give|do that|do this|help|"
    r"handle|record|save|call|process|write|read back|repeat)",
    re.IGNORECASE,
)
#: What the agent can always do: take a caller's number (the platform's read-back rule).
_NUMBERS: Final = re.compile(r"number|digits|phone|mobile", re.IGNORECASE)
#: Words naming each kind of in-call action, for the capability check.
_ACTION_WORDS: Final[dict[str, re.Pattern[str]]] = {
    "whatsapp": re.compile(r"whats\s?app|send|message|details|brochure", re.IGNORECASE),
    "payment_link": re.compile(r"payment|link|send|pay", re.IGNORECASE),
    "calendar": re.compile(r"book|appointment|slot|visit|schedule", re.IGNORECASE),
}
_CALL_BACK: Final = re.compile(r"call(?:ing)?\s?back|callback", re.IGNORECASE)
_HAND_OVER_WORDS: Final = re.compile(
    r"person|human|transfer|hand(?:ing)?\s?over|connect|manager|team member", re.IGNORECASE
)
#: An instruction that shrinks what the agent deals with to a list ("you only handle property
#: enquiries", "nothing else"): the business decides its agent's scope, never a test fix.
_NARROWS: Final = re.compile(
    r"\b(?:only|just|solely|exclusively)\s+(?:handle|handles|handling|deal|deals|dealing|help|"
    r"helps|answer|answers|talk|talks|discuss|discusses|cover|covers|take|takes)\b"
    r"|\bnothing else\b|\boutside (?:your|its|the agent's|their) (?:scope|role|remit)\b",
    re.IGNORECASE,
)
#: A `why` that reports an effect nobody has tested, or a restriction (founder, 27 Oct 2026:
#: "I have restricted the agent to only handling property enquiries").
_CLAIMED_EFFECT: Final = re.compile(
    r"\b(?:restrict\w*|forbid\w*|forbade|block(?:ed|s)?|disabl\w*|no longer)\b", re.IGNORECASE
)
#: A `why` written as the AI speaking ("I have", "we changed"): the owner reads a sentence
#: about their script, in the third person ("Asks the agent to ...").
_FIRST_PERSON: Final = re.compile(
    r"\bI\b|\bI'(?:m|ve|d|ll)\b|(?i:\b(?:me|my|we|we've|we're|we'll|our|us)\b)"
)
_CONTENT_WORD: Final = re.compile(r"[a-z]{4,}")
_NOT_CONTENT: Final = frozenset(
    {
        "agent",
        "caller",
        "callers",
        "call",
        "calls",
        "that",
        "this",
        "with",
        "they",
        "them",
        "their",
        "what",
        "when",
        "then",
        "than",
        "have",
        "from",
        "your",
        "will",
        "only",
        "just",
        "each",
        "more",
        "about",
        "before",
        "after",
        "never",
        "always",
        "into",
    }
)
#: A refusal that only limits HOW ("not until all ten are read back", "never on part of a
#: number") rather than WHETHER, unless it also reaches every case ("partial or full").
_ONLY_HOW: Final = re.compile(
    r"\b(?:until|before|unless|part of|fewer|less than|only after)\b", re.IGNORECASE
)
_EVERY_CASE: Final = re.compile(r"\b(?:full|any|every|at all|anything)\b", re.IGNORECASE)


def refuses(sentence: str) -> bool:
    """Does `sentence` refuse or forbid an act outright?"""
    if not _REFUSES.search(sentence):
        return False
    return not _ONLY_HOW.search(sentence) or bool(_EVERY_CASE.search(sentence))


def _content(text: str) -> set[str]:
    return {
        word.rstrip("s") for word in _CONTENT_WORD.findall(text.lower()) if word not in _NOT_CONTENT
    }


def _capabilities(brief: AgentBrief) -> list[tuple[str, re.Pattern[str]]]:
    """What this agent can do that a suggested fix may never take away, each with the words
    that name it. Taking a caller's number is every agent's."""
    out: list[tuple[str, re.Pattern[str]]] = [("taking a caller's number", _NUMBERS)]
    for kind, what in brief.actions:
        words = _ACTION_WORDS.get(kind)
        if words is not None:
            out.append((f"its {kind} action ({what[:60]})", words))
    if brief.call_backs:
        out.append(("call backs", _CALL_BACK))
    if brief.hand_over != "off":
        out.append(("hand-over to a person", _HAND_OVER_WORDS))
    return out


def stored_problem(edit: ScriptEdit, script: CallScript, *, where: str = "edit") -> str | None:
    """Why `edit` (made against `script`) is not a fix the owner may be offered, by the rules
    that need nothing but the edit: or None.

    Refused: a fix for a test a platform rule owns; a `why` that claims an effect or speaks
    as "I"/"we"; dropping the step's own sentences; refusing to take a number; narrowing what
    the agent handles. Each answer names the rule, never the client's words (hard rule 6:
    it is logged and sent back to the model)."""
    if edit.because in PLATFORM_RULE_TESTS:
        return (
            f"{where}: the test it fixes is one our platform rules decide, so it is ours to "
            "fix and never a script change"
        )
    if _CLAIMED_EFFECT.search(edit.why):
        return (
            f"{where}: `why` says what the change asks the agent to do; it is untested, so it "
            "never says it restricted, blocked or stopped anything"
        )
    if _FIRST_PERSON.search(edit.why):
        return (
            f'{where}: `why` is about the script, in the third person ("Asks the agent to '
            '..."), never "I" or "we"'
        )
    kept = kept_problem(edit, script, where=where)
    if kept is not None:
        return kept
    added = sentences(added_text(edit, script))
    for sentence in added:
        if refuses(sentence) and _NUMBERS.search(sentence):
            return f"{where}: refuses taking a caller's number, which every agent does"
        if _NARROWS.search(sentence):
            return (
                f"{where}: narrows what the agent handles; the business decides that, never a "
                "test fix"
            )
    return None


def offered_edits(improvement: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """A stored proposal's edits the owner may still be offered, and how many are withheld.

    Each edit is checked again against the script it was made from (`base_script`), so a
    proposal stored before a rule existed is never shown or applied as current. Edits are
    checked one by one against that base: each was made against the base, not against the
    edits before it."""
    base_raw = improvement.get("base_script")
    try:
        base = CallScript.model_validate(base_raw) if isinstance(base_raw, dict) else CallScript()
    except ValidationError:
        base = CallScript()
    offered: list[dict[str, Any]] = []
    withheld = 0
    for raw in improvement.get("edits") or []:
        if not isinstance(raw, dict):
            continue
        if stored_problem(ScriptEdit.of(raw), base) is not None:
            withheld += 1
            continue
        offered.append(raw)
    return offered, withheld


def grounding_problem(
    edit: ScriptEdit,
    script: CallScript,
    *,
    brief: AgentBrief,
    good_answer: str,
    where: str,
) -> str | None:
    """`stored_problem`, and what needs the agent and the test: refusing one of this agent's
    in-call actions, call backs or hand-over, or forbidding what the test's good answer has
    the agent do."""
    stored = stored_problem(edit, script, where=where)
    if stored is not None:
        return stored
    refusals = [s for s in sentences(added_text(edit, script)) if refuses(s)]
    for sentence in refusals:
        for name, words in _capabilities(brief):
            if words.search(sentence):
                return f"{where}: refuses {name}, which this agent does; never take it away"
    affirmed = _content(" ".join(s for s in sentences(good_answer) if not refuses(s)))
    for sentence in refusals:
        if _content(sentence) & affirmed:
            return f"{where}: forbids what the test's good answer has the agent do"
    return None


__all__ = ["grounding_problem", "offered_edits", "refuses", "stored_problem"]
