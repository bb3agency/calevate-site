"""Deterministic checks on what a script makes the agent say or promise (D-945).

The writer (`apps/workers/script_assist`) runs them on its own draft and gets one repair round,
as for the call rules (`call_rules.said_line_problem`); the readiness card shows what is left
on a published script with a button to fix it (`agents/readiness`). Code rather than prompt
text because a ban-list in a prompt can prime the very words it bans and every prompt
character is paid on every reply (`docs/research/reports/Sales call scripts and
generation.md`, "What the lints check").

Five checks:

* PROMOTIONAL OR URGENCY WORDS. Under TRAI's TCCCPR Second Amendment (Feb 2025) promotional
  content mixed into a service call makes the whole call promotional (secondary-legal reading
  in the same report). The lists are short and conservative on purpose: "free parking" or
  "we offer home delivery" is an ordinary fact, so bare "free" and "offer" are not on them.
  The Telugu and Hindi entries are loanwords as they are written in those scripts; they
  are detection terms, never lines the agent says, and wait for the founder's review.
* A PROMISE NOTHING ON THE ACCOUNT CAN KEEP: a WhatsApp send, a call back, a booking or a hand
  to a person that the capability manifest says this agent cannot do. A sentence that makes
  the action conditional ("only if you can") is left alone: the platform's WHAT YOU CAN DO
  block decides at call time.
* A FIGURE THE OWNER NEVER GAVE: digits, a rupee sign or a percentage in a spoken line that no
  fact holds.
* MORE THAN ONE QUESTION in one spoken line.
* ANOTHER PERSON'S NAME given as the agent's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from calevate_shared.call_script import CallScript

#: Promotional or urgency phrases, per language family, as data. Matched case-insensitively
#: on whole phrases.
PROMO_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "discount",
        "cashback",
        "cash back",
        "special offer",
        "limited offer",
        "limited period",
        "limited time",
        "offer ends",
        "only today",
        "today only",
        "last few units",
        "last few flats",
        "hurry",
        "best price",
        "lowest price",
        "guaranteed returns",
        "don't miss",
    ),
    "te": (
        "డిస్కౌంట్",
        "క్యాష్‌బ్యాక్",
        "క్యాష్ బ్యాక్",
        "స్పెషల్ ఆఫర్",
        "లిమిటెడ్ ఆఫర్",
        "బెస్ట్ ప్రైస్",
    ),
    "hi": (
        "डिस्काउंट",
        "कैशबैक",
        "स्पेशल ऑफर",
        "लिमिटेड ऑफर",
        "बेस्ट प्राइस",
        "सिर्फ आज",
    ),
}


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """What this agent can actually do on a call, read from the account (D-945), and where
    its leads come from. The writer is told it and never writes a promise outside it."""

    #: A calendar action is live on the agent, so it can find and book a real slot.
    booking_tool: bool = False
    #: A WhatsApp action is live on the agent, so it can send a message during the call.
    whatsapp: bool = False
    #: The account may keep a call back (not while it is a restricted trial).
    call_backs: bool = False
    #: The agent may hand a caller to a person on duty.
    hand_over: bool = False
    #: The team is alerted from the call (`team_alert_rules.in_call`).
    team_alerts: bool = False
    #: Where this account's leads come from (`leads.source`), most first.
    lead_sources: tuple[str, ...] = ()

    def brief_lines(self) -> str:
        """The manifest as the writer reads it."""
        can = [
            label
            for label, on in (
                ("book a time in the business's calendar", self.booking_tool),
                ("send a WhatsApp message", self.whatsapp),
                ("offer a call back", self.call_backs),
                ("hand the caller to a person on duty", self.hand_over),
                ("alert the team about the call", self.team_alerts),
            )
            if on
        ]
        cannot = [
            label
            for label, on in (
                ("book or confirm a time (the team confirms it)", self.booking_tool),
                ("send a WhatsApp or any message", self.whatsapp),
                ("offer a call back", self.call_backs),
                ("put the caller through to a person", self.hand_over),
            )
            if not on
        ]
        lines = ["What this agent can do on a call: " + ("; ".join(can) if can else "talk only")]
        if cannot:
            lines.append(
                "It can NOT: "
                + "; ".join(cannot)
                + ". Never write a line or step that promises these."
            )
        if self.lead_sources:
            lines.append("Where its leads come from: " + ", ".join(self.lead_sources))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class LintContext:
    """What a script is checked against."""

    language: str = ""
    manifest: CapabilityManifest | None = None
    #: Every fact the owner gave (profile, pinned and known facts, their answers), as one text.
    facts: str = ""
    agent_name: str = ""
    business_name: str = ""


def _family(language: str) -> str:
    return language.split("-")[0].strip().lower()


def _phrase(term: str) -> re.Pattern[str]:
    # Latin terms on word boundaries; Indic ones as substrings, whose word edges `\b` misreads.
    if term.isascii():
        return re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.IGNORECASE)
    return re.compile(re.escape(term))


_PROMO: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    family: tuple(_phrase(term) for term in terms) for family, terms in PROMO_TERMS.items()
}


def promo_term(text: str, language: str = "") -> str | None:
    """The first promotional or urgency phrase in `text`, or None. English is always
    checked, because a Telugu or Hindi line says these words in English as often as not."""
    for family in dict.fromkeys(("en", _family(language))):
        for pattern in _PROMO.get(family, ()):
            found = pattern.search(text)
            if found:
                return found.group(0)
    return None


#: A sentence that makes an action depend on what the agent can do; the platform decides.
_CONDITIONAL: Final = re.compile(
    r"\bonly if\b|\bif you (?:can|have)\b|\bunless\b|\bif (?:the|a) (?:tool|person|call back)",
    re.IGNORECASE,
)
#: A sentence that says the action will NOT happen ("I can't connect you now") promises nothing.
_NEGATED: Final = re.compile(
    r"\b(?:can'?t|cannot|won'?t|not|no one|nobody|never|unable)\b|కుదరదు|లేరు|లేదు|"
    r"చేయలేను|नहीं|कोई नहीं",
    re.IGNORECASE,
)
_WHATSAPP: Final = re.compile(r"whats\s?app|వాట్సాప్|వాట్సప్|व्हाट्सएप|व्हाट्सऐप", re.IGNORECASE)
_SENDS: Final = re.compile(r"\bsend|\bsent\b|\bshare|పంపి|పంపు|పంపా|షేర్|भेज|शेयर", re.IGNORECASE)
_CALL_BACK: Final = re.compile(
    r"call (?:you )?back|call-back|callback|తిరిగి కాల్|కాల్ బ్యాక్|वापस कॉल|कॉल बैक",
    re.IGNORECASE,
)
_BOOKS: Final = re.compile(
    r"\b(?:i(?:'ll| will)|let me|we(?:'ll| will)) (?:book|confirm|fix)\b|"
    r"బుక్ చేస్తాను|కన్ఫర్మ్ చేస్తాను|बुक कर (?:देत|दूँग|दूंग)",
    re.IGNORECASE,
)
_HANDS_OVER: Final = re.compile(
    r"\b(?:transfer|connect|put) you\b|\bput you through\b|కనెక్ట్ చేస్తాను|ట్రాన్స్‌ఫర్|"
    r"कनेक्ट कर|ट्रांसफर",
    re.IGNORECASE,
)


def unbacked_promise(text: str, manifest: CapabilityManifest) -> str | None:
    """What `text` promises that `manifest` says this agent cannot do, or None."""
    for sentence in re.split(r"(?<=[.?!।])\s+", text):
        if _CONDITIONAL.search(sentence) or _NEGATED.search(sentence):
            continue
        if not manifest.whatsapp and _WHATSAPP.search(sentence) and _SENDS.search(sentence):
            return "a WhatsApp message, and this agent has no WhatsApp action"
        if not manifest.call_backs and _CALL_BACK.search(sentence):
            return "a call back, and this account cannot keep one yet"
        if not manifest.booking_tool and _BOOKS.search(sentence):
            return "to book or confirm a time, and this agent has no calendar"
        if not manifest.hand_over and _HANDS_OVER.search(sentence):
            return "to put the caller through to a person, and hand-over is off"
    return None


_FIGURE: Final = re.compile(r"₹\s*[\d,]+|\d[\d,.]*\s*%|\d[\d,.]*")
_NON_DIGITS: Final = re.compile(r"[^\d]")


def unknown_figure(text: str, facts: str) -> str | None:
    """The first figure in `text` (digits, a rupee amount, a percentage) whose digits appear
    in no fact, or None."""
    known = {_NON_DIGITS.sub("", m.group(0)) for m in _FIGURE.finditer(facts)}
    for match in _FIGURE.finditer(text):
        digits = _NON_DIGITS.sub("", match.group(0))
        if digits and digits not in known:
            return match.group(0).strip()
    return None


def question_count(text: str) -> int:
    return text.count("?") + text.count("\uff1f")


#: Latin letters only: an agent name is configured in them, and its Telugu or Hindi spelling
#: cannot be compared with it without a transliteration we do not have.
_SELF_NAMED: Final = re.compile(r"\b(?:my name is|I am|I'm|this is) ([A-Z][a-z]+)\b")


def other_persona(text: str, *, agent_name: str, business_name: str) -> str | None:
    """A name the line gives as the agent's own that is not the configured agent name (nor
    the business's), or None. A line that names the agent's own name passes."""
    allowed = {agent_name.strip().casefold(), *business_name.casefold().split()}
    for match in _SELF_NAMED.finditer(text):
        name = match.group(1)
        if name.casefold() not in allowed:
            return name
    return None


def instruction_fields(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of every field that instructs the in-call model and is never heard.

    A step in "say" mode is said as written, so its instruction is a spoken line. A step's
    name, an objection's caller side, the facts and the legacy `steps` are not here: the
    first two are the caller's words or the owner's label, and the AI writes none of the rest
    as instructions."""
    fields = [
        ("business_line", script.business_line),
        ("identity", script.identity),
        ("goal", script.goal),
        ("outbound_purpose", script.outbound_purpose),
        ("style.tone", script.style.tone),
        ("style.address_form", script.style.address_form),
        ("ending", script.ending),
    ]
    fields += [(f"objections.{i}.response", o.response) for i, o in enumerate(script.objections)]
    for i, stage in enumerate(script.stages):
        if stage.mode == "guide":
            fields.append((f"stages.{i}.instruction", stage.instruction))
        fields += [(f"stages.{i}.branches.{j}.when", b.when) for j, b in enumerate(stage.branches)]
        for j, step in enumerate(stage.procedure):
            fields.append((f"stages.{i}.procedure.{j}.action", step.action))
            fields.append((f"stages.{i}.procedure.{j}.wait_for", step.wait_for))
    return fields


