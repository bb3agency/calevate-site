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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_STAGE_BRANCHES,
    CallScript,
    ConversationStage,
    StageBranch,
    extract_variable_names,
    says_instruction,
    stage_steps,
)
from calevate_shared.call_words import LivePattern as _LivePattern
from calevate_shared.call_words import extend as _extend
from calevate_shared.engine import NAME_VARIABLE
from calevate_shared.spoken_guard import (
    empty_title,
    has_indic_letters,
    own_script_problem,
    reads_as_romanised,
)

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
    f"{NAME_FIELD} ({NAME_PLACEMENT_RULE}), say who is calling and from which business, "
    "then why this person is called (what they did that led to the call, never the task for "
    "the call), then ask only whether they can talk now."
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


#: What an owner's "Never" rule forbids, as far as a script line can show it (W3.9).
OwnerRuleKind = Literal[
    "call_back_time",
    "call_back",
    "discount",
    "price",
    "refund",
    "guarantee",
    "booking",
    "whatsapp",
]


@dataclass(frozen=True, slots=True)
class OwnerRule:
    """One owner rule: their words, verbatim, and what it forbids; `kind` is None for a rule no
    code check can see, which still reaches the practice judge as words."""

    words: str
    kind: OwnerRuleKind | None = None


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
    #: The labels of the lead details the script's job collects (a campaign's or a line's
    #: "What it notes"; none for an agent's own script), each of which some step should ask.
    collect: tuple[str, ...] = ()
    #: Those of `collect` a call back takes (the time and another number,
    #: `script_builder.CALL_BACK_KEYS`), noted on the step that asks for a later time.
    call_back: tuple[str, ...] = ()
    #: The labels of the job's details judged from the whole call (`extraction.
    #: whole_call_detail`), which the post-call pipeline writes and no step may ask.
    judged: tuple[str, ...] = ()
    #: The agent's call language, against which a line in English letters is found (D-861).
    #: Empty skips that check.
    language: str = ""
    #: The script is said on calls the agent places, so its steps need the ways out every
    #: placed call does (`script_assist.way_out_problems`).
    places_calls: bool = False
    #: What the agent says on a call outside the script, word for word: its AI and recording
    #: sentences where they are switched on. Names in them need the script's pronunciations.
    spoken_elsewhere: tuple[str, ...] = ()
    #: The owner's "Never ..." rules among the pinned facts (`owner_prohibitions`), each in
    #: the owner's own words, which no line of the script may break (W3.9).
    owner_rules: tuple[OwnerRule, ...] = ()


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
_NEGATED: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:can'?t|cannot|won'?t|not|no one|nobody|never|unable)\b", "script_lint._NEGATED"
    ),
    re.IGNORECASE,
)
#: Where one clause ends and the next begins. A negation is read only in the promise's own
#: clause, so "ఇబ్బంది లేదు, WhatsApp lo pampistanu" ("no problem, I'll send it") still
#: promises the send.
_CLAUSE_BREAK: Final = _LivePattern(
    lambda: (
        r"\s*[,;:\N{EN DASH}\N{EM DASH}]\s*|\s+(?:"
        + _extend("and|but|so", "script_lint._CLAUSE_BREAK")
        + r")\s+"
    ),
    re.IGNORECASE,
)
_WHATSAPP: Final = _LivePattern(
    lambda: _extend(r"whats\s?app", "script_lint._WHATSAPP"), re.IGNORECASE
)
#: Each verb also in the Latin-letter Telugu and Hindi that scripts are written in as often as
#: the native scripts ("WhatsApp lo pampistanu", "bhej dunga").
_SENDS: Final = _LivePattern(
    lambda: _extend(r"\bsend|\bsent\b|\bshare", "script_lint._SENDS"), re.IGNORECASE
)
_SMS: Final = _LivePattern(
    lambda: _extend(r"\bsms\b|\btext message", "script_lint._SMS"), re.IGNORECASE
)
_CALL_BACK: Final = _LivePattern(
    lambda: _extend(r"call (?:you )?back|call-back|callback", "script_lint._CALL_BACK"),
    re.IGNORECASE,
)
_BOOKS: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:i(?:'ll| will)|let me|we(?:'ll| will)) (?:book|confirm|fix)\b", "script_lint._BOOKS"
    ),
    re.IGNORECASE,
)
_HANDS_OVER: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:transfer|connect|put) you\b|\bput you through\b", "script_lint._HANDS_OVER"
    ),
    re.IGNORECASE,
)


def offers_call_back(text: str) -> bool:
    """Whether `text` offers a call back in a clause that does not say it will not happen,
    in English or the founder's Indian-language words (`call_words.json`). Unlike
    `unbacked_promise`, a condition does not excuse it: "if you still cannot, we will call you
    back" is the offer itself."""
    return any(
        _CALL_BACK.search(clause) and not _NEGATED.search(clause)
        for sentence in re.split(r"(?<=[.?!।])\s+", text)
        for clause in _CLAUSE_BREAK.split(sentence)
        if clause
    )


def unbacked_promise(text: str, manifest: CapabilityManifest) -> str | None:
    """What `text` promises that `manifest` says this agent cannot do, or None."""
    for sentence in re.split(r"(?<=[.?!।])\s+", text):
        # A condition qualifies the whole sentence ("only if you can, offer a call back").
        if _CONDITIONAL.search(sentence):
            continue
        clauses = [c for c in _CLAUSE_BREAK.split(sentence) if c]

        def promised(verb: _LivePattern, clauses: list[str] = clauses) -> bool:
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


_SENTENCE: Final = re.compile(r"[^.?!\uff1f\u0964]+[.?!\uff1f\u0964]?")
_LIST_SPLIT: Final = re.compile(r",|\band\b", re.IGNORECASE)
_ASKED_THING: Final = re.compile(r"\byour\b", re.IGNORECASE)
#: "your number or your email?" offers a choice, which is one answer.
_CHOICE: Final = re.compile(r"\bor\b", re.IGNORECASE)


def listed_asks(text: str) -> int:
    """How many asks a question lists beyond its first, in English words: "your name, your
    goal and another number?" is several asks under one question mark (step 1 of the Rytu
    Khata script of 25 Nov 2026 put five there). Each comma- or "and"-separated part naming
    one of the person's things ("your ...") is an ask. A line in an Indian language is left
    to the review pass, which reads every language."""
    if has_indic_letters(text):
        return 0
    extra = 0
    for sentence in _SENTENCE.findall(text):
        asked = sentence.strip()
        if not asked.endswith(("?", "\uff1f")) or _CHOICE.search(asked):
            continue
        parts = [part for part in _LIST_SPLIT.split(asked) if _ASKED_THING.search(part)]
        extra += max(len(parts) - 1, 0)
    return extra


def asks_count(text: str) -> int:
    """How many things a line asks: its question marks and the asks listed under one."""
    return question_count(text) + listed_asks(text)


#: Latin letters only: an agent name is configured in them, and its Telugu or Hindi spelling
#: cannot be compared with it without a transliteration we do not have. The lead-in in any
#: case ("My name is" starts a sentence); the name capitalised, as a name is written.
_SELF_NAMED: Final = re.compile(r"\b(?i:my name is|i am|i'm|this is) ([A-Z][a-z]+)\b")


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
OPENING_FIELDS: Final = frozenset({"opening_line", "outbound_opening_line"})


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
_EN_CALLER_ACTION: Final = (
    r"\b(?:open|tap|press|click|type|select|choose|scroll|swipe|install|download|enter|"
    r"go to|log in|sign in)\b"
)
_CALLER_ACTION: Final = re.compile(_EN_CALLER_ACTION, re.IGNORECASE)
#: The same actions in any language a spoken line is written in: the Indian-language verbs
#: are the founder's (`call_words.json`), matched inside a word, since both scripts join
#: endings to the verb ("నొక్కండి", "నొక్కితే").
_SPOKEN_ACTION: Final = _LivePattern(
    lambda: _extend(_EN_CALLER_ACTION, "script_lint._CALLER_ACTION"), re.IGNORECASE
)


def names_caller_action(text: str) -> bool:
    """Whether `text` names something the person does on their phone, in any call language
    the action words cover (`call_rules.task_first_problem`)."""
    return _SPOKEN_ACTION.search(text) is not None


#: "Once it opens", "after that": said before an action, it hands over the next step before
#: the person has done the one it waits on.
_AFTER_CLAUSE: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:once|after)\s+(?:it|that|this|you|the)\b|"
        r"\bwhen (?:it|that|this) (?:opens|shows|appears|loads|comes)\b",
        "script_lint._AFTER_CLAUSE",
    ),
    re.IGNORECASE,
)
_STAGE_INSTRUCTION: Final = re.compile(r"^stages\.\d+\.instruction$")


