"""The script cause of each mistake on a real call (D-985, D-1005): the detectors.

`call_mistakes.LESSONS` names what went wrong on real calls; each `<kind>_problems` here finds
the lines of a script (an Inbound line's or a campaign's) that make the in-call model do it,
as `script_lint` findings ("<path>: <problem>"), so the healer can rewrite exactly those
lines. They are registered, with their severity and the call-mistake kind each causes, in
`script_checks`, which every path runs; nothing calls them from anywhere else.

Each check runs the in-call detector for its kind (`turn_checks`) on the script's lines,
so a script check and a real call can never disagree about what the mistake is, and every
word it listens for comes from `call_words.json` through that detector. Nothing here is a
word list or a new threshold. Because the healer rewrites live lines, each check is
conservative: it reads only the shape the detector reads, and only in lines the in-call
model says or copies, each read in its own language (`script_lint.line_language`).

THE OPENING LINES ARE LEFT ALONE except by `false_history`. The opening is never judged as
a reply on a real call (`call_mistakes._replies`), it carries the notices woven into it
(D-971), and its length and wording have their own checks; a claim of earlier contact is
the exception because it is a claim made to the person, wherever it is said.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.call_script import CallScript, stage_steps, substitute_variables
from calevate_shared.spoken_guard import textbook_note

from apps.api.agents import turn_checks
from apps.api.agents.script_lint import (
    NAME_FIELD,
    OPENING_FIELDS,
    LintContext,
    agent_lines,
    line_language,
    next_steps,
    reachable_steps,
    spoken_fields,
    step_line,
)


def _agent_lines(
    script: CallScript, *, openings: bool = False, procedure: bool = False
) -> list[tuple[str, str]]:
    """(path, text) of each non-empty line the agent says or copies (`agent_lines`: the
    spoken fields, each language's step lines and examples, the answers), the caller's
    example lines left out, the openings only when `openings`, and with `procedure` the small
    steps' actions, which the agent says one a turn."""
    lines = [
        (path, text)
        for path, text in agent_lines(script)
        if text.strip() and (openings or path not in OPENING_FIELDS)
    ]
    if procedure:
        lines += [
            (f"stages.{i}.procedure.{j}.action", step.action)
            for i, stage in enumerate(script.stages)
            for j, step in enumerate(stage.procedure)
            if step.action.strip()
        ]
    return lines


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
            for found in turn_checks.turn_problems(
                _heard(text), language=line_language(path, context.language)
            )
        )
    ]


def too_long_problems(script: CallScript, context: LintContext) -> list[str]:
    return _turn_kind_lines(
        script,
        context,
        frozenset({"too_long", "several_questions", "repeated_question"}),
        f"says more than {turn_checks.MAX_SENTENCES} short sentences or asks more than one "
        "question in one turn; keep it to one point or one question, then let them speak.",
    )


def caller_line_problems(script: CallScript, context: LintContext) -> list[str]:
    # A speaker label ("Caller: ...") is the caller's part written into the agent's line,
    # the same failure `caller_line` names in a reply.
    return _turn_kind_lines(
        script,
        context,
        frozenset({"caller_line", "speaker_labels"}),
        "is written with the caller's part in it, or answers for them; write only what the "
        "agent says and leave the answer to the caller.",
    )


def third_person_problems(script: CallScript, context: LintContext) -> list[str]:
    return _turn_kind_lines(
        script,
        context,
        frozenset({"third_person"}),
        "talks about the person instead of to them; speak to them directly.",
    )


def wrong_language_problems(script: CallScript, context: LintContext) -> list[str]:
    # A line wholly in English in a call language with letters of its own is the reply the
    # model copies when it answers in English. A code-mixed line keeps the language's own
    # letters and is not this mistake (`turn_checks.answers_in_english`); its English words
    # are `script_problems`' finding.
    found: list[str] = []
    for path, text in _agent_lines(script):
        name = turn_checks.answers_in_english(_heard(text), line_language(path, context.language))
        if name is not None:
            found.append(f"{path}: is in English, not {name}; write it in {name}, as the call is.")
    return found


def false_history_problems(script: CallScript, _context: LintContext) -> list[str]:
    # `caller_asked=True`: "earlier you asked" may mean earlier on this call, which a script
    # line cannot rule out, so only an outright claim of earlier contact counts.
    return [
        f"{path}: tells the person they enquired or spoke with the business before, which is "
        "untrue for anyone with no earlier enquiry or call; say why you are calling without "
        "claiming one."
        for path, text in _agent_lines(script, openings=True)
        if turn_checks.false_history(_heard(text), caller_asked=True)
    ]


def goodbye_while_asking_problems(script: CallScript, _context: LintContext) -> list[str]:
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


