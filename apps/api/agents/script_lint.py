"""Deterministic checks on what a script makes the agent say or promise (D-945).

The writer (`apps/workers/script_assist`) runs them on its own draft and gets one repair round,
as for the call rules (`call_rules.said_line_problem`); the readiness card shows what is left
on a published script with a button to fix it (`agents/readiness`). Code rather than prompt
text because a ban-list in a prompt can prime the very words it bans and every prompt
character is paid on every reply (`docs/research/reports/Sales call scripts and
generation.md`, "What the lints check").

The checks:

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
* A PLACED CALL'S OPENING without the person's name, or asking nothing
  (`call_rules.OPENING_LINE_RULE`).
* AN OPENING THAT DOES NOT READ WITHOUT THE PERSON'S NAME (`name_segment_problem`).
* A STEP THAT GIVES SEVERAL ACTIONS AT ONCE instead of its step-by-step list.
* A DETAIL TO COLLECT that no step asks (whole script only: it needs the agent's lead details).
* The call's shape (whole script, `flow_problems`): a step kept with a placeholder for its
  instruction, a question about using something asked before or right after the caller sets
  it up, and the same explanation in two steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from calevate_shared.call_script import CallScript, ConversationStage, extract_variable_names
from calevate_shared.call_words import extend as _extend
from calevate_shared.engine import NAME_VARIABLE

from apps.api.compliance.call_purpose import Finding, first_finding

#: The merge field the dial fills with the person's name (`call_script.STANDARD_VARIABLES`); a
#: dial with no name drops it with its title (`call_script.fill_spoken_line`), so a line written
#: as `name_segment_problem` asks still reads. Here rather than in `call_rules`, which imports
#: this module.
NAME_FIELD: Final = f"{{{{{NAME_VARIABLE}}}}}"

#: How the name sits in an opening so the line reads on the many calls placed without one
#: (`name_segment_problem`), as every writer of an opening is told it.
NAME_PLACEMENT_RULE: Final = (
    f"put {NAME_FIELD} right after the greeting, then its title if the language uses one, "
    "then a comma; on a call with no name the two are left out together, so the rest must "
    "read without them"
)

#: What an outbound agent's opening line holds, as the brief tells every writer of it.
PLACED_OPENING_BRIEF: Final = (
    "Its opening line is said on calls it places: greet the person by name with "
    f"{NAME_FIELD} ({NAME_PLACEMENT_RULE}), say who is calling and why in one short "
    "sentence, then ask only whether they can talk now."
)


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
    #: The agent's calling direction (`agents.direction`): an outbound agent's opening line is
    #: said on calls it places. Empty when unread, and then no opening is judged as one.
    direction: str = ""

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
        if self.direction == "outbound":
            # Every writer that reads the brief (a whole script, one opening line) is held to
            # `placed_opening_problem` on this agent's opening, so each is told it here.
            lines.append(PLACED_OPENING_BRIEF)
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
    #: The labels of the lead details the agent collects (`script_builder.collect_fields`),
    #: each of which some step should ask.
    collect: tuple[str, ...] = ()


def _promo(text: str, context: LintContext) -> Finding | None:
    return first_finding(text) if context.promo else None


#: A sentence that makes an action depend on what the agent can do; the platform decides.
_CONDITIONAL: Final = re.compile(
    r"\bonly if\b|\bif you (?:can|have)\b|\bunless\b|\bif (?:the|a) (?:tool|person|call back)",
    re.IGNORECASE,
)
#: A clause that says the action will NOT happen ("I can't connect you now") promises nothing.
#: The romanised Telugu forms are the negative verb endings ("pampinchalemu", "cheyalenu").
#: Every Indian-language alternative below is the founder's (`call_words.json`); the English
#: stays here.
_NEGATED: Final = re.compile(
    _extend(r"\b(?:can'?t|cannot|won'?t|not|no one|nobody|never|unable)\b", "script_lint._NEGATED"),
    re.IGNORECASE,
)
#: Where one clause ends and the next begins. A negation is read only in the promise's own
#: clause, so "ఇబ్బంది లేదు, WhatsApp lo pampistanu" ("no problem, I'll send it") still
#: promises the send.
_CLAUSE_BREAK: Final = re.compile(
    r"\s*[,;:\N{EN DASH}\N{EM DASH}]\s*|\s+(?:"
    + _extend("and|but|so", "script_lint._CLAUSE_BREAK")
    + r")\s+",
    re.IGNORECASE,
)
_WHATSAPP: Final = re.compile(_extend(r"whats\s?app", "script_lint._WHATSAPP"), re.IGNORECASE)
#: Each verb also in the Latin-letter Telugu and Hindi that scripts are written in as often as
#: the native scripts ("WhatsApp lo pampistanu", "bhej dunga").
_SENDS: Final = re.compile(_extend(r"\bsend|\bsent\b|\bshare", "script_lint._SENDS"), re.IGNORECASE)
_SMS: Final = re.compile(_extend(r"\bsms\b|\btext message", "script_lint._SMS"), re.IGNORECASE)
_CALL_BACK: Final = re.compile(
    _extend(r"call (?:you )?back|call-back|callback", "script_lint._CALL_BACK"),
    re.IGNORECASE,
)
_BOOKS: Final = re.compile(
    _extend(
        r"\b(?:i(?:'ll| will)|let me|we(?:'ll| will)) (?:book|confirm|fix)\b", "script_lint._BOOKS"
    ),
    re.IGNORECASE,
)
_HANDS_OVER: Final = re.compile(
    _extend(r"\b(?:transfer|connect|put) you\b|\bput you through\b", "script_lint._HANDS_OVER"),
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


def placed_call_opening(where: str, context: LintContext) -> bool:
    """Whether the line at `where` is said first on a call the agent places."""
    if where == "outbound_opening_line":
        return True
    return (
        where == "opening_line"
        and context.manifest is not None
        and context.manifest.direction == "outbound"
    )


#: The lines said word for word as the first words of a call.
_OPENING_FIELDS: Final = frozenset({"opening_line", "outbound_opening_line"})


def answered_opening(where: str, context: LintContext) -> bool:
    """Whether the line at `where` is said first on calls the agent answers, where the
    calling system fills it: an answering or "both" agent's opening_line. An unread direction
    counts as placed, the rule that lets a title stand beside the name."""
    return (
        where == "opening_line"
        and context.manifest is not None
        and context.manifest.direction in ("inbound", "both")
    )


def placed_opening_problem(where: str, text: str) -> str | None:
    """What a placed call's opening misses: the person's name, or a question that hands them
    the turn. Any merge field whose key names a name counts (`{{lead_name}}`, a list's
    `{{name}}` column, D-905). Whether the question asks if they can talk now is left to the
    writer's rule: no word list covers every call language."""
    if not any("name" in key for key in extract_variable_names(text)):
        return (
            f"{where}: does not say the person's name; start with {NAME_FIELD}, then who is "
            "calling and why, then ask if they can talk now."
        )
    if question_count(text) == 0:
        return (
            f"{where}: asks nothing; end by asking if they can talk now, before any question "
            "about the business."
        )
    return None


