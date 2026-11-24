"""The script cause of each mistake on a real call, for the auto-healer (D-985, D-1005).

`call_mistakes.LESSONS` names what went wrong on real calls; this module finds, for one of
those kinds, the lines of a script (an Inbound line's or a campaign's) that make the in-call
model do it, so the healer can rewrite exactly those lines. Each finding is a `script_lint`
finding ("<path>: <problem>"), so `mistake_fixes.request_holder_fix(paths=...)`,
`fix_change`, `finding_key` and `kept_to_paths` take it as they take any other.

Each check runs the in-call detector for its kind (`turn_checks`) on the script's lines,
so a script check and a real call can never disagree about what the mistake is, and every
word it listens for comes from `call_words.json` through that detector. Nothing here is a
word list or a new threshold.

BEFORE ANY CALL, NOT IN `script_problems` (D-989). Every kind's check (`script_mistakes`)
runs when Pip writes or changes a script, whose repair round is asked to fix what it finds;
on the readiness card and in Put it live as a separate group of warnings that never blocks
"Put it live" ("Fix them first" fixes them too); and over live scripts by the healer's sweep,
which opens the same fix a real call opens. They stay out of `script_problems` because that
list is the writer's refusal check, and a line that MAY cause a mistake must never cost the
owner a whole draft. Because the healer rewrites live lines, each check is conservative: it
reads only the shape the detector reads, and only in lines the in-call model says or copies.

THE OPENING LINES ARE LEFT ALONE except by `false_history`. The opening is never judged as
a reply on a real call (`call_mistakes._replies`), it carries the notices woven into it
(D-971), and its length and wording have their own checks; a claim of earlier contact is
the exception because it is a claim made to the person, wherever it is said.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

from calevate_shared.call_script import CallScript, stage_steps, substitute_variables
from calevate_shared.spoken_guard import textbook_note

from apps.api.agents import turn_checks
from apps.api.agents.call_rules import opening_redone_line_problems, reacted_line_problems
from apps.api.agents.mistake_fixes import fix_paths
from apps.api.agents.script_lint import (
    OPENING_FIELDS,
    LintContext,
    agent_lines,
    bracket_problems,
    caller_paths,
    flow_problems,
    next_steps,
    opening_redone_problems,
    reachable_steps,
    repeated_line_problems,
    same_ending_problems,
    same_opener_problems,
    spoken_fields,
    step_line,
)

_Check = Callable[[CallScript, LintContext], list[str]]


def _agent_lines(script: CallScript, *, openings: bool = False) -> list[tuple[str, str]]:
    """(path, text) of each non-empty line the agent says or copies, the caller's example
    lines left out, and the openings only when `openings`."""
    callers = caller_paths(script)
    return [
        (path, text)
        for path, text in spoken_fields(script)
        if text.strip() and path not in callers and (openings or path not in OPENING_FIELDS)
    ]


def _step_lines(script: CallScript) -> dict[int, tuple[str, str]]:
    """Each step's spoken line (`step_line`) by step index, empty ones left out."""
    lines = {i: step_line(script, i) for i in range(len(script.stages))}
    return {i: line for i, line in lines.items() if line[1].strip()}


def _heard(text: str) -> str:
    """A line as a call with no merge values hears it: a field left unfilled is dropped
    (`substitute_variables`), so its key is never read as an English word."""
    return substitute_variables(text, {})


def _step_index(script: CallScript) -> dict[str, int]:
    return {stage.id: i for i, stage in enumerate(script.stages)}


def _following(script: CallScript, index: int) -> set[int]:
    """The steps the call goes to straight from step `index`."""
    at = _step_index(script)
    return {at[target] for target in next_steps(script, index) if target in at} - {index}


def _within(script: CallScript, start: int, hops: int) -> set[int]:
    """The steps the call reaches from step `start` in at most `hops` moves."""
    seen: set[int] = set()
    edge = {start}
    for _ in range(hops):
        edge = {j for i in edge for j in _following(script, i)} - seen - {start}
        seen |= edge
    return seen


def _turn_kind_lines(
    script: CallScript, context: LintContext, kinds: frozenset[str], problem: str
) -> list[str]:
    """Each agent line that the reply check (`turn_checks.turn_problems`) faults with one of
    `kinds` when said as a turn: the model copies a step's line, so a line that is the
    mistake as written makes the replies the mistake."""
    return [
        f"{path}: {problem}"
        for path, text in _agent_lines(script)
        if any(
            found.kind in kinds
            for found in turn_checks.turn_problems(_heard(text), language=context.language)
        )
    ]


