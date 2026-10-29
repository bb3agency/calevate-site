"""Deterministic checks on what a script makes the agent say or promise (D-945).

The writer (`apps/workers/script_assist`) runs them on its own draft and gets one repair round,
as for the call rules (`call_rules.said_line_problem`); the readiness card shows what is left
on a published script with a button to fix it (`agents/readiness`). Code rather than prompt
text because a ban-list in a prompt can prime the very words it bans and every prompt
character is paid on every reply (`docs/research/reports/Sales call scripts and
generation.md`, "What the lints check").

Five checks:

* PROMOTIONAL OR URGENCY WORDS, read by the D-943 promo check
  (`compliance.call_purpose.first_finding`): one word list in English, Telugu and Hindi,
  with its negation and everyday-sense guards ("free parking", "we offer home delivery"),
  shared with the put-live warning and the campaign launch block. A second list here
  would drift from the one that blocks a launch.
* A PROMISE NOTHING ON THE ACCOUNT CAN KEEP: a WhatsApp send, a call back, a booking or a hand
  to a person that the capability manifest says this agent cannot do, and an SMS on every
  account, since the platform sends none (messaging is WhatsApp only, D-700). A sentence that makes
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

from apps.api.compliance.call_purpose import Finding, first_finding


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
                # Never on: the platform sends no SMS (D-700).
                ("send an SMS", False),
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

    manifest: CapabilityManifest | None = None
    #: Every fact the owner gave (profile, pinned and known facts, their answers), as one text.
    facts: str = ""
    agent_name: str = ""
    business_name: str = ""
    #: False where the D-943 promo warning already shows the promotional wording beside this
    #: lint (the put-live dialog), so the owner reads one promotional warning, not two.
    promo: bool = True


def _promo(text: str, context: LintContext) -> Finding | None:
    return first_finding(text) if context.promo else None


#: A sentence that makes an action depend on what the agent can do; the platform decides.
_CONDITIONAL: Final = re.compile(
    r"\bonly if\b|\bif you (?:can|have)\b|\bunless\b|\bif (?:the|a) (?:tool|person|call back)",
    re.IGNORECASE,
)
#: A clause that says the action will NOT happen ("I can't connect you now") promises nothing.
#: The romanised Telugu forms are the negative verb endings ("pampinchalemu", "cheyalenu").
_NEGATED: Final = re.compile(
    r"\b(?:can'?t|cannot|won'?t|not|no one|nobody|never|unable)\b|కుదరదు|లేరు|లేదు|"
    r"చేయలేను|नहीं|कोई नहीं|\b\w+(?:lemu|lenu|ledu)\b|\bkudaradu\b|\bnahi?n?\b",
    re.IGNORECASE,
)
#: Where one clause ends and the next begins. A negation is read only in the promise's own
#: clause, so "ఇబ్బంది లేదు, WhatsApp lo pampistanu" ("no problem, I'll send it") still
#: promises the send.
_CLAUSE_BREAK: Final = re.compile(
    r"\s*[,;:\N{EN DASH}\N{EM DASH}]\s*|\s+(?:and|but|so|kani|ani|lekapothe|par|lekin|aur|toh)\s+",
    re.IGNORECASE,
)
_WHATSAPP: Final = re.compile(r"whats\s?app|వాట్సాప్|వాట్సప్|व्हाट्सएप|व्हाट्सऐप", re.IGNORECASE)
#: Each verb also in the Latin-letter Telugu and Hindi that scripts are written in as often as
#: the native scripts ("WhatsApp lo pampistanu", "bhej dunga").
_SENDS: Final = re.compile(
    r"\bsend|\bsent\b|\bshare|\bpamp(?:i|u)|\bbhej|పంపి|పంపు|పంపా|షేర్|भेज|शेयर", re.IGNORECASE
)
_SMS: Final = re.compile(r"\bsms\b|\btext message|ఎస్ఎంఎస్|एसएमएस", re.IGNORECASE)
_CALL_BACK: Final = re.compile(
    r"call (?:you )?back|call-back|callback|తిరిగి కాల్|కాల్ బ్యాక్|మళ్ళీ కాల్|वापस कॉल|कॉल बैक|"
    r"\b(?:malli|tirigi|tarvata|taruvata) call chest|\b(?:wapas|vapas|baad mein) call kar",
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
        # A condition qualifies the whole sentence ("only if you can, offer a call back").
        if _CONDITIONAL.search(sentence):
            continue
        clauses = [c for c in _CLAUSE_BREAK.split(sentence) if c]

        def promised(verb: re.Pattern[str], clauses: list[str] = clauses) -> bool:
            """The verb in a clause that does not itself say it will not happen."""
            return any(verb.search(c) and not _NEGATED.search(c) for c in clauses)

        # No manifest backs an SMS: the platform sends none, its messaging is WhatsApp only
        # (D-700, docs/FOLLOW-UPS.md). Read in the verb's own clause, so "can't send it on
        # WhatsApp, but I'll share it by SMS" is the SMS promise it is.
        if any(_SMS.search(c) and _SENDS.search(c) and not _NEGATED.search(c) for c in clauses):
            return "an SMS, and this platform sends no SMS"
        # The channel may sit in another clause than the verb ("I'll send the brochure and
        # the location on WhatsApp"), so it is looked for in the whole sentence.
        if not manifest.whatsapp and _WHATSAPP.search(sentence) and promised(_SENDS):
            return "a WhatsApp message, and this agent has no WhatsApp action"
        if not manifest.call_backs and promised(_CALL_BACK):
            return "a call back, and this account cannot keep one yet"
        if not manifest.booking_tool and promised(_BOOKS):
            return "to book or confirm a time, and this agent has no calendar"
        if not manifest.hand_over and promised(_HANDS_OVER):
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
    promo = _promo(text, context)
    if promo:
        effect = (
            "which makes the call promotional"
            if promo.severity == "strong"
            else "which can read as promotional"
        )
        problems.append(
            f'{where}: says "{promo.phrase}", {effect}; say only facts the caller asked '
            "about, with no offer, discount or urgency."
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
    promo = _promo(text, context)
    if promo:
        problems.append(f'{where}: tells the agent to use "{promo.phrase}"; no offers or urgency.')
    if context.manifest is not None:
        promise = unbacked_promise(text, context.manifest)
        if promise:
            problems.append(f"{where}: has the agent promise {promise}.")
    return problems


__all__ = [
    "CapabilityManifest",
    "LintContext",
    "caller_paths",
    "instruction_fields",
    "instruction_problems",
    "other_persona",
    "plain",
    "question_count",
    "script_problems",
    "spoken_fields",
    "spoken_line_problems",
    "unbacked_promise",
    "unknown_figure",
]