#: A numbered list ("1. open the app 2. tap ...") inside one step's instruction.
_NUMBERED_ITEM: Final = re.compile(r"(?:^|\s)(?:\d{1,2}[.)]|step \d{1,2}\b)", re.IGNORECASE)
#: What a caller does on their own phone. Counted rather than "then": the agent's own sequence
#: ("read back the time, then close") is one turn of its own and is right as it is.
_CALLER_ACTION: Final = re.compile(
    r"\b(?:open|tap|press|click|type|select|choose|scroll|swipe|install|download|enter|"
    r"go to|log in|sign in)\b",
    re.IGNORECASE,
)
_STAGE_INSTRUCTION: Final = re.compile(r"^stages\.\d+\.instruction$")


def stacked_actions(text: str) -> bool:
    """Whether one instruction gives the caller several things to do on their phone at once:
    a numbered list, or two or more of those actions."""
    return len(_NUMBERED_ITEM.findall(text)) >= 2 or len(_CALLER_ACTION.findall(text)) >= 2


#: Words of a lead detail's label that say nothing about which detail it is.
_GENERIC_WORDS: Final = frozenset(
    {
        "the", "and", "for", "any", "are", "was", "has", "have", "with", "what", "which",
        "their", "your", "they", "them", "from", "about", "does", "did", "not", "yes",
        "caller", "customer", "person", "lead", "details", "detail", "other",
    }
)  # fmt: skip
_WORD: Final = re.compile(r"[A-Za-z]+")
#: Long enough to tell details apart, short enough that "satisfied" meets "Satisfaction".
_STEM: Final = 5