def _too_long(script: CallScript, context: LintContext) -> list[str]:
    return _turn_kind_lines(
        script,
        context,
        frozenset({"too_long", "several_questions", "repeated_question"}),
        f"says more than {turn_checks.MAX_SENTENCES} short sentences or asks more than one "
        "question in one turn; keep it to one point or one question, then let them speak.",
    )


def _caller_line(script: CallScript, context: LintContext) -> list[str]:
    # A speaker label ("Caller: ...") is the caller's part written into the agent's line,
    # the same failure `caller_line` names in a reply.
    return _turn_kind_lines(
        script,
        context,
        frozenset({"caller_line", "speaker_labels"}),
        "is written with the caller's part in it, or answers for them; write only what the "
        "agent says and leave the answer to the caller.",
    )


def _third_person(script: CallScript, context: LintContext) -> list[str]:
    return _turn_kind_lines(
        script,
        context,
        frozenset({"third_person"}),
        "talks about the person instead of to them; speak to them directly.",
    )


def _wrong_language(script: CallScript, context: LintContext) -> list[str]:
    # A line wholly in English in a call language with letters of its own is the reply the
    # model copies when it answers in English. A code-mixed line keeps the language's own
    # letters and is not this mistake (`turn_checks.answers_in_english`); its English words
    # are `script_problems`' finding.
    found: list[str] = []
    for path, text in _agent_lines(script):
        name = turn_checks.answers_in_english(_heard(text), context.language)
        if name is not None:
            found.append(f"{path}: is in English, not {name}; write it in {name}, as the call is.")
    return found


def _false_history(script: CallScript, _context: LintContext) -> list[str]:
    # `caller_asked=True`: "earlier you asked" may mean earlier on this call, which a script
    # line cannot rule out, so only an outright claim of earlier contact counts.
    return [
        f"{path}: tells the person they enquired or spoke with the business before, which is "
        "untrue for anyone with no earlier enquiry or call; say why you are calling without "
        "claiming one."
        for path, text in _agent_lines(script, openings=True)
        if turn_checks.false_history(_heard(text), caller_asked=True)
    ]


def _goodbye_while_asking(script: CallScript, _context: LintContext) -> list[str]:
    """A step's line that says goodbye where the call is not over: the call goes on to
    another step after it, or the line asks something and closes before the answer."""
    found: list[str] = []
    for i, (path, text) in _step_lines(script).items():
        parts = turn_checks.sentences(_heard(text))
        bye = next((n for n, part in enumerate(parts) if turn_checks.says_goodbye(part)), None)
        if bye is None:
            continue
        if _following(script, i):
            found.append(
                f"{path}: says goodbye, and the call goes on to another step after it; keep "
                "goodbye for the close."
            )
        elif any(turn_checks.is_question(part) for part in parts[:bye]):
            found.append(
                f"{path}: asks something and says goodbye in the same line; ask, wait for the "
                "answer, and say goodbye only after it."
            )
    return found


_RECALL_PROBLEM: Final = (
    "says it already told them a figure that no line before it says; say the detail itself "
    "instead of claiming it was said."
)


def _false_recall(script: CallScript, _context: LintContext) -> list[str]:
    """A line claiming it already told the person a figure that nothing said before it says
    (`turn_checks.false_recall`). A step is read against the openings and the steps that
    lead to it; a line with no place in the call (a sample phrase, the example call) against
    everything else the script says, which can only make it pass more often."""
    openings = " ".join(text for path, text in spoken_fields(script) if path in OPENING_FIELDS)
    steps = _step_lines(script)
    found: list[str] = []
    for j, (path, text) in steps.items():
        before = [t for i, (_p, t) in steps.items() if i != j and j in reachable_steps(script, i)]
        if turn_checks.false_recall(_heard(text), _heard(" ".join([openings, *before]))):
            found.append(f"{path}: {_RECALL_PROBLEM}")
    step_paths = {p for p, _t in steps.values()}
    everything = _agent_lines(script, openings=True)
    for path, text in everything:
        if path in step_paths or path in OPENING_FIELDS:
            continue
        said = " ".join(t for p, t in everything if p != path)
        if turn_checks.false_recall(_heard(text), _heard(said)):
            found.append(f"{path}: {_RECALL_PROBLEM}")
    return found