def stacked_actions(text: str) -> bool:
    """Whether one instruction gives the caller several things to do on their phone at once:
    a numbered list, or two or more of those actions."""
    return len(_NUMBERED_ITEM.findall(text)) >= 2 or len(_CALLER_ACTION.findall(text)) >= 2


#: An English instruction's own verb, said where an instruction starts: wider than
#: `_CALLER_ACTION`, because it is read only at the start of a clause, so a label ("tap
#: Save", "the Add Farm button") is never counted as a second action.
_STEP_VERB: Final = re.compile(
    r"(?:open|tap|press|click|type|select|choose|pick|enter|fill|add|save|submit|search|"
    r"scroll|swipe|install|download|upload|allow|accept|go to|log in|sign in)\b",
    re.IGNORECASE,
)
#: Where one English instruction joins another inside a sentence.
_STEP_JOIN: Final = re.compile(r",|\band then\b|\bthen\b|\band\b", re.IGNORECASE)
#: One verb given two boxes or choices ("enter the amount and the farm", "select the farm
#: and the crop"): two things to fill in, said as one.
_TWO_FIELDS: Final = re.compile(r"^(?:enter|type|fill in|select|choose|pick)\b[^,]*\band\b", re.I)


def english_steps(text: str) -> int:
    """How many things an English line tells the person to do: each clause that opens with
    an instruction's verb, and two for one verb given two boxes or choices. The 27 Nov 2026
    script's small steps read "Enter the expense amount and pick your farm" and "Enter the
    sale amount and save the entry", and the call said each as one turn; `_CALLER_ACTION`
    had neither "pick" nor "save"."""
    count = 0
    for sentence in _LINE_CLAUSE_END.split(text):
        if _TWO_FIELDS.match(_LEAD_IN.sub("", sentence.strip())):
            count += 2
            continue
        count += sum(
            1
            for part in _STEP_JOIN.split(sentence)
            if _STEP_VERB.match(_LEAD_IN.sub("", part.strip()))
        )
    return count


def stacked_line(text: str) -> bool:
    """Whether a line the agent says gives the person more than one thing to do in one turn,
    in any language: two actions, or one said after "once it opens" (the step before it, not
    yet done). The 26 Nov 2026 call said "once it opens, press Add to Home screen, the icon
    comes on your home screen; tell me when it does" as one turn. Phone-support practice is
    one action, then the person's word that it is done (speakshark.com/blog/english-it-
    support-customer-calls, read 5 Nov 2026, cited at `call_rules.SCRIPT_FLOW_RULE`).
    Not for instructions, where "once they say it is open, have them tap" is how a step
    waits (`stacked_actions`). A closing request to be told ("tell me once it is open") is
    `asks_when_done`'s and is not read for actions."""
    tail = asks_when_done(text)
    if tail is not None and tail in text:
        # Only the request itself is cut: a Telugu line often joins the actions and the
        # request in one sentence ("ఓపెన్ చేసి సెర్చ్ చేయండి, అయ్యాక నాకు చెప్తారా?", 26 Nov 2026).
        asked = _ASKS_WHEN_DONE.search(tail)
        text = text[: text.rfind(tail) + (asked.start() if asked else 0)]
    if stacked_actions(text) or english_steps(text) >= 2:
        return True
    actions = list(_SPOKEN_ACTION.finditer(text))
    if len(actions) >= 2:
        return True
    after = _AFTER_CLAUSE.search(text)
    return bool(actions) and after is not None and after.start() < actions[0].start()


#: Asking the person to say when a step is done ("tell me once it opens", "అది ఓపెన్ అయ్యాక
#: నాకు చెప్పండి"). English here; the Indian-language forms are the founder's.
_ASKS_WHEN_DONE: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:let me know|tell me|say)\s+(?:when|once|after|as soon as|whether)\s+"
        r"(?:it|that|this|the|you)\b[^?]*?\b(?:done|finished|ready|open|opens|opened|there|"
        r"in|installed|logged|signed|shows?|showing|appears?|loads?|comes?|see|works?|added|"
        r"saved)\b|\blet me know\W*$",
        "script_lint._ASKS_WHEN_DONE",
    ),
    re.IGNORECASE,
)


def asks_when_done(text: str) -> str | None:
    """The last sentence of `text` when it asks the person to say once a step is done, else
    None. The person says so on their own, as anyone does when helped on the phone; a line
    that asks it makes the agent end every turn with the same request, which the founder
    heard on the 26 Nov 2026 call ("no human talks like this"). The script checks and the
    call review (`turn_checks`) read it by this one rule."""
    parts = [part.strip() for part in _SENTENCE.findall(" ".join(text.split())) if part.strip()]
    if not parts:
        return None
    return parts[-1] if _ASKS_WHEN_DONE.search(parts[-1]) else None


#: Words that may come before an English instruction's verb ("Now tap ...", "OK, please open").
_LEAD_IN: Final = re.compile(
    r"^(?:(?:now|please|then|next|first|ok|okay|so|and|just|sure|great|good)\b[\s,]*)+",
    re.IGNORECASE,
)


def tells_caller_to_act(clause: str) -> bool:
    """Whether an English clause tells the caller to do something on their phone: it opens,
    after a lead-in word, with one of the caller's actions ("Now tap the menu"). "I'll open
    your form" and "you opened it" are not instructions. English only: an Indian language's
    instruction is not read by words (`turn_checks.asks_done_too_soon`)."""
    return bool(_CALLER_ACTION.match(_LEAD_IN.sub("", clause.strip())))


#: Where a spoken line's clauses end, for reading it one instruction at a time.
_LINE_CLAUSE_END: Final = re.compile(r"[.!?;\n]+")


def _gives_an_action(line: str) -> bool:
    return any(tells_caller_to_act(clause) for clause in _LINE_CLAUSE_END.split(line))


def asks_caller_to_act(script: CallScript) -> bool:
    """Whether a script has the caller do things on their own phone during the call: a
    section with a step-by-step list, an instruction that stacks several on-screen actions
    (`stacked_actions`), or a line the agent says that gives one ("Now tap Register."). What
    switches "Give callers time" on for a campaign or line (`agents/give_callers_time.
    holder_gives_time`). English words only, as `tells_caller_to_act`; a step-by-step list is
    read by structure, in any language. A raw script is not read: it is written to the agent
    ("Open with a greeting"), so its verbs are not the caller's, and the owner can still
    switch the preset on for that holder."""
    if script.raw_override is not None:
        return False
    for stage in script.stages:
        if stage.procedure or stacked_actions(stage.instruction):
            return True
        spoken = (stage.sounds_like, *stage.scripts.values(), *(qa.answer for qa in stage.qa))
        if any(_gives_an_action(line) for line in spoken):
            return True
    return any(_gives_an_action(faq.answer) for faq in script.faqs)


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


def collected_label(entry: str) -> str:
    """The label a step's `collect` entry names: the writer is shown each detail as "Label:
    when it is asked" and may copy the whole entry."""
    return entry.partition(":")[0].strip()


def unasked_problems(
    script: CallScript, collect: tuple[str, ...], call_back: tuple[str, ...] = ()
) -> list[str]:
    """A finding for each detail the job notes and no step asks (`unasked_details`). With no
    steps there is nowhere to ask; the details list still reaches the call."""
    if not script.stages:
        return []
    return [
        f'script: no step asks for "{label}"; ask it in the step where the call reaches it, '
        "as one question."
        for label in unasked_details(script, collect, call_back)
    ]


def unasked_details(
    script: CallScript, collect: tuple[str, ...], call_back: tuple[str, ...] = ()
) -> list[str]:
    """The labels in `collect` that no step asks for, in their order.

    A step asks for a detail when its `collect` names it, or when its name, instruction and
    step-by-step list carry at least half of the label's words (their first five letters, so
    word forms meet). A label with no English-letter word cannot be compared with English
    instructions and is never reported. The details a call back takes (`call_back`) are asked
    on the call-back path, so a script with a way out to the call back asks them there."""
    steps = [
        (
            {collected_label(c).casefold() for c in stage.collect},
            _stems(" ".join([stage.name, stage.instruction, *(p.action for p in stage.procedure)])),
        )
        for stage in script.stages
    ]
    calls_back = any(
        CALL_BACK in {stage.otherwise, *(b.target for b in stage.branches)}
        for stage in script.stages
    )
    later = {label.casefold() for label in call_back} if calls_back else set()
    missing: list[str] = []
    for label in collect:
        if label.casefold() in later:
            continue
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

    A step whose instruction is said as written (`says_instruction`) holds a spoken line; a
    scenario's description never does, in either mode. A step's name, an objection's caller
    side, the facts and the legacy `steps` are not here: the first two are the caller's words
    or the owner's label, and the AI writes none of the rest as instructions."""
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
        if not says_instruction(stage):
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
        if says_instruction(stage):
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
    """The writer-score lints on a whole script (`scripts/eval_script_writer`), run through
    the check registry (`script_checks.SCRIPT_PROBLEM_CHECKS`), so the eval and every
    production path read one definition of each check. A raw (hand-written) script has no
    fields to walk and is checked as one instruction text."""
    from apps.api.agents import script_checks

    return script_checks.texts(
        script_checks.run(script, context, ids=script_checks.SCRIPT_PROBLEM_CHECKS)
    )


