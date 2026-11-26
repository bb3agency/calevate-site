"""The one registry of script checks (script rebuild DESIGN §3.4, 26 Nov 2026).

Every check on what a call script makes the agent say or do is defined once here: its id, the
fields it reads, the languages and letters its detector understands, where its detection
words live (`call_words.json`, never prompt text), its severity and its repair message, and
the call-mistake kind (`call_mistakes.LESSONS`) a line it faults causes on a real call. The
detectors themselves stay in the modules that own their rules (`script_lint`,
`mistake_lints`, `script_shape`, `call_rules`, `owner_plan`); the per-line ones are the same
`turn_checks` functions the after-call review runs on the agent's real turns, so a script
check and a real call cannot disagree about what the mistake is.

`run(script, context, paths)` is the only way any path asks:

* the writer and its repair rounds, through `writer_findings` (every finding is repaired);
* the healer's line repair (`script_heal.heal_findings`) and the healer's VERIFY of a call
  mistake fix (`workers/mistake_fix`), which both read `script_heal.kind_findings`, so a fix
  the heal pass reports clean is one VERIFY reads clean;
* the owner's Save and Keep, which never refuse on a check: what is found is the warnings
  the holder's checks endpoint shows (`script_gate.holder_findings`);
* Put it live and Start, which refuse while a `block` check finds something
  (`script_gate.refuse_if_blocked`, `campaigns.service.launch_blockers`).

SEVERITY. `block` is kept for what is wrong on every call it reaches, whoever wrote the line:
a bracket the voice reads out, a step kept as a placeholder, a step that asks again whether
now is a good time after the opening asked (26 Nov 2026 call: three times), a line that asks
"is it done?" in the same breath as the action, a claim of earlier contact the person never
had, and a promise the account cannot keep. Everything else is `warn`: the owner sees it and
Pip repairs it, but a line that MAY cause a mistake never stops a script going live
(D-989). The checks whose meaning is a legal duty (the AI and recording notices, the truthful
answers, confidentiality) are not here: they are composed into every prompt and verified on
every publish (`compose_engine_prompt`, `verification.verify_publish`), never left to a
script check.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from calevate_shared.call_script import CallScript
from calevate_shared.spoken_guard import has_indic_letters, latin_word_problem

from apps.api.agents import mistake_lints as ml
from apps.api.agents import script_shape
from apps.api.agents.call_rules import opening_redone_line_problems, reacted_line_problems
from apps.api.agents.owner_plan import OwnerPlan, plan_problems
from apps.api.agents.script_lint import (
    OPENING_FIELDS,
    LintContext,
    agent_lines,
    asks_when_done_problems,
    bracket_problems,
    caller_paths,
    empty_title_problems,
    figure_problem,
    instruction_fields,
    opening_redone_problems,
    opening_shape_problems,
    order_problems,
    persona_problem,
    placeholder_problems,
    promise_problem,
    promo_problem,
    pronunciation_problems,
    questions_problem,
    repeated_line_problems,
    same_ending_problems,
    same_opener_problems,
    spoken_fields,
    stacked_instruction_problem,
    stacked_line_problems,
    step_number_problems,
    step_outcome_problems,
    unasked_problems,
    unreachable_problems,
    untaken_time_problems,
    unwired_way_out_problems,
)

Severity = Literal["block", "warn"]
#: What a check reads. `opening`: the two openings; `instruction`: a step's English
#: instruction; `sounds_like`: the legacy one line a step; `scripts`: a step's line per
#: language; `examples`: `stages.N.examples.<tag>.turns.M`, `.confused`, `.stuck`, `.busy`;
#: `procedure`: `stages.N.procedure.M.action`; `qa`: a step's answers; `style`: sample
#: phrases and the example call; `structure`: the step graph, outcomes, collect and
#: pronunciations, which no line holds.
Reads = Literal[
    "opening",
    "instruction",
    "sounds_like",
    "scripts",
    "examples",
    "procedure",
    "qa",
    "style",
    "structure",
]
#: The letters a check reads a Telugu or Hindi line in: the language's own (`native`) and
#: English letters (`latin`, romanised speech).
Letters = Literal["native", "latin"]

ANY_LANGUAGE: Final = frozenset({"te", "hi", "en"})
ENGLISH: Final = frozenset({"en"})
BOTH_LETTERS: Final = frozenset[Letters]({"native", "latin"})
NATIVE: Final = frozenset[Letters]({"native"})
LATIN: Final = frozenset[Letters]({"latin"})
#: Every line field a step has: what the shared line reader (`script_lint.agent_lines`) walks.
LINES: Final = frozenset[Reads]({"opening", "sounds_like", "scripts", "examples", "qa", "style"})
STEP_LINES: Final = frozenset[Reads]({"sounds_like", "scripts", "examples", "qa", "style"})


@dataclass(frozen=True, slots=True)
class CheckContext:
    """What a script is checked against: the lint context (the agent's names, the
    capabilities, the facts, the call language, the job's details) and, for the writer, the
    owner's step plan."""

    lint: LintContext = field(default_factory=LintContext)
    plan: OwnerPlan | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    """One fault: where (`path`, a script JSON path), what (`problem`, the repair message
    worded for that line), which check found it, and how hard it stops the script."""

    check: str
    path: str
    problem: str
    severity: Severity
    #: The line the finding is about, as the script holds it; "" for a place that is not
    #: one line (the step graph, a step's ways out, the whole script).
    line: str = ""

    @property
    def text(self) -> str:
        """The finding as every repair, key and path reader takes it: "<path>: <problem>"."""
        return f"{self.path}: {self.problem}"

    def __str__(self) -> str:
        return self.text


Detect = Callable[[CallScript, CheckContext], Iterable[str]]


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    reads: frozenset[Reads]
    #: The base languages the detector understands; a line in another is not read by it.
    languages: frozenset[str]
    letters: frozenset[Letters]
    severity: Severity
    #: The repair in the form every message of this check takes; the finding's own text
    #: names the line and what in it to change.
    repair: str
    #: Where its words come from: `call_words.json` keys, or "structure" / "digits" / "code
    #: (English)" for a detector that reads no word list.
    words: str
    detect: Detect
    #: The call mistake a line it faults causes (`call_mistakes.LESSONS`), for the healer.
    mistake: str | None = None
    #: False for a check whose repair needs knowledge the healer does not hold (the owner's
    #: own prices): the owner sees it, the healer never rewrites the line for it.
    heals: bool = True
    #: Part of the call's shape (`script_lint.flow_problems`), which the writer refuses on
    #: its own and `script_mistakes` leaves to that refusal.
    flow: bool = False
    #: A check that also faults what this one does on some lines: where both fault one
    #: line, only that check's finding stands, so a repair hears one problem per line.
    defers_to: str | None = None


def _lint(check: Callable[[CallScript], list[str]]) -> Detect:
    def detect(script: CallScript, _ctx: CheckContext) -> list[str]:
        return check(script)

    return detect


def _with_lint(check: Callable[[CallScript, LintContext], list[str]]) -> Detect:
    def detect(script: CallScript, ctx: CheckContext) -> list[str]:
        return check(script, ctx.lint)

    return detect


def _spoken(rule: Callable[[str, str, LintContext], str | None]) -> Detect:
    """A rule of one line run over every line the agent says or copies (`agent_lines`)."""

    def detect(script: CallScript, ctx: CheckContext) -> list[str]:
        return [
            problem
            for path, text in agent_lines(script)
            if (problem := rule(path, text, ctx.lint)) is not None
        ]

    return detect


def _promo(script: CallScript, ctx: CheckContext) -> list[str]:
    if script.raw_override is not None:
        found = promo_problem("script", script.raw_override, ctx.lint, spoken=False)
        return [found] if found else []
    return [
        *(
            problem
            for path, text in agent_lines(script)
            if (problem := promo_problem(path, text, ctx.lint, spoken=True))
        ),
        *(
            problem
            for path, text in instruction_fields(script)
            if text.strip() and (problem := promo_problem(path, text, ctx.lint, spoken=False))
        ),
    ]


def _promise(script: CallScript, ctx: CheckContext) -> list[str]:
    if script.raw_override is not None:
        found = promise_problem("script", script.raw_override, ctx.lint, spoken=False)
        return [found] if found else []
    return [
        *(
            problem
            for path, text in agent_lines(script)
            if (problem := promise_problem(path, text, ctx.lint, spoken=True))
        ),
        *(
            problem
            for path, text in instruction_fields(script)
            if text.strip() and (problem := promise_problem(path, text, ctx.lint, spoken=False))
        ),
    ]


def _opening_shape(script: CallScript, ctx: CheckContext) -> list[str]:
    return [
        problem
        for path, text in agent_lines(script)
        if path in OPENING_FIELDS
        for problem in opening_shape_problems(path, text, ctx.lint)
    ]


def _several_actions(script: CallScript, _ctx: CheckContext) -> list[str]:
    """More than one thing to do in one turn: in a step's English instruction, whose fix is
    the step-by-step list, and in any line the agent says, in any language
    (`script_lint.stacked_line`)."""
    return [
        *(
            problem
            for i, stage in enumerate(script.stages)
            if (
                problem := stacked_instruction_problem(f"stages.{i}.instruction", stage.instruction)
            )
        ),
        *stacked_line_problems(script),
    ]


def _latin_words(script: CallScript, ctx: CheckContext) -> list[str]:
    """English letters inside a line in the call's own letters (D-861). The in-call model
    copies a step's line, English letters included (Rytu Khata call of 9 Nov 2026: "Android"
    and "iPhone"), so an owner's line written before D-861 or by hand is shown too. A line
    wholly in English is `wrong_language`'s: the language the owner chose to write it in."""
    callers = caller_paths(script)
    names = (ctx.lint.business_name, ctx.lint.agent_name)
    return [
        problem
        for path, text in spoken_fields(script)
        if text.strip()
        and path not in callers
        and has_indic_letters(text)
        and (problem := latin_word_problem(path, text, ctx.lint.language, names=names))
    ]


def _unasked(script: CallScript, ctx: CheckContext) -> list[str]:
    return unasked_problems(script, ctx.lint.collect, ctx.lint.call_back)


def _judged_asks(script: CallScript, ctx: CheckContext) -> list[str]:
    return script_shape.judged_ask_problems(script, ctx.lint.judged)


def _unwired(script: CallScript, ctx: CheckContext) -> list[str]:
    return unwired_way_out_problems(script, ctx.lint.manifest)


def _plan(script: CallScript, ctx: CheckContext) -> list[str]:
    return plan_problems(script, ctx.plan)


_ONE_ACTION: Final = (
    "Give one action and stop; the caller says when it is done, and the next turn gives the "
    "next one."
)

#: Every check, in the order findings are reported (and repaired): the call's shape first,
#: then what the lines say.
CHECKS: Final[tuple[Check, ...]] = (
    Check(
        "placeholder_step",
        frozenset({"instruction"}),
        ENGLISH,
        LATIN,
        "block",
        "Take the step out, or give it something to do.",
        "code (English)",
        _lint(placeholder_problems),
        flow=True,
    ),
    Check(
        "order",
        frozenset({"instruction", "sounds_like", "structure"}),
        ENGLISH,
        LATIN,
        "warn",
        "Ask about using something only after the caller could have used it.",
        "code (English)",
        _lint(order_problems),
        flow=True,
    ),
    Check(
        "repeated_line",
        frozenset({"opening", "sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Explain each thing in one step; have this step move the call on.",
        "structure (shared words)",
        _lint(repeated_line_problems),
        mistake="said_again",
        flow=True,
    ),
    Check(
        "opening_redone",
        frozenset({"instruction"}),
        ENGLISH,
        LATIN,
        "block",
        "Start this step from what comes after the opening; never greet or ask again.",
        "code (English)",
        _lint(opening_redone_problems),
        mistake="opened_again",
        flow=True,
    ),
    Check(
        "same_opener",
        frozenset({"sounds_like", "scripts", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Open each line with its own point.",
        "structure (first words)",
        _lint(same_opener_problems),
        mistake="same_opening",
        flow=True,
    ),
    Check(
        "same_ending",
        frozenset({"sounds_like", "scripts", "examples", "procedure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "End each line where its point ends.",
        "structure (last words)",
        _lint(same_ending_problems),
        mistake="same_closing",
        flow=True,
    ),
    Check(
        "asks_when_done",
        frozenset({"sounds_like", "scripts", "examples", "procedure", "style"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        _ONE_ACTION,
        "script_lint._ASKS_WHEN_DONE",
        _lint(asks_when_done_problems),
        mistake="asks_when_done",
        flow=True,
    ),
    Check(
        "several_actions",
        frozenset({"instruction", "sounds_like", "scripts", "examples", "procedure", "style"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        _ONE_ACTION,
        "script_lint._CALLER_ACTION, _AFTER_CLAUSE",
        _several_actions,
        mistake="several_actions",
        flow=True,
    ),
    Check(
        "unreachable",
        frozenset({"structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Give the step before it a way out that leads here, or leave the step out.",
        "structure",
        _lint(unreachable_problems),
        flow=True,
    ),
    Check(
        "step_outcomes",
        frozenset({"structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Give every step one outcome.",
        "structure",
        _lint(step_outcome_problems),
        flow=True,
    ),
    Check(
        "empty_title",
        frozenset({"sounds_like", "scripts", "examples", "qa", "style"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Put the name field before the title, or leave both out.",
        "spoken_guard honorifics (call_words.json)",
        _lint(empty_title_problems),
        flow=True,
    ),
    Check(
        "brackets",
        frozenset({*LINES, "procedure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "block",
        "Say it once, in the call language, with no brackets.",
        "code (bracket characters)",
        _lint(bracket_problems),
        mistake="brackets",
        flow=True,
    ),
    Check(
        "opening_redone_line",
        frozenset({"sounds_like", "scripts", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "block",
        "Start this step from what comes after their yes; never ask again whether now suits.",
        "turn_checks._ASKS_IF_NOW_SUITS, spoken_guard._GREETING_HEAD",
        _lint(opening_redone_line_problems),
        mistake="opened_again",
    ),
    Check(
        "reacted_line",
        frozenset({"scripts", "examples", "procedure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Start the line with its own point: no reaction first.",
        "turn_checks.stall_words (acknowledgements)",
        _lint(reacted_line_problems),
        mistake="same_opening",
    ),
    Check(
        "too_long",
        STEP_LINES,
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "One point or one question a turn, then let them speak.",
        "turn_checks sentence and question rules",
        _with_lint(ml.too_long_problems),
        mistake="too_long",
    ),
    Check(
        "asked_again",
        frozenset({"sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Ask it once; have this step move on.",
        "turn_checks question rules",
        _with_lint(ml.asked_again_problems),
        mistake="asked_again",
    ),
    Check(
        "reasked_name",
        frozenset({"opening", "sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Use the name the call already has.",
        "turn_checks._ASKS_NAME",
        _with_lint(ml.reasked_name_problems),
        mistake="reasked_name",
    ),
    Check(
        "caller_line",
        STEP_LINES,
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Write only what the agent says; leave the answer to the caller.",
        "turn_checks._LABEL, _ORDER_ENDING",
        _with_lint(ml.caller_line_problems),
        mistake="caller_line",
    ),
    Check(
        "goodbye_while_asking",
        frozenset({"sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Keep goodbye for the close.",
        "turn_checks._GOODBYE",
        _with_lint(ml.goodbye_while_asking_problems),
        mistake="goodbye_while_asking",
    ),
    Check(
        "false_recall",
        frozenset({"opening", *STEP_LINES}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Say the detail itself instead of claiming it was said.",
        "turn_checks._SAID_BEFORE, _PRICE_WORD",
        _with_lint(ml.false_recall_problems),
        mistake="false_recall",
    ),
    Check(
        "wrong_language",
        STEP_LINES,
        frozenset({"te", "hi"}),
        NATIVE,
        "warn",
        "Write it in the call's language.",
        "turn_checks word_languages",
        _with_lint(ml.wrong_language_problems),
        mistake="wrong_language",
    ),
    Check(
        "third_person",
        STEP_LINES,
        ENGLISH,
        LATIN,
        "warn",
        "Speak to the person directly.",
        "turn_checks._THIRD_PERSON",
        _with_lint(ml.third_person_problems),
        mistake="third_person",
    ),
    Check(
        "offered_more_too_soon",
        frozenset({"sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Ask whether they need anything else once, when the task is done.",
        "turn_checks._OFFERS_MORE",
        _with_lint(ml.offered_more_too_soon_problems),
        mistake="offered_more_too_soon",
    ),
    Check(
        "false_history",
        frozenset({"opening", *STEP_LINES}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "block",
        "Say why you are calling without claiming an earlier enquiry.",
        "turn_checks._CLAIMS_HISTORY, _ENQUIRY_WORDS",
        _with_lint(ml.false_history_problems),
        mistake="false_history",
    ),
    Check(
        "stalled",
        frozenset({"sounds_like", "examples"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "End it on the question or next step it leads to.",
        "turn_checks.stall_words (acknowledgements)",
        _with_lint(ml.stalled_problems),
        mistake="stalled",
    ),
    Check(
        "moved_on_unconfirmed",
        frozenset({"structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Give the step an Otherwise.",
        "structure",
        _with_lint(ml.moved_on_unconfirmed_problems),
        mistake="moved_on_unconfirmed",
    ),
    Check(
        "formal_words",
        frozenset({*STEP_LINES, "procedure"}),
        frozenset({"te", "hi"}),
        NATIVE,
        "warn",
        "Use the words callers say.",
        "spoken_style.json textbook lists",
        _with_lint(ml.formal_words_problems),
        mistake="formal_words",
    ),
    Check(
        "asked_done_too_soon",
        frozenset({*STEP_LINES, "procedure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "block",
        _ONE_ACTION,
        "turn_checks._CALLER_DONE, _TE_YES_NO_ENDINGS",
        _with_lint(ml.asked_done_too_soon_problems),
        mistake="asked_done_too_soon",
    ),
    Check(
        "caller_action_claimed",
        STEP_LINES,
        ENGLISH,
        LATIN,
        "warn",
        "Ask them to do it; what they do in the app is theirs.",
        "code (English)",
        _lint(script_shape.caller_action_claimed_problems),
    ),
    Check(
        "judged_ask",
        frozenset({"instruction", *STEP_LINES}),
        ENGLISH,
        LATIN,
        "warn",
        "Ask only what the person can answer.",
        "code (English)",
        _judged_asks,
    ),
    Check(
        "promo",
        frozenset({*LINES, "instruction"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Say only facts the caller asked about, with no offer, discount or urgency.",
        "compliance.call_purpose (en, te, hi lists)",
        _promo,
    ),
    Check(
        "unbacked_promise",
        frozenset({*LINES, "instruction"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "block",
        "Promise only what the account can do; take the details for the team.",
        "script_lint._WHATSAPP, _SMS, _CALL_BACK, _BOOKS, _HANDS_OVER",
        _promise,
    ),
    Check(
        "unknown_figure",
        LINES,
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Leave out a figure no fact of the owner gives.",
        "digits",
        _spoken(figure_problem),
        heals=False,
    ),
    Check(
        "several_questions",
        LINES,
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Ask one thing and wait.",
        "'?' in any language; English lists",
        _spoken(lambda path, text, _lint: questions_problem(path, text)),
        defers_to="too_long",
    ),
    Check(
        "opening_shape",
        frozenset({"opening"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Open with the person's name and one question, reading without the name too.",
        "structure (merge fields, punctuation)",
        _opening_shape,
    ),
    Check(
        "other_persona",
        LINES,
        ENGLISH,
        LATIN,
        "warn",
        "Give the agent its own name.",
        "code (English)",
        _spoken(persona_problem),
    ),
    Check(
        "latin_words",
        frozenset({"opening", "sounds_like", "style"}),
        frozenset({"te", "hi"}),
        NATIVE,
        "warn",
        "Write every word in the call language's letters.",
        "spoken_guard letters",
        _latin_words,
    ),
    Check(
        "unasked_detail",
        frozenset({"instruction", "sounds_like", "structure"}),
        ENGLISH,
        LATIN,
        "warn",
        "Have the step that reaches it ask for each detail the job notes.",
        "code (English stems)",
        _unasked,
    ),
    Check(
        "step_numbers",
        frozenset({"structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Number the steps 1, 2, 3 in call order.",
        "structure",
        _lint(step_number_problems),
    ),
    Check(
        "untaken_time",
        frozenset({"instruction", "structure"}),
        ENGLISH,
        LATIN,
        "warn",
        "Note the time they give and go to call back with it.",
        "code (English)",
        _lint(untaken_time_problems),
    ),
    Check(
        "unwired_way_out",
        frozenset({"instruction", "structure"}),
        ENGLISH,
        LATIN,
        "warn",
        "Give the way out the instruction names as a way out of the step.",
        "code (English)",
        _unwired,
    ),
    Check(
        "pronunciation",
        frozenset({*LINES, "structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Add a pronunciation for each spelling of a taught name.",
        "style.pronunciations",
        _with_lint(pronunciation_problems),
    ),
    Check(
        "owner_plan",
        frozenset({"instruction", "structure"}),
        ANY_LANGUAGE,
        BOTH_LETTERS,
        "warn",
        "Keep the owner's steps, in their order, with their outcomes and ways out.",
        "structure (owner's numbered steps)",
        _plan,
    ),
)

BY_ID: Final[dict[str, Check]] = {check.id: check for check in CHECKS}
assert len(BY_ID) == len(CHECKS), "a check id is registered twice"

#: The call mistakes a script line can cause, each with the checks that find that line.
MISTAKE_CHECKS: Final[dict[str, tuple[str, ...]]] = {
    kind: tuple(c.id for c in CHECKS if c.mistake == kind)
    for kind in dict.fromkeys(c.mistake for c in CHECKS if c.mistake is not None)
}
#: The mistake kinds a script check can trace to the agent's own script.
SCRIPT_FIXABLE_KINDS: Final[frozenset[str]] = frozenset(MISTAKE_CHECKS)
BLOCKING: Final[frozenset[str]] = frozenset(c.id for c in CHECKS if c.severity == "block")
#: The call's shape the writer refuses an answer for while it has repair rounds
#: (`script_assist.shape_problems`): the flow checks, and a step's line that redoes the
#: opening or opens with a reaction.
SHAPE_CHECKS: Final[tuple[str, ...]] = (
    *(c.id for c in CHECKS if c.flow),
    "opening_redone_line",
    "reacted_line",
)
#: What `script_lint.script_problems` (the eval's writer score) has always counted.
SCRIPT_PROBLEM_CHECKS: Final[tuple[str, ...]] = (
    "promo",
    "unbacked_promise",
    "unknown_figure",
    "several_questions",
    "opening_shape",
    "other_persona",
    "latin_words",
    "several_actions",
    "asks_when_done",
    "placeholder_step",
    "order",
    "repeated_line",
    "opening_redone",
    "same_opener",
    "same_ending",
    "unreachable",
    "step_outcomes",
    "empty_title",
    "brackets",
    "step_numbers",
    "untaken_time",
    "unwired_way_out",
    "pronunciation",
    "unasked_detail",
)


def _context(context: CheckContext | LintContext | None) -> CheckContext:
    if context is None:
        return CheckContext()
    if isinstance(context, LintContext):
        return CheckContext(lint=context)
    return context


def _under(path: str, paths: Sequence[str]) -> bool:
    return any(path == p or path.startswith(f"{p}.") for p in paths)


def run(
    script: CallScript,
    context: CheckContext | LintContext | None = None,
    paths: Sequence[str] | None = None,
    *,
    ids: Iterable[str] | None = None,
) -> list[Finding]:
    """Every finding of the registered checks (or of `ids`) on `script`, each once, in
    registry order; with `paths`, only those at or under one of them. A hand-written (raw)
    script has no fields to walk: only the checks that read it as one instruction answer."""
    ctx = _context(context)
    wanted = CHECKS if ids is None else tuple(BY_ID[i] for i in dict.fromkeys(ids))
    found: dict[str, Finding] = {}
    dumped: dict[str, Any] | None = None
    for check in wanted:
        if script.raw_override is not None and check.id not in {"promo", "unbacked_promise"}:
            continue
        for text in check.detect(script, ctx):
            path, _sep, problem = text.partition(": ")
            if text in found or (paths is not None and not _under(path, paths)):
                continue
            if dumped is None:
                dumped = script.model_dump(mode="json")
            line = _at(dumped, path)
            found[text] = Finding(
                check.id, path, problem, check.severity, line if isinstance(line, str) else ""
            )
    faulted = {(f.check, f.path) for f in found.values()}
    return [
        f
        for f in found.values()
        if (defers := BY_ID[f.check].defers_to) is None or (defers, f.path) not in faulted
    ]


def texts(findings: Iterable[Finding]) -> list[str]:
    return [f.text for f in findings]


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]


def _fix_paths(findings: list[str]) -> list[str]:
    # Imported here: `mistake_fixes` reaches `campaigns.workspace`, whose draft code reaches
    # the writer (`workers/script_assist`), which runs these checks.
    from apps.api.agents.mistake_fixes import fix_paths

    return fix_paths(findings)


def _node(script: CallScript, path: str) -> Any:
    return _at(script.model_dump(mode="json"), path)


def _at(node: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def repairable(script: CallScript, finding: str) -> bool:
    """Whether a line repair (`script_proposals.kept_to_paths`) may rewrite the place
    `finding` names: one line, or the whole script's steps for a detail no step asks
    ("script"); never an opening or its notices (`mistake_fixes.fix_paths`), never a step
    outcome, which its own pass writes."""
    path = finding.partition(": ")[0]
    return (
        not path.startswith("step_outcomes")
        and bool(_fix_paths([finding]))
        and (path == "script" or isinstance(_node(script, path), str))
    )


def repairs(
    script: CallScript,
    context: CheckContext | LintContext | None = None,
    *,
    ids: Iterable[str] | None = None,
) -> list[str]:
    """What a line repair is asked to clear, by the writer's repair rounds and the healer
    alike: `run`'s findings a repair can reach (`repairable`), without the checks whose fix
    needs knowledge a repair does not hold (`Check.heals`). One function, so the writer, the
    heal pass and the healer's VERIFY never judge one script two ways."""
    return [
        f.text
        for f in run(script, context, ids=ids)
        if BY_ID[f.check].heals and repairable(script, f.text)
    ]


def writer_findings(
    script: CallScript, context: CheckContext | LintContext | None = None
) -> list[str]:
    """What the writer and its repair rounds are asked to clear (`repairs`), block and warn
    alike, as "<path>: <problem>"."""
    return repairs(script, context)


def mistake_findings(script: CallScript, context: LintContext, kind: str) -> list[str]:
    """The findings in `script` that can cause call mistake `kind`; [] for a kind no script
    line causes, or a raw script, which has no lines to point at."""
    ids = MISTAKE_CHECKS.get(kind)
    if not ids or script.raw_override:
        return []
    return texts(run(script, context, ids=ids))


def fixable_findings(script: CallScript, context: LintContext, kind: str) -> list[str]:
    """`mistake_findings` on the lines a fix may change (`mistake_fixes.fix_paths`): never the
    openings or their notice records, whatever the check names."""
    return [f for f in mistake_findings(script, context, kind) if _fix_paths([f])]


def script_mistakes(
    script: CallScript, context: LintContext, *, beside: Sequence[str] = ()
) -> list[str]:
    """Every mistake kind's fixable findings in `script`, each once, in a stable order. A
    finding of a flow check is left to the writer's refusal of the shape, which names it.

    `beside`, for a screen that lists another check's findings too: a line one of them
    already names is left to it, so one line is not counted twice."""
    flow = set(texts(run(script, context, ids=[c.id for c in CHECKS if c.flow])))
    named = {problem.partition(": ")[0] for problem in beside}
    found: dict[str, None] = {}
    for kind in sorted(SCRIPT_FIXABLE_KINDS):
        for finding in fixable_findings(script, context, kind):
            if finding not in flow and finding.partition(": ")[0] not in named:
                found.setdefault(finding)
    return list(found)


__all__ = [
    "BLOCKING",
    "BY_ID",
    "CHECKS",
    "MISTAKE_CHECKS",
    "SCRIPT_FIXABLE_KINDS",
    "SCRIPT_PROBLEM_CHECKS",
    "SHAPE_CHECKS",
    "Check",
    "CheckContext",
    "Finding",
    "blocking",
    "fixable_findings",
    "mistake_findings",
    "repairable",
    "repairs",
    "run",
    "script_mistakes",
    "texts",
    "writer_findings",
]