def false_recall_problems(script: CallScript, _context: LintContext) -> list[str]:
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


def asked_again_problems(script: CallScript, _context: LintContext) -> list[str]:
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


def _name_asking(script: CallScript) -> tuple[dict[int, tuple[str, str]], set[int]]:
    steps = _step_lines(script)
    return steps, {i for i, (_p, text) in steps.items() if turn_checks.asks_name(_heard(text))}


def known_name_problems(script: CallScript) -> list[str]:
    """A step whose line asks the person's name when the opening of a placed call already
    greets them by the name field (the 25 Nov 2026 Rytu Khata call asked an existing
    customer's name in step 1): what the contact record holds is never asked (docs/evidence/
    voice-agent-research-2026-11-25.md §C "Field collection")."""
    openings = f"{script.outbound_opening_line} {script.opening_line}".replace(" ", "")
    if NAME_FIELD not in openings:
        return []
    steps, asking = _name_asking(script)
    return [
        f"{steps[j][0]}: asks for the name, which the call already has: the opening greets "
        "them by it; leave the question out and use their name."
        for j in sorted(asking)
    ]


def reasked_name_problems(script: CallScript, _context: LintContext) -> list[str]:
    """A step whose line asks the person's name the call already has (`known_name_problems`),
    or that a step the call passes first asks too (`turn_checks.asks_name`)."""
    known = known_name_problems(script)
    if known:
        return known
    steps, asking = _name_asking(script)
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


def offered_more_too_soon_problems(script: CallScript, _context: LintContext) -> list[str]:
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


def stalled_problems(script: CallScript, _context: LintContext) -> list[str]:
    """A step whose line is a reaction and nothing more (`turn_checks.only_reaction`): the
    model copies it as the whole turn and the caller is left to ask what comes next. A step
    the call goes nowhere from is a close, where a short thank-you is the turn."""
    return [
        f"{path}: is only a reaction; end it on the question or next step it leads to."
        for i, (path, text) in _step_lines(script).items()
        if turn_checks.only_reaction(_heard(text)) and _following(script, i)
    ]


def formal_words_problems(script: CallScript, context: LintContext) -> list[str]:
    """Each agent line with a word from the language's textbook list, naming the words and
    what people say instead, as the reply check names them. The small steps' actions too:
    the agent says them one a turn. A line in a named language is read in that language."""
    found: list[str] = []
    for path, text in _agent_lines(script, procedure=True):
        swaps = turn_checks.formal_swaps(_heard(text), line_language(path, context.language))
        if swaps:
            found.append(f"{path}: uses textbook words callers do not say: {textbook_note(swaps)}.")
    return found


def asked_done_too_soon_problems(script: CallScript, _context: LintContext) -> list[str]:
    """A line that gives an action and asks in the same line whether it is done
    (`turn_checks.asks_done_too_soon`): every line the agent says or copies, each call
    language's step lines and the small steps' actions included, the openings left out. The
    repair rewrites it as the action alone: the person says when it is done."""
    lines = _agent_lines(script, procedure=True)
    return [
        f"{path}: gives an action and asks in the same line whether it is done, before they "
        "can do it; end the line on the action itself, with no question after it."
        for path, text in lines
        if text.strip() and turn_checks.asks_done_too_soon(_heard(text))
    ]


# --- step outcomes (founder, 24 Nov 2026) -----------------------------------------------------
def moved_on_unconfirmed_problems(script: CallScript, _context: LintContext) -> list[str]:
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
        # An Otherwise is somewhere to go when the outcome clearly cannot be reached
        # (`OUTCOMES_LEAD`), and the agent stays on the step until then. Asking for a way out
        # there made the repair add "cannot or will not reach it -> call back" to every guided
        # step, when a call back is the last resort (founder, 25 Nov 2026).
        if stage.branches or stage.otherwise:
            with_exit.add(step)
    return [
        f"stages.{i}.instruction: step {step} has an outcome and nowhere to go if it cannot "
        "be reached; give it an Otherwise, and a way out to a call back only for someone who "
        "still cannot after being guided step by step."
        for step, i in sorted(first.items())
        if step in has_outcome and step != last and step not in with_exit
    ]


__all__ = [
    "asked_again_problems",
    "asked_done_too_soon_problems",
    "caller_line_problems",
    "false_history_problems",
    "false_recall_problems",
    "formal_words_problems",
    "goodbye_while_asking_problems",
    "known_name_problems",
    "moved_on_unconfirmed_problems",
    "offered_more_too_soon_problems",
    "reasked_name_problems",
    "stalled_problems",
    "third_person_problems",
    "too_long_problems",
    "wrong_language_problems",
]