_PLACES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^outbound_opening_line"), "The opening on calls it makes"),
    (re.compile(r"^opening_line"), "The opening line"),
    (re.compile(r"^stages\.(\d+)\."), "Step {n}"),
    (re.compile(r"^objections\.(\d+)\."), "Push-back answer {n}"),
    (re.compile(r"^example_exchange\.\d+\."), "The example call"),
    (re.compile(r"^style\.sample_phrases\.\d+"), "A sample phrase"),
    (re.compile(r"^style\."), "How it speaks"),
    (re.compile(r"^ending$"), "The ending"),
    (re.compile(r"^faqs\.(\d+)\."), "Quick fact {n}"),
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


def promo_problem(where: str, text: str, context: LintContext, *, spoken: bool) -> str | None:
    """A promotional or urgency word in a line the agent says (`spoken`) or an instruction it
    follows, by the D-943 list, or None."""
    promo = _promo(text, context)
    if not promo:
        return None
    if not spoken:
        return f'{where}: tells the agent to use "{promo.phrase}"; no offers or urgency.'
    effect = (
        "which makes the call promotional"
        if promo.severity == "strong"
        else "which can read as promotional"
    )
    return (
        f'{where}: says "{promo.phrase}", {effect}; say only facts the caller asked '
        "about, with no offer, discount or urgency."
    )


def promise_problem(where: str, text: str, context: LintContext, *, spoken: bool) -> str | None:
    """A promise the capability manifest cannot keep (`unbacked_promise`), or None. No
    manifest, nothing to judge it against."""
    if context.manifest is None:
        return None
    promise = unbacked_promise(text, context.manifest)
    if not promise:
        return None
    if spoken:
        return f"{where}: promises {promise}; take the details for the team."
    return f"{where}: has the agent promise {promise}."


# --- the owner's "Never" rules (W3.9) ----------------------------------------------------
#
# A rule stays a pinned fact (`kb_facts`, D-1017: no marker of its own); it is recognised
# here by how it is worded, in code rather than by a model, so a publish check never waits on
# a model and gives the same answer every time. What a rule forbids is read from its words
# into one of `OwnerRuleKind`; a rule naming none of them is left to the post-call judge,
# which reads every rule as written. English only: the owner's rules are typed in the
# dashboard, and a rule in another language is not read here.

_PROHIBITION: Final = re.compile(
    r"^\s*(?:never|do\s+not|don'?t|dont|must\s+not|mustn'?t|should\s+not|shouldn'?t|"
    r"no\s+one\s+should|avoid|no)\b",
    re.IGNORECASE,
)
#: Where one rule ends and the next begins inside one pinned fact.
_RULE_SENTENCE_END: Final = re.compile(r"(?<=[.!?।])\s+|\s*\n+\s*")
_TIME_WORD: Final = re.compile(
    r"\b(?:time|times|hour|hours|when|exact|specific|o'?clock|slot|slots)\b", re.I
)
#: A clock time said in a line: "5 PM", "5:30", "at 5", "five o'clock", and an hour said with
#: the call languages' hour words ("5 గంటలకు", "5 baje", "5 बजे").
_CLOCK_SAID: Final = re.compile(
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\b\d{1,2}:\d{2}\b|\bo'?clock\b|"
    r"\bat\s+\d{1,2}\b|\b\d{1,2}\s*(?:గంట|baje\b|gantala|बजे)",
    re.IGNORECASE,
)
#: A time named without a clock ("which time", "a time"): it breaks the rule only in a clause
#: that does not refuse it ("I can't give a time" keeps it).
_TIME_NAMED: Final = re.compile(r"\b(?:which|what|a|the|exact)\s+time\b", re.IGNORECASE)
_DISCOUNT: Final = re.compile(
    r"\bdiscounts?\b|\d+\s*%\s*off\b|\bpercent off\b|\bconcessions?\b|\bcashback\b|"
    r"\bcheaper\b|\blower\s+price\b|\bprice\s+cut\b",
    re.I,
)
_PRICE_RULE: Final = re.compile(r"\b(?:prices?|pricing|costs?|fees?|rates?|charges?)\b", re.I)
_PRICE_SAID: Final = re.compile(r"₹\s*\d|\brs\.?\s*\d|\b\d[\d,]*\s*(?:rupees|rs\b|/-)", re.I)
_REFUND: Final = re.compile(r"\brefunds?\b|\bmoney back\b", re.IGNORECASE)
_GUARANTEE: Final = re.compile(r"\bguarantee[sd]?\b|\bassured?\b|\b100\s*%", re.IGNORECASE)
_BOOKING_RULE: Final = re.compile(r"\b(?:book|booking|appointments?|confirm)\b", re.IGNORECASE)


def _rule_kind(words: str) -> OwnerRuleKind | None:
    """What a "Never" rule forbids, the narrowest reading first."""
    if _CALL_BACK.search(words):
        return "call_back_time" if _TIME_WORD.search(words) else "call_back"
    if _DISCOUNT.search(words):
        return "discount"
    if _REFUND.search(words):
        return "refund"
    if _GUARANTEE.search(words):
        return "guarantee"
    if _WHATSAPP.search(words):
        return "whatsapp"
    if _BOOKING_RULE.search(words):
        return "booking"
    if _PRICE_RULE.search(words):
        return "price"
    return None


def owner_rules(texts: Iterable[str]) -> tuple[OwnerRule, ...]:
    """Every "Never" rule in the owner's pinned facts: each sentence of `texts` that opens like
    one, once, in the owner's words, with what it forbids (`_rule_kind`, None when no code
    check can see it). The one reader of the owner's rules: the publish check takes those a
    script line can break (`owner_prohibitions`); the practice judge and the real-call check
    take them all (`call_rules.owner_rules`)."""
    out: dict[str, OwnerRule] = {}
    for text in texts:
        for sentence in _RULE_SENTENCE_END.split(text or ""):
            words = " ".join(sentence.split())
            if words and _PROHIBITION.search(words):
                out.setdefault(words.casefold(), OwnerRule(words, _rule_kind(words)))
    return tuple(out.values())


def owner_prohibitions(facts: Iterable[str]) -> tuple[OwnerRule, ...]:
    """The owner's rules naming something a script line can do (`owner_rules` with a kind)."""
    return tuple(rule for rule in owner_rules(facts) if rule.kind is not None)


def breaks_owner_rule(rule: OwnerRule, text: str) -> bool:
    """Whether any sentence of `text` does what `rule` forbids; False for a rule with no kind."""
    return rule.kind is not None and any(
        _breaks(rule, s) for s in re.split(r"(?<=[.?!।])\s+", text) if s.strip()
    )


def _breaks(rule: OwnerRule, sentence: str) -> bool:
    """Whether one sentence does what `rule` forbids, in a clause that does not say it will
    not happen ("we can't give a discount" keeps the rule)."""
    clauses = [c for c in _CLAUSE_BREAK.split(sentence) if c]

    def said(pattern: re.Pattern[str] | _LivePattern) -> bool:
        return any(pattern.search(c) and not _NEGATED.search(c) for c in clauses)

    if rule.kind == "call_back_time":
        return offers_call_back(sentence) and (
            bool(_CLOCK_SAID.search(sentence)) or said(_TIME_NAMED)
        )
    if rule.kind == "call_back":
        return offers_call_back(sentence)
    if rule.kind == "discount":
        return said(_DISCOUNT)
    if rule.kind == "price":
        return said(_PRICE_SAID)
    if rule.kind == "refund":
        return said(_REFUND)
    if rule.kind == "guarantee":
        return said(_GUARANTEE)
    if rule.kind == "booking":
        return said(_BOOKS)
    return bool(_WHATSAPP.search(sentence)) and said(_SENDS)


def owner_rule_problem(where: str, text: str, rules: Sequence[OwnerRule]) -> str | None:
    """The first of the owner's rules `text` breaks, named in their words, or None."""
    for rule in rules:
        if breaks_owner_rule(rule, text):
            return f'{where}: breaks your rule "{rule.words[:120]}"; change the line to keep it.'
    return None


def figure_problem(where: str, text: str, context: LintContext) -> str | None:
    figure = unknown_figure(text, context.facts)
    if not figure:
        return None
    return f'{where}: says "{figure}", a figure no fact of the owner gives; leave it out.'


def questions_problem(where: str, text: str) -> str | None:
    asked = asks_count(text)
    return f"{where}: asks {asked} questions; ask one and wait." if asked > 1 else None