def _asked_again(script: CallScript, _context: LintContext) -> list[str]:
    """A step whose line asks, word for word, the question of the step the call comes from
    (`turn_checks.asked_again`, the check that compares one reply with the one before)."""
    steps = _step_lines(script)
    found: list[str] = []
    for j, (path, text) in steps.items():
        came_from = next(
            (
                i
                for i, (_p, before) in steps.items()
                if j in _following(script, i)
                and turn_checks.asked_again(_heard(text), _heard(before))
            ),
            None,
        )
        if came_from is not None:
            found.append(
                f"{path}: asks again what step {came_from + 1} just asked; ask it once, and "
                "have this step move on to the next thing."
            )
    return found


def _reasked_name(script: CallScript, _context: LintContext) -> list[str]:
    """A step whose line asks the person's name when a step the call passes first asks it
    too (`turn_checks.asks_name`)."""
    steps = _step_lines(script)
    asking = {i for i, (_p, text) in steps.items() if turn_checks.asks_name(_heard(text))}
    found: list[str] = []
    for j in sorted(asking):
        earlier = next(
            (i for i in sorted(asking) if i != j and j in reachable_steps(script, i)), None
        )
        if earlier is not None:
            found.append(
                f"{steps[j][0]}: asks for the name, which step {earlier + 1} already asks for; "
                "use the name they gave."
            )
    return found


def _offered_more_too_soon(script: CallScript, _context: LintContext) -> list[str]:
    """A step's line that asks whether they need anything else (`turn_checks.offers_more`)
    while the topic is not done: in a step that walks them through its step-by-step list,
    or with another such offer within the replies the in-call check counts
    (`turn_checks.OFFERS_MORE_WINDOW`), each step being at least one reply."""
    steps = _step_lines(script)
    offering = {i for i, (_p, text) in steps.items() if turn_checks.offers_more(_heard(text))}
    found: list[str] = []
    for i in sorted(offering):
        path = steps[i][0]
        if script.stages[i].procedure:
            found.append(
                f"{path}: asks whether they need anything else in a step that walks them "
                "through steps; give the next step instead, and ask it only once the task "
                "is done."
            )
            continue
        soon = sorted(offering & _within(script, i, turn_checks.OFFERS_MORE_WINDOW - 1))
        if soon:
            found.append(
                f"{path}: asks whether they need anything else, and step {soon[0] + 1} soon "
                "after asks it again; ask it only once the topic is done."
            )
    return found


def _stalled(script: CallScript, _context: LintContext) -> list[str]:
    """A step whose line is a reaction and nothing more (`turn_checks.only_reaction`): the
    model copies it as the whole turn and the caller is left to ask what comes next. A step
    the call goes nowhere from is a close, where a short thank-you is the turn."""
    return [
        f"{path}: is only a reaction; end it on the question or next step it leads to."
        for i, (path, text) in _step_lines(script).items()
        if turn_checks.only_reaction(_heard(text)) and _following(script, i)
    ]


def _formal_words(script: CallScript, context: LintContext) -> list[str]:
    """Each agent line with a word from the language's textbook list, naming the words and
    what people say instead, as the reply check names them."""
    found: list[str] = []
    for path, text in _agent_lines(script):
        swaps = turn_checks.formal_swaps(_heard(text), context.language)
        if swaps:
            found.append(f"{path}: uses textbook words callers do not say: {textbook_note(swaps)}.")
    return found


def _asked_done_too_soon(script: CallScript, _context: LintContext) -> list[str]:
    """A line that gives an action and asks in the same line whether it is done
    (`turn_checks.asks_done_too_soon`): every line the agent says or copies, each call
    language's step lines and the small steps' actions included, the openings left out. The
    repair rewrites it as the action and an invitation to say when it is done."""
    lines = [
        *((p, t) for p, t in agent_lines(script) if p not in OPENING_FIELDS),
        *(
            (f"stages.{i}.procedure.{j}.action", step.action)
            for i, stage in enumerate(script.stages)
            for j, step in enumerate(stage.procedure)
        ),
    ]
    return [
        f"{path}: gives an action and asks in the same line whether it is done, before they "
        "can do it; end on the action and an invitation to say when it is done, worded for "
        "this step, with no question."
        for path, text in lines
        if text.strip() and turn_checks.asks_done_too_soon(_heard(text))
    ]


def _opened_again(script: CallScript, _context: LintContext) -> list[str]:
    """A step told to redo the opening (its English instruction) or whose line does."""
    return [*opening_redone_problems(script), *opening_redone_line_problems(script)]