def _stems(text: str) -> set[str]:
    return {
        word.casefold()[:_STEM]
        for word in _WORD.findall(text)
        if len(word) >= 3 and word.casefold() not in _GENERIC_WORDS
    }


def unasked_details(script: CallScript, collect: tuple[str, ...]) -> list[str]:
    """The labels in `collect` that no step asks for, in their order.

    A step asks for a detail when its `collect` names it, or when its name, instruction and
    step-by-step list carry at least half of the label's words (their first five letters, so
    word forms meet). A label with no English-letter word cannot be compared with English
    instructions and is never reported."""
    steps = [
        (
            {c.casefold() for c in stage.collect},
            _stems(" ".join([stage.name, stage.instruction, *(p.action for p in stage.procedure)])),
        )
        for stage in script.stages
    ]
    missing: list[str] = []
    for label in collect:
        wanted = _stems(label)
        if not wanted:
            continue
        need = (len(wanted) + 1) // 2
        if not any(
            label.casefold() in named or len(wanted & said) >= need for named, said in steps
        ):
            missing.append(label)
    return missing


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
    found += flow_problems(script)
    # With no steps there is nowhere to ask; the details list still reaches the call.
    if script.stages:
        found += [
            f'script: no step asks for "{label}"; ask it in the step where the call reaches '
            "it, as one question."
            for label in unasked_details(script, context.collect)
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
    if placed_call_opening(where, context):
        opening = placed_opening_problem(where, text)
        if opening:
            problems.append(opening)
    if where in _OPENING_FIELDS:
        nameless = name_segment_problem(where, text, placed=not answered_opening(where, context))
        if nameless:
            problems.append(nameless)
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
    if _STAGE_INSTRUCTION.match(where) and stacked_actions(text):
        problems.append(
            f"{where}: gives several actions in one go; put each in the step's step-by-step "
            "list, so the agent says one and waits until it is done."
        )
    return problems


#: A merge field that holds a person's name (`{{lead_name}}`, a list's `{{name}}` column), the
#: same test `placed_opening_problem` uses.
_NAME_MERGE_FIELD: Final = re.compile(r"\{\{\s*(\w*name\w*)\s*\}\}")
#: What may follow the name in a placed call's opening: its title, if the language puts one
#: after a name, then a break the line can stand on without both (`call_script.
#: fill_spoken_line` leaves the two out together). Not "?": "is this {{lead_name}}?" has no
#: question left without the name.
_PLACED_NAME_TAIL: Final = re.compile(r"(?:[ \t]+[^\s,.!?।{}]+)?[ \t]*[,.!।]")
#: What must follow it on a call the agent answers: the calling system fills the greeting
#: there and leaves out only the field, so a word after it would be said alone.
_ANSWERED_NAME_TAIL: Final = re.compile(r"[ \t]*[,.!।]")
_CLAUSE_END: Final = re.compile(r"[,.!?।]")
#: Words before the name in its clause: a greeting ("Hello", "Good morning") is the most a
#: clause can keep and still read once the name is left out of it.
_WORDS_BEFORE_NAME: Final = 2


def name_segment_problem(where: str, text: str, *, placed: bool) -> str | None:
    """Whether an opening still reads on a call with no name for the person, or None.

    Placing a call with no name is ordinary (a list of numbers, a test call, a call from a
    number alone), and the calling system has no "if the name is known" of its own: an
    unfilled field is left out and the rest spoken (snapshots/2026-10-29/pages/channels/
    voice-campaigns.md:201-205). On a call we place, the opening is filled by us and the
    name's title goes with it; on one the agent answers, only the field goes. Language-free:
    it reads the punctuation around the field, never the words."""
    for match in _NAME_MERGE_FIELD.finditer(text):
        tail = (_PLACED_NAME_TAIL if placed else _ANSWERED_NAME_TAIL).match(text, match.end())
        clause = _CLAUSE_END.split(text[: match.start()])[-1].split()
        if placed and (tail is None or len(clause) > _WORDS_BEFORE_NAME):
            return f"{where}: does not read when the name is unknown; {NAME_PLACEMENT_RULE}."
        if not placed and tail is None:
            return (
                f"{where}: on calls it answers only the name is left out when it is unknown, "
                f"so put a comma straight after {NAME_FIELD}, with no title after it."
            )
    return None


#: An instruction that only says the step is not wanted, as a model writes it when it means
#: to drop a step it was told to keep the shape of ("Not needed.", "N/A", "-"). English
#: only: instructions are written in English (`english_problem`).
_PLACEHOLDER: Final = re.compile(
    r"^(?:this )?(?:step )?(?:is )?(?:not (?:needed|used|required|applicable)|"
    r"no longer (?:needed|used|required)|unused|removed|deleted|delete|remove|skip(?:ped)?|"
    r"omit(?:ted)?|n ?a|none|nil|tbd|todo|blank|empty)(?: any ?more)?$"
)


def placeholder_instruction(text: str) -> bool:
    """Whether a step's instruction holds nothing for the agent to do: no letter at all, or
    only words saying the step is not wanted. A line in another script is never one."""
    if not any(ch.isalpha() for ch in text):
        return True
    if any(ch.isalpha() and not ch.isascii() for ch in text):
        return False
    return bool(_PLACEHOLDER.match(" ".join(re.findall(r"[a-z]+", text.casefold()))))


def placeholder_problems(script: CallScript) -> list[str]:
    """A step kept with a placeholder for its instruction. The last step is the close: it is
    never taken out, so it must say how the call ends."""
    last = len(script.stages) - 1
    return [
        f'stages.{i}.instruction: says only "{stage.instruction.strip()}"; '
        + (
            "this is the close, so write how the call ends, with a short thank-you line."
            if i == last
            else "take the step out of stages and point the ways to it at the step after "
            "it, or, if it is for some callers only, write what it does and reach it "
            "through a way out whose condition says who."
        )
        for i, stage in enumerate(script.stages)
        if placeholder_instruction(stage.instruction)
    ]


def _successors(script: CallScript, index: int) -> set[str]:
    """The steps the call can go to from step `index`: its ways out, else the next step."""
    stage = script.stages[index]
    out = {branch.target for branch in stage.branches}
    if stage.otherwise:
        out.add(stage.otherwise)
    elif index + 1 < len(script.stages):
        out.add(script.stages[index + 1].id)
    return out


def _reachable(script: CallScript, start: int) -> set[int]:
    """Every step the call can reach after step `start`."""
    at = {stage.id: i for i, stage in enumerate(script.stages)}
    seen: set[int] = set()
    todo = [start]
    while todo:
        for target in _successors(script, todo.pop()):
            i = at.get(target)
            if i is not None and i not in seen:
                seen.add(i)
                todo.append(i)
    return seen


#: Something the caller sets up during the call. Read in the English instructions only.
_SETS_UP: Final = re.compile(
    r"\b(?:install|set(?:ting)? (?:it |them )?up|setup|download|sign(?:ing)? up|register|"
    r"activat|creat\w* (?:an |a |their |the )?account)",
    re.IGNORECASE,
)
_HELPS: Final = re.compile(r"\b(?:help|guide|walk|show|assist|support|take them through)", re.I)
#: Asking how the caller uses or likes something, which needs them to have used it.
_ASKS_EXPERIENCE: Final = re.compile(
    r"\b(?:satisf\w*|experience with|feedback|suggestions|improvements?|"
    r"how (?:they|you) (?:like|find|feel about)|purpose of us\w*|"
    r"what (?:they|you) (?:are )?(?:use|using)\b|(?:use|using) (?:it|the \w+) for\b|"
    r"how (?:often|much) (?:they|you) use)",
    re.IGNORECASE,
)


def _stage_text(stage: ConversationStage) -> str:
    return " ".join([stage.name, stage.instruction, *(p.action for p in stage.procedure)])


def _sets_up(stage: ConversationStage) -> bool:
    text = _stage_text(stage)
    return bool(_SETS_UP.search(text)) and (bool(stage.procedure) or bool(_HELPS.search(text)))


def _asks_experience(stage: ConversationStage) -> bool:
    return bool(_ASKS_EXPERIENCE.search(f"{stage.name} {stage.instruction}"))


def order_problems(script: CallScript) -> list[str]:
    """A step that asks how the caller uses or likes something, on a path of the call that
    also helps them set it up: before it, they do not have it yet; right after it, they have
    not used it. Either way the question cannot be answered on that call (the Rytu Khata
    call of 6 Nov 2026: "I only just installed it, how would I be using it?")."""
    setup = [i for i, stage in enumerate(script.stages) if _sets_up(stage)]
    problems: list[str] = []
    for i, stage in enumerate(script.stages):
        if not _asks_experience(stage) or _sets_up(stage):
            continue
        reach = _reachable(script, i)
        before = next((s for s in setup if s in reach), None)
        after = next((s for s in setup if i in _reachable(script, s)), None)
        if before is None and after is None:
            continue
        when = (
            f"before step {before + 1} helps them set it up"
            if before is not None
            else f"right after step {(after or 0) + 1} helps them set it up"
        )
        problems.append(
            f"stages.{i}.instruction: asks how the caller uses or likes it, and the call can "
            f"reach it {when}, when they cannot answer it; ask it only on the way for callers "
            "who already had it, and after setting it up show them the first thing to do."
        )
    return problems


#: Punctuation stripped from a word's ends: ASCII, the danda, curly quotes and dashes.
_TOKEN_EDGE: Final = (
    ".,!?;:\"'()\N{DEVANAGARI DANDA}\N{LEFT SINGLE QUOTATION MARK}"
    "\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT DOUBLE QUOTATION MARK}"
    "\N{RIGHT DOUBLE QUOTATION MARK}\N{EN DASH}\N{EM DASH}-"
)
#: Words a line needs before two lines can be called the same thing said twice.
_MIN_REPEAT_WORDS: Final = 5
#: Share of their words two lines have in common (of all the words either uses).
_REPEAT_OVERLAP: Final = 0.6


def _words(text: str) -> frozenset[str]:
    plain_text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    return frozenset(
        word for token in plain_text.split() if (word := token.strip(_TOKEN_EDGE).casefold())
    )


def _place(path: str) -> str:
    """Where a path is, in the owner's words ("step 2", "the opening line")."""
    label = plain(f"{path}: -").removesuffix(": -")
    return label if label.startswith("Step") else label[0].lower() + label[1:]


def repeated_line_problems(script: CallScript) -> list[str]:
    """A step whose example line says nearly what the opening or an earlier step's line says.
    Read by shared words, so it works in any language: each thing is explained once, and a
    caller who asks again hears the next thing, not the same description."""
    lines = [
        (path, text)
        for path, text in (
            ("opening_line", script.opening_line),
            ("outbound_opening_line", script.outbound_opening_line),
            *(
                (
                    f"stages.{i}.{'instruction' if s.mode == 'say' else 'sounds_like'}",
                    s.instruction if s.mode == "say" else s.sounds_like,
                )
                for i, s in enumerate(script.stages)
            ),
        )
        if len(_words(text)) >= _MIN_REPEAT_WORDS
    ]
    problems: list[str] = []
    for later, (path, text) in enumerate(lines):
        words = _words(text)
        for earlier_path, earlier in lines[:later]:
            other = _words(earlier)
            if len(words & other) / len(words | other) >= _REPEAT_OVERLAP:
                problems.append(
                    f"{path}: says nearly what {_place(earlier_path)} says; explain each "
                    "thing in one step, and have this step move the call on (answer what "
                    "they asked, or the next thing to do)."
                )
                break
    return problems


def flow_problems(script: CallScript) -> list[str]:
    """What the whole call's shape gets wrong: a placeholder step, a question asked before
    the caller can answer it, the same thing said twice."""
    return [
        *placeholder_problems(script),
        *order_problems(script),
        *repeated_line_problems(script),
    ]


__all__ = [
    "NAME_FIELD",
    "NAME_PLACEMENT_RULE",
    "PLACED_OPENING_BRIEF",
    "CapabilityManifest",
    "LintContext",
    "answered_opening",
    "caller_paths",
    "flow_problems",
    "instruction_fields",
    "instruction_problems",
    "name_segment_problem",
    "order_problems",
    "other_persona",
    "placed_call_opening",
    "placed_opening_problem",
    "placeholder_instruction",
    "placeholder_problems",
    "plain",
    "question_count",
    "repeated_line_problems",
    "script_problems",
    "spoken_fields",
    "spoken_line_problems",
    "stacked_actions",
    "unasked_details",
    "unbacked_promise",
    "unknown_figure",
]