def opening_shape_problems(where: str, text: str, context: LintContext) -> list[str]:
    """An opening on a placed call without the person's name or a question, and one that does
    not read when the name is unknown. [] for a line that is not an opening."""
    problems: list[str] = []
    if placed_call_opening(where, context):
        opening = placed_opening_problem(where, text)
        if opening:
            problems.append(opening)
    if where in OPENING_FIELDS:
        nameless = name_segment_problem(where, text, placed=not answered_opening(where, context))
        if nameless:
            problems.append(nameless)
    return problems


def persona_problem(where: str, text: str, context: LintContext) -> str | None:
    if not context.agent_name.strip():
        return None
    other = other_persona(text, agent_name=context.agent_name, business_name=context.business_name)
    if not other:
        return None
    return f'{where}: calls the agent "{other}"; its name is {context.agent_name.strip()}.'


def stacked_instruction_problem(where: str, text: str) -> str | None:
    """A step's instruction that gives the caller several actions at once."""
    if not (_STAGE_INSTRUCTION.match(where) and stacked_actions(text)):
        return None
    return (
        f"{where}: gives several actions in one go; put each in the step's step-by-step "
        "list, so the agent gives one and stops; the caller says when it is done."
    )


def spoken_line_problems(where: str, text: str, context: LintContext) -> list[str]:
    """What the lint finds in one line the agent says: the writer's refusal of a line it
    wrote (`script_assist.language_problems`), made of the same rules the check registry
    runs one by one (`script_checks`)."""
    return [
        problem
        for problem in (
            promo_problem(where, text, context, spoken=True),
            promise_problem(where, text, context, spoken=True),
            figure_problem(where, text, context),
            questions_problem(where, text),
            *opening_shape_problems(where, text, context),
            persona_problem(where, text, context),
        )
        if problem
    ]


def instruction_problems(where: str, text: str, context: LintContext) -> list[str]:
    """What the lint finds in an instruction the agent follows but never says: a promise
    outside the manifest, a promotional or urgency term, several actions in one step."""
    return [
        problem
        for problem in (
            promo_problem(where, text, context, spoken=False),
            promise_problem(where, text, context, spoken=False),
            stacked_instruction_problem(where, text),
        )
        if problem
    ]


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


def next_steps(script: CallScript, index: int) -> set[str]:
    """The steps the call can go to from step `index`: its ways out, else the next step."""
    stage = script.stages[index]
    out = {branch.target for branch in stage.branches}
    if stage.otherwise:
        out.add(stage.otherwise)
    elif index + 1 < len(script.stages):
        out.add(script.stages[index + 1].id)
    return out


def reachable_steps(script: CallScript, start: int) -> set[int]:
    """Every step the call can reach after step `start`."""
    at = {stage.id: i for i, stage in enumerate(script.stages)}
    seen: set[int] = set()
    todo = [start]
    while todo:
        for target in next_steps(script, todo.pop()):
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


#: An instruction that takes the caller's use as given ("they already use the app").
_PRESUMES_USE: Final = re.compile(
    r"\b(?:already|since (?:they|you)|as (?:they|you))\b[^.;?]{0,25}\b(?:us(?:e|es|ed|ing)|user)\b|"
    r"\b(?:they|you) (?:are|were|have been|had been) (?:already )?using\b",
    re.IGNORECASE,
)
#: A way out whose condition says the caller uses it: the only way a step that takes their
#: use as given may be reached. Having it, installing it or registering is not using it:
#: the Rytu Khata caller of 9 Nov 2026 had registered and never used the app.
_SAYS_USES: Final = re.compile(r"\b(?:us(?:e|es|ed|ing)|user|tried)\b", re.IGNORECASE)
_DENIES: Final = re.compile(
    r"n't\b|\b(?:not|never|no|nor|yet to|only|without|stopped|unused)\b", re.IGNORECASE
)
#: A step that decides for itself who it is for: it asks first whether the caller uses it,
#: or goes on only for callers who said they do. A linear script (a new draft has no ways
#: out) can gate a step only this way.
_ASKS_WHETHER_USES: Final = re.compile(
    r"\b(?:ask|check|find out|confirm)\w*\b[^.;?]{0,30}\b(?:whether|if)\b[^.;?]{0,40}"
    r"\b(?:us(?:e|es|ed|ing)|tried)\b",
    re.IGNORECASE,
)
_ONLY_IF_USES: Final = re.compile(
    r"\b(?:if|when|once)\s+(?:they|the caller)\b[^.;?,]{0,25}\b(?:us(?:e|es|ed|ing)|tried)\b",
    re.IGNORECASE,
)


def _gates_itself(instruction: str) -> bool:
    if _ASKS_WHETHER_USES.search(instruction):
        return True
    match = _ONLY_IF_USES.search(instruction)
    return match is not None and not _DENIES.search(match.group(0))


def _asks_experience(stage: ConversationStage) -> bool:
    return bool(_ASKS_EXPERIENCE.search(f"{stage.name} {stage.instruction}"))


def _presumes_use(stage: ConversationStage) -> bool:
    """Whether a step needs the caller to use the thing already: it asks how they use or like
    it, or takes their use as given. One that asks whether they use it first does not."""
    text = f"{stage.name} {stage.instruction}"
    if _gates_itself(stage.instruction):
        return False
    return _asks_experience(stage) or bool(_PRESUMES_USE.search(text))


def _says_uses(condition: str) -> bool:
    return bool(_SAYS_USES.search(condition)) and not _DENIES.search(condition)


def _reached_unasked(script: CallScript) -> set[int]:
    """The steps the call reaches with a caller who has not said they use it: from the first
    step, along every way out except one whose condition says they do (`_says_uses`).
    "Otherwise" and the step after carry no answer, so they never gate."""
    if not script.stages:
        return set()
    at = {stage.id: i for i, stage in enumerate(script.stages)}
    seen = {0}
    todo = [0]
    while todo:
        index = todo.pop()
        stage = script.stages[index]
        targets = [b.target for b in stage.branches if not _says_uses(b.when)]
        if stage.otherwise:
            targets.append(stage.otherwise)
        elif index + 1 < len(script.stages):
            targets.append(script.stages[index + 1].id)
        for target in targets:
            i = at.get(target)
            if i is not None and i not in seen:
                seen.add(i)
                todo.append(i)
    return seen


def _order_findings(script: CallScript) -> list[tuple[int, str]]:
    """(step index, problem) for each step asked of a caller who cannot answer it."""
    setup = [i for i, stage in enumerate(script.stages) if _sets_up(stage)]
    unasked = _reached_unasked(script)
    found: list[tuple[int, str]] = []
    for i, stage in enumerate(script.stages):
        if _sets_up(stage) or not _presumes_use(stage):
            continue
        reach = reachable_steps(script, i)
        before = next((s for s in setup if s in reach), None)
        after = next((s for s in setup if i in reachable_steps(script, s)), None)
        if _asks_experience(stage) and (before is not None or after is not None):
            when = (
                f"before step {before + 1} helps them set it up"
                if before is not None
                else f"right after step {(after or 0) + 1} helps them set it up"
            )
            found.append(
                (
                    i,
                    f"stages.{i}.instruction: asks how the caller uses or likes it, and the call "
                    f"can reach it {when}, when they cannot answer it; ask it only on the way "
                    "for callers who said they use it, and after setting it up show them the "
                    "first thing to do.",
                )
            )
        elif i in unasked:
            found.append(
                (
                    i,
                    f"stages.{i}.instruction: takes as given that the caller uses it, and the "
                    "call reaches it with callers who have not said so (having it, installing "
                    "it or registering is not using it); ask first, as a question, whether they "
                    "use it, and come here only through a way out whose condition says they "
                    "do, or have this step ask that first and its line ask rather than say it.",
                )
            )
    return found


def order_problems(script: CallScript) -> list[str]:
    """A step asked of a caller who cannot answer it:

    - how the caller uses or likes something, on a path that also helps them set it up:
      before it they do not have it yet, right after it they have not used it (the Rytu
      Khata call of 6 Nov 2026: "I only just installed it, how would I be using it?");
    - a step that takes their use as given, reached without a way out whose condition says
      they use it (the Rytu Khata call of 9 Nov 2026: "you already use the app, what for?"
      to a caller who had only registered). Asking before assuming, and branching on the
      answer, is the conversation-design default ("Don't ask the user a question if you're
      not prepared to handle their answer", developers.google.com/assistant/
      conversation-design/questions, read 9 Nov 2026).

    Read in the English instructions and conditions only, so it works for any call language.
    """
    return [problem for _i, problem in _order_findings(script)]