# --- step outcomes (founder, 24 Nov 2026) -----------------------------------------------------
def _moved_on_unconfirmed(script: CallScript, _context: LintContext) -> list[str]:
    """A step with an outcome, not the last, none of whose scenarios has a way out: the
    outcomes section sends a step that cannot be reached to its way out "else its Otherwise",
    so with none the call goes on to the next step without the outcome. Named on the step's
    first scenario's instruction, the line a fix may say the way out in. A step without an
    outcome is left to Pip, who writes it (`campaigns/step_outcomes`)."""
    if not script.stages:
        return []
    steps = stage_steps(script.stages)
    has_outcome = {o.step for o in script.step_outcomes}
    last = max(steps)
    first: dict[int, int] = {}
    with_exit: set[int] = set()
    for i, (stage, step) in enumerate(zip(script.stages, steps, strict=True)):
        first.setdefault(step, i)
        if stage.branches:
            with_exit.add(step)
    return [
        f"stages.{i}.instruction: step {step} has an outcome and no way out; say what to do "
        "when the person cannot or will not reach it, so the agent never moves on without it."
        for step, i in sorted(first.items())
        if step in has_outcome and step != last and step not in with_exit
    ]


# --- end of the step-outcome block -------------------------------------------------------------


def _delegate(lint: Callable[[CallScript], list[str]]) -> _Check:
    def check(script: CallScript, _context: LintContext) -> list[str]:
        return lint(script)

    return check


#: Each mistake kind's script check. The four that `script_lint.flow_problems` already
#: finds go to that lint, so the readiness card and the healer read one check.
_CHECKS: Final[dict[str, _Check]] = {
    "brackets": _delegate(bracket_problems),
    "opened_again": _opened_again,
    "same_opening": _delegate(lambda s: [*same_opener_problems(s), *reacted_line_problems(s)]),
    "same_closing": _delegate(same_ending_problems),
    "said_again": _delegate(repeated_line_problems),
    "too_long": _too_long,
    "asked_again": _asked_again,
    "reasked_name": _reasked_name,
    "caller_line": _caller_line,
    "goodbye_while_asking": _goodbye_while_asking,
    "false_recall": _false_recall,
    "wrong_language": _wrong_language,
    "third_person": _third_person,
    "offered_more_too_soon": _offered_more_too_soon,
    "false_history": _false_history,
    "stalled": _stalled,
    "moved_on_unconfirmed": _moved_on_unconfirmed,
    "formal_words": _formal_words,
    "asked_done_too_soon": _asked_done_too_soon,
}

#: The mistake kinds a script check can trace to the agent's own script.
SCRIPT_FIXABLE_KINDS: Final[frozenset[str]] = frozenset(_CHECKS)
# A kind the agent shows during the call whatever its script says has no script check, so
# the healer never rewrites a line for it.
assert SCRIPT_FIXABLE_KINDS.isdisjoint(turn_checks.IN_CALL_KINDS)


def mistake_findings(script: CallScript, context: LintContext, kind: str) -> list[str]:
    """The findings in `script` that can cause mistake `kind` on a call, as `script_lint`
    findings ("<path>: <problem>"); [] for a kind with no check, or nothing found. A raw
    (hand-written) script has no lines to point at."""
    check = _CHECKS.get(kind)
    if check is None or script.raw_override:
        return []
    return check(script, context)


def fixable_findings(script: CallScript, context: LintContext, kind: str) -> list[str]:
    """`mistake_findings` on the lines a fix may change (`mistake_fixes.fix_paths`): never the
    openings or their notice records, whatever the check names."""
    return [f for f in mistake_findings(script, context, kind) if fix_paths([f])]


def script_mistakes(
    script: CallScript, context: LintContext, *, beside: Sequence[str] = ()
) -> list[str]:
    """Every kind's fixable findings in `script`, each once, in a stable order: what the
    writer repairs, the readiness card shows and "Fix them first" fixes. A finding
    `script_lint.flow_problems` also makes is left to `script_problems`, which shows it.

    `beside`, for a screen that lists the script check's findings too: a line one of them
    already names is left to it, so one line is not counted twice. The writer passes
    nothing, since a repair must hear every rule a line breaks."""
    flow = set(flow_problems(script))
    named = {problem.partition(": ")[0] for problem in beside}
    found: dict[str, None] = {}
    for kind in sorted(SCRIPT_FIXABLE_KINDS):
        for finding in fixable_findings(script, context, kind):
            if finding not in flow and finding.partition(": ")[0] not in named:
                found.setdefault(finding)
    return list(found)


__all__ = ["SCRIPT_FIXABLE_KINDS", "fixable_findings", "mistake_findings", "script_mistakes"]