def spoken_fields(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of every line the agent says, or that shows how a caller sounds."""
    fields = [
        ("opening_line", script.opening_line),
        ("outbound_opening_line", script.outbound_opening_line),
    ]
    for i, stage in enumerate(script.stages):
        fields.append((f"stages.{i}.sounds_like", stage.sounds_like))
        if stage.mode == "say":
            fields.append((f"stages.{i}.instruction", stage.instruction))
    fields += [(f"style.sample_phrases.{i}", p) for i, p in enumerate(script.style.sample_phrases)]
    fields += [
        (f"example_exchange.{i}.text", e.text) for i, e in enumerate(script.example_exchange)
    ]
    return fields


def caller_paths(script: CallScript) -> frozenset[str]:
    """The example lines that are the caller's, never the agent's to keep."""
    return frozenset(
        f"example_exchange.{i}.text"
        for i, line in enumerate(script.example_exchange)
        if line.speaker == "caller"
    )


def script_problems(script: CallScript, context: LintContext) -> list[str]:
    """Every lint finding on a whole script, spoken lines first. A raw (hand-written) script
    has no fields to walk and is checked as one instruction text."""
    if script.raw_override:
        return instruction_problems("script", script.raw_override, context)
    callers = caller_paths(script)
    found = [
        problem
        for path, text in spoken_fields(script)
        if text.strip() and path not in callers
        for problem in spoken_line_problems(path, text, context)
    ]
    found += [
        problem
        for path, text in instruction_fields(script)
        if text.strip()
        for problem in instruction_problems(path, text, context)
    ]
    return found


_PLACES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^outbound_opening_line"), "The opening on calls it makes"),
    (re.compile(r"^opening_line"), "The opening line"),
    (re.compile(r"^stages\.(\d+)\."), "Step {n}"),
    (re.compile(r"^objections\.(\d+)\."), "Push-back answer {n}"),
    (re.compile(r"^example_exchange\.\d+\."), "The example call"),
    (re.compile(r"^style\.sample_phrases\.\d+"), "A sample phrase"),
    (re.compile(r"^style\."), "How it speaks"),
    (re.compile(r"^script$"), "The script"),
)


def plain(problem: str) -> str:
    """A finding with its field path in the owner's words ("Step 2: says ..."), for the
    client screens; the writer reads the path itself."""
    where, sep, rest = problem.partition(": ")
    if not sep:
        return problem
    for pattern, label in _PLACES:
        found = pattern.match(where)
        if found:
            number = int(found.group(1)) + 1 if found.groups() else 0
            return f"{label.format(n=number)}: {rest}"
    return f"{where.split('.')[0].replace('_', ' ').capitalize()}: {rest}"


def spoken_line_problems(where: str, text: str, context: LintContext) -> list[str]:
    """What the lint finds in one line the agent says."""
    problems: list[str] = []
    promo = promo_term(text, context.language)
    if promo:
        problems.append(
            f'{where}: says "{promo}", which makes the call promotional; say only facts '
            "the caller asked about, with no offer, discount or urgency."
        )
    if context.manifest is not None:
        promise = unbacked_promise(text, context.manifest)
        if promise:
            problems.append(f"{where}: promises {promise}; take the details for the team.")
    figure = unknown_figure(text, context.facts)
    if figure:
        problems.append(
            f'{where}: says "{figure}", a figure no fact of the owner gives; leave it out.'
        )
    if question_count(text) > 1:
        problems.append(f"{where}: asks {question_count(text)} questions; ask one and wait.")
    if context.agent_name.strip():
        other = other_persona(
            text, agent_name=context.agent_name, business_name=context.business_name
        )
        if other:
            problems.append(
                f'{where}: calls the agent "{other}"; its name is {context.agent_name.strip()}.'
            )
    return problems


def instruction_problems(where: str, text: str, context: LintContext) -> list[str]:
    """What the lint finds in an instruction the agent follows but never says: a promise
    outside the manifest, or a promotional or urgency term."""
    problems: list[str] = []
    promo = promo_term(text, context.language)
    if promo:
        problems.append(f'{where}: tells the agent to use "{promo}"; no offers or urgency.')
    if context.manifest is not None:
        promise = unbacked_promise(text, context.manifest)
        if promise:
            problems.append(f"{where}: has the agent promise {promise}.")
    return problems


__all__ = [
    "PROMO_TERMS",
    "CapabilityManifest",
    "LintContext",
    "caller_paths",
    "instruction_fields",
    "instruction_problems",
    "other_persona",
    "plain",
    "promo_term",
    "question_count",
    "script_problems",
    "spoken_fields",
    "spoken_line_problems",
    "unbacked_promise",
    "unknown_figure",
]