def step_line(script: CallScript, index: int) -> tuple[str, str]:
    """(path, text) of what the agent says at step `index`: its instruction when that is said
    as written (`says_instruction`), else its "sounds like" line, which the model copies."""
    stage = script.stages[index]
    if says_instruction(stage):
        return f"stages.{index}.instruction", stage.instruction
    if not stage.sounds_like.strip():
        # A step written with examples (DESIGN §3.2) has no "sounds like" line; its first
        # example turn is what the step sounds like to the checks that read one line a step.
        for tag, said in stage.examples.items():
            if said.turns:
                return f"stages.{index}.examples.{tag}.turns.0", said.turns[0]
    return f"stages.{index}.sounds_like", stage.sounds_like


def presumed_lines(script: CallScript) -> tuple[str, ...]:
    """What the agent says at each step `order_problems` names: a line a caller who cannot
    answer it hears, which the practice checks look for in the replies
    (`turn_checks.conversation_problems`)."""
    lines: list[str] = []
    for i, _problem in _order_findings(script):
        _path, line = step_line(script, i)
        if line.strip():
            lines.append(line.strip())
    return tuple(dict.fromkeys(lines))


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
            *(step_line(script, i) for i in range(len(script.stages))),
        )
        if len(_words(text)) >= _MIN_REPEAT_WORDS
    ]
    problems: list[str] = []
    for later, (path, text) in enumerate(lines):
        words = _words(text)
        for earlier_path, earlier in lines[:later]:
            # A "both" agent's two openings are never said on one call, and share its names
            # and any woven notice words by design.
            if path in OPENING_FIELDS and earlier_path in OPENING_FIELDS:
                continue
            other = _words(earlier)
            if len(words & other) / len(words | other) >= _REPEAT_OVERLAP:
                problems.append(
                    f"{path}: says nearly what {_place(earlier_path)} says; explain each "
                    "thing in one step, and have this step move the call on (answer what "
                    "they asked, or the next thing to do)."
                )
                break
    return problems


#: A step told to do what the opening line already did: greet, say who is calling, or ask
#: whether now is a good time. Read in the English instructions only.
_REDOES_OPENING: Final = re.compile(
    r"\b(?:greet\w*|introduce (?:yourself|herself|himself|the agent)|"
    r"identify (?:yourself|herself|himself)|say who (?:you are|is calling)|"
    r"(?:ask|check)\w* (?:if|whether) (?:they|it is|now)\b[^.;]{0,30}"
    r"\b(?:talk|speak|good time|convenient|free|suits?)\b)",
    re.IGNORECASE,
)


def opening_redone_problems(script: CallScript) -> list[str]:
    """A step that greets, introduces the agent or asks whether now suits, in a script with
    an opening line. The engine says the opening first, word for word, and the model follows
    the step it is on: on the founder's Rytu Khata call of 9 Nov 2026 (20:32) the first step
    said "greet the lead by name, identify yourself, ask if they can talk now", and the
    agent greeted and introduced itself a second time after the opening had."""
    if not (script.opening_line.strip() or script.outbound_opening_line.strip()):
        return []
    return [
        f"stages.{i}.instruction: greets, says who is calling or asks if now is a good time, "
        "which the opening line already did; leave that out and start this step from what "
        "comes after it."
        for i, stage in enumerate(script.stages)
        if not says_instruction(stage) and _REDOES_OPENING.search(stage.instruction)
    ]


#: The words before a line's first mark that count as how it opens: a short reaction. Three,
#: so "చాలా మంచిది అండి" (very good + the polite tag) is one, as it was on the 26 Nov 2026 call.
_OPENER_MAX_WORDS: Final = 3
#: The full-width comma and question mark are escapes (RUF001).
_FIRST_MARK: Final = re.compile("[,.!?;:\\u0964\\uff0c\\uff1f]")


def line_opener(text: str) -> str | None:
    """The short lead before a line's first mark ("సరే అండి" of "సరే అండి, ఏ ఏరియా?"), lower
    case, or None when the line has no mark or leads with more than a few words. The script
    checks and the call review (`turn_checks.opener`) read openers by this one rule."""
    head = _FIRST_MARK.split(" ".join(text.split()), maxsplit=1)
    if len(head) < 2:
        return None
    words = [word for token in head[0].split() if (word := token.strip(_TOKEN_EDGE).casefold())]
    return " ".join(words) if 0 < len(words) <= _OPENER_MAX_WORDS else None


def same_opener_problems(script: CallScript) -> list[str]:
    """A step's line that opens with the same short reaction as an earlier step's line. The
    in-call model copies how a step's line opens, so lines that all open alike make every
    reply open alike (founder's Rytu Khata call of 9 Nov 2026: three replies running began
    with the same "OK"). Read by words, so it works in any language. A step's line in each
    call language (`scenario_lines`) is held to the same rule among the lines of its language:
    on the Rytu Khata call of 23 Nov 2026 (23:19) the Telugu lines opened alike while the
    English examples did not."""
    problems: list[str] = []
    for group in _line_groups(script, procedure=False):
        seen: dict[str, int] = {}
        for i, path, line in group:
            said = line_opener(line)
            if said is None:
                continue
            if said in seen:
                problems.append(
                    f"{path}: opens with the same words as step {seen[said] + 1}'s line; the "
                    "agent copies how lines open, so its replies would all begin alike. Open "
                    "it with its own point."
                )
            else:
                seen[said] = i
    return problems


def _line_groups(script: CallScript, *, procedure: bool) -> list[list[tuple[int, str, str]]]:
    """(step index, path, text) of the lines the agent copies, one group per language: the
    "sounds like" lines, each call language's scenario lines, and with `procedure` the small
    steps' actions, which the agent says one a turn."""
    groups: list[list[tuple[int, str, str]]] = [
        [
            (i, path, line)
            for i in range(len(script.stages))
            for path, line in [step_line(script, i)]
            if line.strip()
        ]
    ]
    by_language: dict[str, list[tuple[int, str, str]]] = {}
    for i, stage in enumerate(script.stages):
        for tag, text in stage.scripts.items():
            if text.strip():
                by_language.setdefault(tag, []).append((i, f"stages.{i}.scripts.{tag}", text))
    # Examples are a group of their own per language: a step's several turns are written to
    # differ from each other and from every other step's, which is what the model copies.
    for path, text in example_lines(script):
        tag = line_language(path)
        by_language.setdefault(f"examples:{tag}", []).append((int(path.split(".")[1]), path, text))
    groups += by_language.values()
    if procedure:
        groups.append(
            [
                (i, f"stages.{i}.procedure.{j}.action", step.action)
                for i, stage in enumerate(script.stages)
                for j, step in enumerate(stage.procedure)
            ]
        )
    return groups


#: The words at a line's end that count as its closing tag ("... నాకు చెప్తారా?", "tell me").
#: Two, because the tag the 26 Nov 2026 call ended every reply with was two words long and
#: the word before it changed with the step.
_ENDING_WORDS: Final = 2
#: A line shorter than this has no tag apart from its point.
_ENDING_MIN_LINE_WORDS: Final = 5
#: Step lines of one language ending alike: two is already the habit, since the agent copies
#: both into every reply.
_ENDING_REPEATS: Final = 2
#: A step's small steps are English instructions that may fairly end alike ("... the
#: button"); three of them, and half the list, before their ending is a tag.
_SMALL_STEP_ENDING_WORDS: Final = 3
_SMALL_STEP_ENDING_REPEATS: Final = 3


def line_ending(text: str, words: int = _ENDING_WORDS) -> str | None:
    """The last `words` words of `text`, lower case, or None for a line too short to have a
    closing tag apart from its point. The script checks and the call review (`turn_checks`)
    read endings by this one rule."""
    said = [
        word
        for token in re.sub(r"\{\{[^}]*\}\}", " ", text).split()
        if (word := token.strip(_TOKEN_EDGE).casefold())
    ]
    if len(said) < _ENDING_MIN_LINE_WORDS:
        return None
    return " ".join(said[-words:])


def same_ending_problems(script: CallScript) -> list[str]:
    """Lines that end with the same tag, in one language or across a step's small steps:
    on the Rytu Khata calls of 23 Nov 2026 (23:19) and 26 Nov 2026 nearly every reply ended
    "tell me" in Telugu, copied from lines written that way. The agent waits after each
    action anyway (`call_script.PROCEDURE_LEAD`), so the tag says nothing; a model told to
    vary repeats less, but copies a line it is given ("Sample phrases (vary, don't always
    reuse)", cdn.openai.com/API/docs/realtime-prompting-guide.pdf, read 23 Nov 2026). Read by
    words, so it works in any language; every line after the first with the tag is named."""
    groups = _line_groups(script, procedure=True)
    problems: list[str] = []
    for n, group in enumerate(groups):
        small_steps = n == len(groups) - 1
        size = _SMALL_STEP_ENDING_WORDS if small_steps else _ENDING_WORDS
        endings: dict[str, list[str]] = {}
        seen: set[str] = set()
        for _i, path, text in group:
            # A line said again word for word is `repeated_line_problems`' finding, not a tag.
            flat = " ".join(text.casefold().split())
            if flat in seen:
                continue
            seen.add(flat)
            ending = line_ending(text, size)
            if ending is not None:
                endings.setdefault(ending, []).append(path)
        for paths in endings.values():
            if small_steps and (
                len(paths) < _SMALL_STEP_ENDING_REPEATS or 2 * len(paths) < len(group)
            ):
                continue
            if len(paths) >= _ENDING_REPEATS:
                problems += [
                    f"{path}: ends with the same words as another step's line; the agent "
                    "copies them into every reply. End it where its point ends."
                    for path in paths[1:]
                ]
    return problems


#: The parts of a step's examples in one language (`StepExamples`), in the order shown.
EXAMPLE_PARTS: Final = ("turns", "confused", "stuck", "busy")


def example_lines(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of each example turn of each step in each language
    (`ConversationStage.examples`): `stages.N.examples.<tag>.turns.M`, `.confused`, `.stuck`
    and `.busy`. The in-call model copies examples more closely than any rule (DESIGN §2.3),
    so every check that reads a line the agent says reads these."""
    out: list[tuple[str, str]] = []
    for i, stage in enumerate(script.stages):
        for tag, said in stage.examples.items():
            at = f"stages.{i}.examples.{tag}"
            out += [(f"{at}.turns.{m}", turn) for m, turn in enumerate(said.turns) if turn.strip()]
            out += [
                (f"{at}.{part}", text)
                for part in EXAMPLE_PARTS[1:]
                if (text := getattr(said, part)).strip()
            ]
    return out


def _guiding_lines(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of the lines that walk the person through something: each step's line
    and its line in each call language, each small step, and the sample phrases. The
    openings are not among them."""
    return [
        *(line for i in range(len(script.stages)) if (line := step_line(script, i))[1].strip()),
        *scenario_lines(script),
        *(
            (f"stages.{i}.procedure.{j}.action", step.action)
            for i, stage in enumerate(script.stages)
            for j, step in enumerate(stage.procedure)
            if step.action.strip()
        ),
        *(
            (f"style.sample_phrases.{i}", phrase)
            for i, phrase in enumerate(script.style.sample_phrases)
            if phrase.strip()
        ),
    ]


def asks_when_done_problems(script: CallScript) -> list[str]:
    """A line that ends by asking the person to say when a step is done (`asks_when_done`)."""
    return [
        f'{path}: ends by asking them to say when it is done ("{tail}"); they say so on their '
        "own. End the line on the action itself, with no question after it."
        for path, text in _guiding_lines(script)
        if (tail := asks_when_done(text)) is not None
    ]


def stacked_line_problems(script: CallScript) -> list[str]:
    """A line that gives more than one thing to do in one turn (`stacked_line`)."""
    return [
        f"{path}: gives more than one thing to do in one turn; say only the next action, in a "
        "few words, and stop, so they do it before the next one."
        for path, text in _guiding_lines(script)
        if stacked_line(text)
    ]


def scenario_lines(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of each step's own line in each language (`ConversationStage.scripts`)
    and each of its example turns (`example_lines`), which the in-call model uses as what to
    say at that step."""
    return [
        *(
            (f"stages.{i}.scripts.{tag}", text)
            for i, stage in enumerate(script.stages)
            for tag, text in stage.scripts.items()
            if text.strip()
        ),
        *example_lines(script),
    ]


#: `stages.N.scripts.<tag>` or `stages.N.examples.<tag>.…`: the language tag a line is in.
_TAGGED_PATH: Final = re.compile(r"^stages\.\d+\.(?:scripts|examples)\.([A-Za-z]{2,3}-[A-Za-z]{2})")


def line_language(path: str, default: str = "") -> str:
    """The language a line at `path` is in: its tag for a step's line or example in a named
    language, else `default` (the call's language)."""
    found = _TAGGED_PATH.match(path)
    return found.group(1) if found else default


def answer_lines(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of each answer a step gives a caller's question, in English and in each
    other language."""
    out: list[tuple[str, str]] = []
    for i, stage in enumerate(script.stages):
        for j, qa in enumerate(stage.qa):
            out.append((f"stages.{i}.qa.{j}.answer", qa.answer))
            out += [
                (f"stages.{i}.qa.{j}.translations.{tag}.answer", said.answer)
                for tag, said in qa.translations.items()
                if said.answer.strip()
            ]
    return out


def agent_lines(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of every line the agent says or copies: the spoken fields but the caller's
    example lines, each step's lines by language, and its answers."""
    callers = caller_paths(script)
    return [
        *((p, t) for p, t in spoken_fields(script) if t.strip() and p not in callers),
        *scenario_lines(script),
        *answer_lines(script),
    ]


#: `stages.N.qa.M.answer` is the English answer (`ScenarioQa`); each language's is under
#: `translations.<tag>`.
_ENGLISH_ANSWER: Final = re.compile(r"^stages\.\d+\.qa\.\d+\.answer$")
_TRANSLATED_ANSWER: Final = re.compile(
    r"^stages\.\d+\.qa\.\d+\.translations\.([A-Za-z]{2,3}-[A-Za-z]{2})\."
)


def own_script_line_problems(script: CallScript, context: LintContext) -> list[str]:
    """A line the agent says, in a call language with letters of its own, written with none
    of them or holding an English sentence (`spoken_guard.own_script_problem`, the rule the
    opening writer holds its line to). Production, 27 Nov 2026: a campaign's lines came back in
    romanised Telugu, and a Telugu line carried a whole English sentence. Every line the agent
    says or copies is read, the openings and an owner's own lines included, each in its own
    language (`line_language`)."""
    names = (context.business_name, context.agent_name)
    found: list[str] = []
    for path, text in agent_lines(script):
        if _ENGLISH_ANSWER.match(path):
            continue
        tagged = _TRANSLATED_ANSWER.match(path)
        language = tagged.group(1) if tagged else line_language(path, context.language)
        if (problem := own_script_problem(path, text, language, names=names)) is not None:
            found.append(problem)
    return found


def romanised_instruction_problems(script: CallScript) -> list[str]:
    """An instruction to the in-call model, or a quick fact, written as an Indian language in
    English letters (`spoken_guard.reads_as_romanised`). These fields are plain English by
    the founder's language-pack decision of 19 Oct 2026 (`spoken_guard`'s module docstring,
    `workers/step_writer.FRAME_INSTRUCTION`): the model says them in the call language in its
    own words. Production, 27 Nov 2026: a campaign's push-back answers and quick facts were
    romanised Telugu, which is neither. Not the native-letter case: an instruction in Telugu
    letters is the owner's to keep (`spoken_guard.english_problem` binds only the AI)."""
    fields = [
        *instruction_fields(script),
        *((f"faqs.{i}.answer", faq.answer) for i, faq in enumerate(script.faqs)),
    ]
    return [
        f"{path}: is written in an Indian language in English letters; write it in plain "
        "English, which the agent says in the call language in its own words."
        for path, text in fields
        if text.strip() and reads_as_romanised(text)
    ]


#: An invitation to reach the business by message, or by phone: the contact channel a line
#: gives the person. English only, because the ending and a step's instruction are English
#: (`romanised_instruction_problems`); a line in Telugu or Hindi letters is not read for it
#: until those words are written and reviewed by a native speaker (`call_words.json`).
_MESSAGE_US: Final = re.compile(
    r"\b(?:message|text|msg|whats\s?app)\s+(?:us|the\s+(?:team|office|business))\b"
    r"|\b(?:send|drop|leave)\s+(?:us\s+)?an?\s+(?:message|text|whats\s?app)\b"
    r"|\b(?:message|text|write to|reach|contact)\s+us\s+on\s+whats\s?app\b",
    re.IGNORECASE,
)
_CALL_US: Final = re.compile(
    r"\b(?:call|phone|ring)\s+(?:us|the\s+(?:team|office|shop|store|helpline))\b"
    r"|\bgive\s+us\s+a\s+(?:call|ring)\b"
    r"|\bcall\s+(?:on\s+)?(?:this|our)\s+number\b",
    re.IGNORECASE,
)
CONTACT_CHANNELS: Final[dict[str, re.Pattern[str]]] = {"message": _MESSAGE_US, "call": _CALL_US}


def contact_channels(text: str) -> frozenset[str]:
    """The ways `text` tells the person to reach the business ("message", "call"), each read
    only in a clause that does not itself say not to ("don't call us, message us on
    WhatsApp" gives the person one way)."""
    found: set[str] = set()
    for sentence in re.split(r"(?<=[.?!।])\s+", text):
        for clause in _CLAUSE_BREAK.split(sentence):
            if not clause or _NEGATED.search(clause):
                continue
            found.update(
                name for name, pattern in CONTACT_CHANNELS.items() if pattern.search(clause)
            )
    return frozenset(found)


#: A bracketed aside, or a lone bracket. Every character of a line the agent copies is
#: spoken (D-739), so "యాడ్ టు హోమ్ స్క్రీన్ (Add to Home screen)" is said twice, once with its
#: brackets read as pauses. Curly braces are merge fields (`{{name}}`) and are not brackets.
BRACKETED: Final = re.compile(r"\[[^\]]{0,200}\]|\([^()]{0,200}\)|[\[\]()]")


def bracket_problems(script: CallScript) -> list[str]:
    """A line the agent says or copies (`agent_lines`, and the small steps it walks a caller
    through) holding a bracket: the in-call model copies the line, brackets and the repeat
    inside them included, into what the caller hears."""
    lines = [
        *agent_lines(script),
        *(
            (f"stages.{i}.procedure.{j}.action", step.action)
            for i, stage in enumerate(script.stages)
            for j, step in enumerate(stage.procedure)
        ),
    ]
    return [
        f'{path}: has "{found.group(0)}" in brackets, which the voice reads out; say it once, '
        "in the call language, with no brackets."
        for path, text in lines
        if (found := BRACKETED.search(text)) is not None
    ]


def empty_title_problems(script: CallScript) -> list[str]:
    """A line the agent says that puts an honorific where the person's name belongs with no
    name (`spoken_guard.empty_title`); the openings are the opening writer's to judge."""
    return [
        f'{path}: says "{title}" where the person\'s name belongs, with no name; put '
        f"{NAME_FIELD} before it or leave both out."
        for path, text in agent_lines(script)
        if path not in OPENING_FIELDS and (title := empty_title(text))
    ]


def unreached_steps(script: CallScript) -> list[int]:
    """The steps, by index, that no way out from the first step ever reaches."""
    if len(script.stages) < 2:
        return []
    reached = reachable_steps(script, 0) | {0}
    return [i for i in range(len(script.stages)) if i not in reached]


def unreachable_problems(script: CallScript) -> list[str]:
    return [
        f'stages.{i}: no way out of another step leads to "{script.stages[i].name}", so the '
        "call never reaches it; give the step before it a way out whose condition says when "
        "this one is needed, or leave it out."
        for i in unreached_steps(script)
    ]


def step_numbers_broken(script: CallScript) -> bool:
    """Whether the stages' step numbers do not read as the call's steps: some numbered and
    some not, out of list order, or with a number skipped."""
    steps = [stage.step for stage in script.stages]
    if all(step is None for step in steps):
        return False
    if any(step is None for step in steps):
        return True
    numbers = [step or 0 for step in steps]
    return numbers != sorted(numbers) or sorted(set(numbers)) != list(range(1, max(numbers) + 1))


def step_number_problems(script: CallScript) -> list[str]:
    if not step_numbers_broken(script):
        return []
    return [
        "stages: the step numbers do not follow the call; number the steps 1, 2, 3 in call "
        "order, and give scenarios that are other ways of the same moment the same number."
    ]


def step_outcome_problems(script: CallScript) -> list[str]:
    """An outcome for a step the script does not have, and, once any step has an outcome, a
    step with none."""
    if not script.step_outcomes:
        return []
    steps = set(stage_steps(script.stages))
    named = {o.step for o in script.step_outcomes}
    return [
        *(
            f"step_outcomes: step {step} has an outcome and no scenario; leave it out."
            for step in sorted(named - steps)
        ),
        *(
            f"step_outcomes: step {step} has no outcome; say in one sentence what is true "
            "once that step is done."
            for step in sorted(steps - named)
        ),
    ]


#: A step that asks the person when to call them back. Read in the English instruction.
_ASKS_A_TIME: Final = re.compile(
    r"\b(?:better|convenient|suitable|good|preferred|another|later) (?:time|day)\b|"
    r"\bwhen (?:to|we (?:can|should)|i (?:can|should)|they (?:want|would like) (?:us )?to) "
    r"call\b|\bcall (?:them |you )?(?:back )?later\b",
    re.IGNORECASE,
)


def asks_a_time(stage: ConversationStage) -> bool:
    return stage.mode == "guide" and bool(_ASKS_A_TIME.search(stage.instruction))


def untaken_time_problems(script: CallScript) -> list[str]:
    """A step that asks when to call the person back but notes nothing and goes nowhere with
    the answer: the time is lost and nobody calls."""
    problems: list[str] = []
    for i, stage in enumerate(script.stages):
        if not asks_a_time(stage):
            continue
        exits = {stage.otherwise, *(b.target for b in stage.branches)}
        if not stage.collect or CALL_BACK not in exits:
            problems.append(
                f"stages.{i}.collect: asks for a time to call back but does not note it or "
                "go to call_back with it; collect the time they give and go to call_back."
            )
    return problems


_LATIN_RUN: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[ \-][A-Za-z][A-Za-z0-9]*){0,3}")


def _squashed(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text).casefold()


def unpronounced_spellings(script: CallScript, context: LintContext) -> list[tuple[str, str]]:
    """(spelling, say_as) for each spelling of a word the script teaches the voice to say that
    a line the agent speaks writes differently ("Rytu khata" where the pronunciation is for
    "RytuKhata"), anywhere the agent speaks: the script's lines and its AI and recording
    sentences. Spellings are compared without case, spaces or hyphens."""
    taught = {_squashed(p.word): p.say_as for p in script.style.pronunciations}
    have = {p.word.strip().casefold() for p in script.style.pronunciations}
    found: dict[str, tuple[str, str]] = {}
    texts = [t for _p, t in agent_lines(script)] + list(context.spoken_elsewhere)
    for text in texts:
        for run in _LATIN_RUN.finditer(text):
            words = re.split(r"([ \-])", run.group(0))
            # Every stretch of one to four words in the run, so "the Rytu khata app" finds
            # "Rytu khata".
            tokens = words[::2]
            for start in range(len(tokens)):
                for end in range(start + 1, min(start + 4, len(tokens)) + 1):
                    spelling = "".join(words[start * 2 : end * 2 - 1])
                    say_as = taught.get(_squashed(spelling))
                    folded = spelling.casefold()
                    if say_as is not None and folded not in have and folded not in found:
                        found[folded] = (spelling, say_as)
    return list(found.values())


def pronunciation_problems(script: CallScript, context: LintContext) -> list[str]:
    return [
        f'style.pronunciations: a line says "{spelling}", which no pronunciation covers; add '
        "it with the same sound as its other spelling."
        for spelling, _say in unpronounced_spellings(script, context)
    ]


#: A conditional sentence of an English instruction, condition first ("If they cannot, offer
#: to call back") or action first ("End politely if they are not interested"). "unless" is
#: left out: its condition is the negation of what it says, which code cannot write.
_CONDITION_FIRST: Final = re.compile(
    r"^(?:\w+\s+)?(?:if|when|whenever|in case)\s+(?P<cond>[^,]{2,200}?)\s*(?:,|\bthen\b)"
    r"\s*(?P<act>.+)$",
    re.IGNORECASE,
)
_ACTION_FIRST: Final = re.compile(
    r"^(?P<act>.+?)\s+(?:if|when|whenever|in case)\s+(?P<cond>.{2,200})$", re.IGNORECASE
)
#: An action that tells the agent NOT to take the way out ("do not end the call").
_ACTION_NEGATED: Final = re.compile(r"\b(?:do not|don'?t|never|not|without)\b", re.IGNORECASE)
#: The ways out a stated action names, each to a branch target (`call_script.SPECIAL_TARGETS`).
_WAY_OUT_ACTIONS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (CALL_BACK, re.compile(r"\bcall[\s-]?(?:them\s+)?back\b|\bcallback\b", re.IGNORECASE)),
    (
        HAND_OVER,
        re.compile(
            r"\bhand(?:s|ing)?\s+(?:them\s+|the\s+call\s+|it\s+)?over\b|"
            r"\btransfer\s+(?:them|the\s+call|it)\b|\bput\s+them\s+through\b|"
            r"\bconnect\s+them\s+(?:to|with)\b",
            re.IGNORECASE,
        ),
    ),
    (
        END_OF_CALL,
        re.compile(
            r"\bend(?:s|ing)?\s+(?:the\s+call\b|it\b|politely\b)|"
            r"\bclose\s+(?:the\s+call\b|politely\b)|\bhang\s+up\b|\bsay\s+goodbye\b",
            re.IGNORECASE,
        ),
    ),
)


def stated_ways_out(
    stage: ConversationStage, *, last_step: bool, manifest: CapabilityManifest | None
) -> list[StageBranch]:
    """The ways out `stage`'s instruction states as conditions in words ("If they cannot,
    offer to call back") that the stage does not have as a way out, each as the branch it
    should be: the condition as written, to the call back, the end or a person.

    The call flow draws and the engine is sent only a stage's branches, so a way out left in
    the instruction is one nobody sees on the canvas. Leaves out: an end in the call's last
    step, where the call ends anyway; a hand to a person on an agent with hand-over off, a
    promise `unbacked_promise` already reports; and any past `MAX_STAGE_BRANCHES`. A call back
    is wired whatever the account can do, as every call-back branch is: it compiles to what
    the account can do at publish (`call_script._target_action`)."""
    has = {stage.otherwise, *(b.target for b in stage.branches)}
    room = MAX_STAGE_BRANCHES - len(stage.branches)
    out: list[StageBranch] = []
    for sentence in re.split(r"(?<=[.?!;])\s+|;\s*", " ".join(stage.instruction.split())):
        text = sentence.strip().rstrip(".?!;").strip()
        found = _CONDITION_FIRST.match(text) or _ACTION_FIRST.match(text)
        if found is None:
            continue
        act, cond = found.group("act"), found.group("cond").strip(" ,")
        # "If they agree, explain it and end politely when they are done": two conditions,
        # and which one the way out hangs on is a guess, so the sentence is left as written.
        if _ACTION_FIRST.match(act) or _ACTION_FIRST.match(cond):
            continue
        for target, verb in _WAY_OUT_ACTIONS:
            hit = verb.search(act)
            if hit is None or _ACTION_NEGATED.search(act[: hit.start()]):
                continue
            if (
                target in has
                or (target == END_OF_CALL and last_step)
                or (target == HAND_OVER and manifest is not None and not manifest.hand_over)
                or len(out) >= room
            ):
                break
            has.add(target)
            out.append(StageBranch(when=(cond[:1].upper() + cond[1:])[:300], target=target))
            break
    return out


_ENDS_CALL: Final = dict(_WAY_OUT_ACTIONS)[END_OF_CALL]


def closes_the_call(stage: ConversationStage) -> bool:
    """Whether `stage` is a close by its role: its way on, when no way out holds, is the end
    of the call, or its instruction says outright to end it ("Thank them and close the
    call"). An end on a condition ("If they are busy, end the call") is a way out, not a
    close."""
    if stage.otherwise == END_OF_CALL:
        return True
    for sentence in re.split(r"(?<=[.?!;])\s+|;\s*", " ".join(stage.instruction.split())):
        text = sentence.strip().rstrip(".?!;").strip()
        if not text or _CONDITION_FIRST.match(text) or _ACTION_FIRST.match(text):
            continue
        hit = _ENDS_CALL.search(text)
        if hit is not None and not _ACTION_NEGATED.search(text[: hit.start()]):
            return True
    return False


def unwired_way_out_problems(
    script: CallScript, manifest: CapabilityManifest | None = None
) -> list[str]:
    """A way out written in a step's instruction but not given as a way out
    (`stated_ways_out`). Code wires it (`script_structure.ways_out_wired`), so it is
    `script_problems`' alone, never the writer's to repair."""
    steps = stage_steps(script.stages)
    last = max(steps, default=0)
    return [
        f'stages.{i}.branches: the instruction says what to do when "{way.when}", but that '
        f"is not a way out of the step, so the call flow does not show it; give the step a "
        f"way out to {way.target} whose condition says so."
        for i, (stage, step) in enumerate(zip(script.stages, steps, strict=True))
        for way in stated_ways_out(stage, last_step=step == last, manifest=manifest)
    ]


def flow_problems(script: CallScript) -> list[str]:
    """What the whole call's shape gets wrong: a placeholder step, a question asked before
    the caller can answer it, the same thing said twice, a step that redoes the opening,
    lines that all open alike, a step nothing leads to, outcomes that do not match the steps,
    a title said with no name, and a bracket in a spoken line. Broken step numbers and a
    call-back time asked and lost are `script_problems`' alone, not the writer's to repair:
    code mends both before the owner reads a draft (`script_structure.renumbered`,
    `time_taken`), and a new draft has no `collect` to answer the second with."""
    return [
        *placeholder_problems(script),
        *order_problems(script),
        *repeated_line_problems(script),
        *opening_redone_problems(script),
        *same_opener_problems(script),
        *same_ending_problems(script),
        *asks_when_done_problems(script),
        *stacked_line_problems(script),
        *unreachable_problems(script),
        *step_outcome_problems(script),
        *empty_title_problems(script),
        *bracket_problems(script),
    ]


# --- the shape checks of 25 Nov 2026, by the names the script-writer scorer reads ----------
# (`scripts/eval_script_writer.py` adopts any one- or two-argument `<check>_problems` here).
# They live in `script_shape`, which imports this module, hence the imports inside.


def multi_question_line_problems(script: CallScript) -> list[str]:
    """A line the agent says or copies that asks more than one thing (`asks_count`)."""
    return [
        f"{path}: asks {asked} questions; ask one and wait."
        for path, text in agent_lines(script)
        if path not in OPENING_FIELDS and (asked := asks_count(text)) > 1
    ]


def multi_action_line_problems(script: CallScript) -> list[str]:
    """A line giving more than one thing to do in one turn, by the one check the registry
    runs for it (`stacked_line_problems`), under the name the writer eval reads."""
    return stacked_line_problems(script)


def agent_claims_caller_action_problems(script: CallScript) -> list[str]:
    from apps.api.agents.script_shape import caller_action_claimed_problems

    return caller_action_claimed_problems(script)


def fake_branch_problems(script: CallScript) -> list[str]:
    from apps.api.agents.script_shape import echo_problems, named_way_problems

    return [*echo_problems(script), *named_way_problems(script)]


def steps_after_close_problems(script: CallScript) -> list[str]:
    from apps.api.agents.script_shape import trailing_problems

    return trailing_problems(script)


def judged_field_asked_problems(
    script: CallScript, context: LintContext | None = None
) -> list[str]:
    """A step that collects a detail judged from the call (`extraction.whole_call_detail`),
    which code takes out of a Pip script (`script_structure.without_judged_asks`), and an
    instruction or line that asks one of the job's judged details (`context.judged`,
    `script_shape.judged_ask_problems`)."""
    from calevate_shared.extraction import whole_call_detail

    from apps.api.agents.script_shape import judged_ask_problems

    return [
        *(
            f'stages.{i}.collect: collects "{collected_label(entry)}", which is worked out '
            "after the call, never asked."
            for i, stage in enumerate(script.stages)
            for entry in stage.collect
            if whole_call_detail("", collected_label(entry))
        ),
        *judged_ask_problems(script, context.judged if context is not None else ()),
    ]


def known_value_asked_problems(script: CallScript) -> list[str]:
    """A step's line asking the name the opening already greets them by."""
    from apps.api.agents.mistake_lints import known_name_problems

    return known_name_problems(script)


__all__ = [
    "BRACKETED",
    "CONTACT_CHANNELS",
    "NAME_FIELD",
    "NAME_PLACEMENT_RULE",
    "OPENING_FIELDS",
    "PLACED_OPENING_BRIEF",
    "CapabilityManifest",
    "LintContext",
    "OwnerRule",
    "OwnerRuleKind",
    "agent_claims_caller_action_problems",
    "agent_lines",
    "answer_lines",
    "answered_opening",
    "asks_a_time",
    "asks_caller_to_act",
    "asks_count",
    "asks_when_done",
    "asks_when_done_problems",
    "bracket_problems",
    "breaks_owner_rule",
    "caller_paths",
    "closes_the_call",
    "collected_label",
    "contact_channels",
    "empty_title_problems",
    "fake_branch_problems",
    "flow_problems",
    "instruction_fields",
    "instruction_problems",
    "judged_field_asked_problems",
    "known_value_asked_problems",
    "line_ending",
    "line_opener",
    "listed_asks",
    "multi_action_line_problems",
    "multi_question_line_problems",
    "name_segment_problem",
    "names_caller_action",
    "next_steps",
    "offers_call_back",
    "opening_redone_problems",
    "order_problems",
    "other_persona",
    "own_script_line_problems",
    "owner_prohibitions",
    "owner_rule_problem",
    "owner_rules",
    "placed_call_opening",
    "placed_opening_problem",
    "placeholder_instruction",
    "placeholder_problems",
    "plain",
    "presumed_lines",
    "pronunciation_problems",
    "question_count",
    "reachable_steps",
    "repeated_line_problems",
    "romanised_instruction_problems",
    "same_ending_problems",
    "same_opener_problems",
    "scenario_lines",
    "script_problems",
    "spoken_fields",
    "spoken_line_problems",
    "stacked_actions",
    "stacked_line",
    "stacked_line_problems",
    "stated_ways_out",
    "step_line",
    "step_number_problems",
    "step_numbers_broken",
    "step_outcome_problems",
    "steps_after_close_problems",
    "tells_caller_to_act",
    "unasked_details",
    "unasked_problems",
    "unbacked_promise",
    "unknown_figure",
    "unpronounced_spellings",
    "unreachable_problems",
    "unreached_steps",
    "untaken_time_problems",
    "unwired_way_out_problems",
]
