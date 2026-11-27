"""The steps an owner lays out in their own request, and whether a written script keeps them.

An owner who writes "Steps, in this order: 1. Introduction: ... Outcome: ... - Busy now: offer
a call back" has already designed the call. The writer's own guidance (the kinds of call, the
trade's step plan, the closing step's name, the main task's items, the ways out every placed
call gets) is for a request that has not, and on 25 Nov 2026 it won: the Rytu Khata rewrite
came back with the main task's old install steps, a duplicated Login, call back and end call as
steps of their own, and five of the owner's eleven steps missing. So the plan is read here by
code, shown to the writer as its own block, and checked against every draft as a repairable
problem (`plan_problems`), the way the language rules are.

Read deterministically rather than by asking the model for the plan first: the format is the
one owners and Pip already write (numbered "Name: what to do. Outcome: ..." items, bulleted
"Condition: where it goes" branches, named side steps a "go to" reaches), a parse is free and
cannot itself drift from the words, and a request that does not have this shape (prose, or a
numbered list of changes rather than steps) yields no plan, leaving the writer as it was. The
text may arrive folded onto one line (`copilot.script_actions._ask`), so nothing here depends
on line breaks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Final

from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_SCRIPT_STAGES,
    SPECIAL_TARGETS,
    STAGE_TITLE_MAX,
    STEP_OUTCOME_MAX,
    CallScript,
    ConversationStage,
    StepOutcome,
    stage_steps,
)
from calevate_shared.spoken_guard import has_indic_letters

from apps.api.agents.script_lint import closes_the_call, next_steps


@dataclass(frozen=True, slots=True)
class PlanBranch:
    """One way out the owner named: `when` in their words, `said` what they said to do, and
    `goes_to` one of `SPECIAL_TARGETS`, a planned step's name, or "" when the owner's words
    name no place the code can tell (the writer still reads them)."""

    when: str
    said: str
    goes_to: str = ""


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """One step of the owner's plan. `number` is its place in the numbered list; None for a
    named side step that only a way out reaches ("Not registered")."""

    name: str
    instruction: str
    outcome: str = ""
    branches: tuple[PlanBranch, ...] = ()
    number: int | None = None

    @property
    def key(self) -> str:
        return name_key(self.name)


@dataclass(frozen=True, slots=True)
class OwnerPlan:
    steps: tuple[PlannedStep, ...]

    @property
    def fitting(self) -> tuple[PlannedStep, ...]:
        """The steps a script can hold: every step needs at least one stage."""
        return self.steps[:MAX_SCRIPT_STAGES]

    @property
    def over(self) -> tuple[PlannedStep, ...]:
        return self.steps[MAX_SCRIPT_STAGES:]

    def named(self, name: str) -> PlannedStep | None:
        key = name_key(name)
        return next((step for step in self.steps if step.key == key), None)

    @property
    def numbered(self) -> tuple[PlannedStep, ...]:
        return tuple(step for step in self.fitting if step.number is not None)

    def reached_from(self, side: PlannedStep) -> int | None:
        """The number of the earliest numbered step a way out of which reaches the side step
        `side`, directly or through another side step; None when nothing numbered does."""
        seen = {side.key}
        todo = [side.key]
        found: list[int] = []
        while todo:
            key = todo.pop()
            for step in self.fitting:
                if not any(name_key(b.goes_to) == key for b in step.branches if b.goes_to):
                    continue
                if step.number is not None:
                    found.append(step.number)
                elif step.key not in seen:
                    seen.add(step.key)
                    todo.append(step.key)
        return min(found, default=None)

    def side_home(self, side: PlannedStep) -> int | None:
        """The numbered step a side step is a scenario of: the one right after the earliest
        step that reaches it, so the way out into it is a move to the next step (a line on the
        call-flow canvas, `flowLayout.ts`) and no step's own way on leads into it; the
        reaching step itself when that is the last. None when nothing numbered reaches it."""
        reacher = self.reached_from(side)
        if reacher is None:
            return None
        numbers = [step.number for step in self.numbered]
        return reacher + 1 if reacher + 1 in numbers else reacher


_STEP_PREFIX: Final = re.compile(r"^\s*step\s*\d{1,2}\s*[:.)-]?\s*", re.IGNORECASE)


def name_key(name: str) -> str:
    """A step name as compared: case, spacing, punctuation and a leading "Step 3:" ignored,
    so "Log in" is the owner's "Login" and nothing looser is."""
    return re.sub(r"[\W_]+", "", _STEP_PREFIX.sub("", name).casefold())


#: A numbered item ("1. Introduction:"), at a line start or after a space, so a list folded
#: onto one line still reads as a list.
_NUMBER_MARK: Final = re.compile(r"(?:^|(?<=\s))(\d{1,2})[.)]\s+", re.MULTILINE)
#: A label ("Outcome:", "Busy now:") at the start of the text, after a sentence, or after a
#: bullet. A colon inside a sentence ("at 10:30", "https://") is not one.
#: Straight and curly quotes, as owners and Pip type them (U+201C, U+201D, U+2018, U+2019).
_QUOTES: Final = "\"'" + "".join(map(chr, (0x201C, 0x201D, 0x2018, 0x2019)))
_LABEL: Final = re.compile(
    rf"(?:^|(?<=[.!?]\s)|(?<=[.!?][{_QUOTES})]\s)|(?P<bullet>(?:^|(?<=\s))[-*•]\s+))"
    rf"(?P<label>[^\W\d_][^:.!?{_QUOTES}\n]{{0,139}}?):(?=\s|$)",
    re.MULTILINE,
)
#: A bullet's condition may be a whole clause ("Still cannot open the website after being
#: guided step by step:"); a label that is not a bullet stays short, so a sentence that merely
#: has a colon in it is not read as one.
_BULLET_LABEL_WORDS: Final = 20
#: Labels that open the request's general part after the steps ("Rules: one question per
#: turn ..."): the plan ends there, so they are never read as a way out of the last step or
#: of a side step.
_CLOSING_LABEL: Final = re.compile(
    r"(?:^|(?<=[.!?]\s)|(?<=[.!?][\"')]\s))(?:general\s+)?"
    r"(?:rules?|notes|throughout|for\s+(?:every|each)\s+(?:step|turn))\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_LABEL_WORDS: Final = 8
_OUTCOME_LABELS: Final = frozenset({"outcome", "done when", "result", "expected outcome", "goal"})
_GO_TO_NUMBER: Final = re.compile(
    r"\b(?:go|goes|skip|move|jump)\s+(?:on\s+|straight\s+|back\s+)?to\s+step\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_GO_TO_NAME: Final = re.compile(
    r"\b(?:go|goes|skip|move|jump)\s+(?:on\s+|straight\s+|back\s+)?to\s+"
    rf"[{_QUOTES}]?(?P<name>[^{_QUOTES}.;,!?]+)",
    re.IGNORECASE,
)
_CALL_BACK_WORDS: Final = re.compile(r"\bcall[\s-]?back\b|\bcall\s+(?:them\s+)?later\b", re.I)
_HAND_OVER_WORDS: Final = re.compile(r"\bhand(?:\s|-)?over\b|\btransfer\b", re.I)
_END_WORDS: Final = re.compile(
    r"\b(?:end|close|finish)\s+(?:the\s+|this\s+)?call\b|\bhang\s+up\b|\bend\s+politely\b", re.I
)


@dataclass(frozen=True, slots=True)
class _Segment:
    label: str
    body: str
    bullet: bool
    start: int


def _segments(text: str) -> tuple[str, list[_Segment]]:
    """`text` cut at its labels: what comes before the first, and each labelled part."""
    marks = [
        m
        for m in _LABEL.finditer(text)
        if len(m.group("label").split())
        <= (_BULLET_LABEL_WORDS if m.group("bullet") is not None else _LABEL_WORDS)
    ]
    head = text[: marks[0].start()] if marks else text
    out = [
        _Segment(
            label=" ".join(m.group("label").split()),
            body=" ".join(
                text[m.end() : marks[n + 1].start() if n + 1 < len(marks) else None].split()
            ),
            bullet=m.group("bullet") is not None,
            start=m.start(),
        )
        for n, m in enumerate(marks)
    ]
    return " ".join(head.split()), out


def _named_target(body: str) -> str | None:
    found = _GO_TO_NAME.search(body)
    if found is None:
        return None
    name = re.sub(r"^(?:the\s+)", "", found.group("name").strip(), flags=re.I)
    name = re.sub(r"\s+step$", "", name, flags=re.I).strip()
    return name or None


def _routed(body: str) -> bool:
    """Whether `body` says where the call goes."""
    return bool(
        _GO_TO_NUMBER.search(body)
        or _GO_TO_NAME.search(body)
        or _CALL_BACK_WORDS.search(body)
        or _HAND_OVER_WORDS.search(body)
        or _END_WORDS.search(body)
    )


def _goes_to(body: str, numbered: Sequence[str], side: Sequence[str]) -> str:
    """Where a branch's words send the call: a named step first (its words may also say
    "end"), then a call back, a hand over, the end."""
    by_number = _GO_TO_NUMBER.search(body)
    if by_number is not None and 1 <= int(by_number.group(1)) <= len(numbered):
        return numbered[int(by_number.group(1)) - 1]
    name = _named_target(body)
    if name is not None:
        key = name_key(name)
        for known in (*numbered, *side):
            if name_key(known) == key:
                return known
    if _CALL_BACK_WORDS.search(body):
        return CALL_BACK
    if _HAND_OVER_WORDS.search(body):
        return HAND_OVER
    if _END_WORDS.search(body):
        return END_OF_CALL
    return ""


def _numbered_items(text: str) -> list[tuple[int, str]]:
    """The list 1, 2, 3 ... in `text`, each with its text. A stray "1." before the real list
    is dropped when another "1." follows it."""
    run: list[re.Match[str]] = []
    for mark in _NUMBER_MARK.finditer(text):
        number = int(mark.group(1))
        if number == 1 and len(run) <= 1:
            run = [mark]
        elif number == len(run) + 1:
            run.append(mark)
    return [
        (n + 1, text[mark.end() : run[n + 1].start() if n + 1 < len(run) else len(text)])
        for n, mark in enumerate(run)
    ]


def numbered_items(text: str | None) -> list[str]:
    """The numbered list 1, 2, 3 ... in `text`, each item's text on one line; [] for fewer
    than two. A main task written as plain numbered sentences has these and no plan."""
    items = [" ".join(body.split()) for _n, body in _numbered_items(text or "")]
    return items if len(items) >= 2 and all(items) else []


def owner_plan(text: str | None) -> OwnerPlan | None:
    """The steps `text` lays out, or None when it lays out none: at least two numbered items,
    each starting with its name ("Login: ..."), and at least half giving an outcome."""
    if not text:
        return None
    items = _numbered_items(text)
    if len(items) < 2:
        return None
    number, last_body = items[-1]
    closing = _CLOSING_LABEL.search(last_body)
    if closing is not None:
        items[-1] = (number, last_body[: closing.start()])
    parsed = [_segments(body) for _n, body in items]
    if any(head or not segs or segs[0].start != 0 for head, segs in parsed):
        return None
    names = [segs[0].label for _head, segs in parsed]
    wanted_side = [
        name
        for match in _GO_TO_NAME.finditer(text)
        if (name := _named_target(match.group(0))) is not None
        and name_key(name) not in {name_key(n) for n in names}
    ]
    side_keys = {name_key(name) for name in wanted_side}
    steps: list[PlannedStep] = []
    trailing: list[list[_Segment]] = []
    for index, (_head, segs) in enumerate(parsed):
        last = index == len(parsed) - 1
        first, rest = segs[0], segs[1:]
        instruction = [first.body]
        outcome = ""
        branches: list[tuple[str, str]] = []
        for at, seg in enumerate(rest):
            if name_key(seg.label) in side_keys:
                trailing.append(rest[at:])
                break
            if seg.label.casefold() in _OUTCOME_LABELS and not seg.bullet:
                outcome = seg.body
            elif seg.bullet or _routed(seg.body):
                branches.append((seg.label, seg.body))
            elif last:
                break
            else:
                instruction.append(f"{seg.label}: {seg.body}")
        steps.append(
            PlannedStep(
                name=first.label,
                instruction=" ".join(part for part in instruction if part),
                outcome=outcome,
                branches=tuple(PlanBranch(when, said) for when, said in branches),
                number=index + 1,
            )
        )
    if sum(bool(step.outcome) for step in steps) * 2 < len(steps):
        return None
    sides: list[PlannedStep] = []
    for segs in trailing:
        current: PlannedStep | None = None
        for seg in segs:
            if name_key(seg.label) in side_keys and not seg.bullet:
                if current is not None:
                    sides.append(current)
                current = PlannedStep(name=seg.label, instruction=seg.body)
            elif current is not None and (seg.bullet or _routed(seg.body)):
                current = PlannedStep(
                    name=current.name,
                    instruction=current.instruction,
                    branches=(*current.branches, PlanBranch(seg.label, seg.body)),
                )
            elif current is not None:
                sides.append(current)
                current = None
        if current is not None:
            sides.append(current)
    unique_sides: list[PlannedStep] = []
    for side in sides:
        if all(side.key != kept.key for kept in unique_sides):
            unique_sides.append(side)
    numbered = [step.name for step in steps]
    side_names = [step.name for step in unique_sides]

    def routed(step: PlannedStep) -> PlannedStep:
        return PlannedStep(
            name=step.name,
            instruction=step.instruction,
            outcome=step.outcome,
            number=step.number,
            branches=tuple(
                PlanBranch(b.when, b.said, _goes_to(b.said, numbered, side_names))
                for b in step.branches
            ),
        )

    return OwnerPlan(tuple(routed(step) for step in (*steps, *unique_sides)))


#: What a placed call's opening line already does, as a plan step's English says it: greet,
#: introduce the agent, say who is calling, ask whether now suits.
_OPENING_ACTS: Final = re.compile(
    r"\b(?:greet\w*(?:\s+(?:them|the\s+\w+))?(?:\s+by\s+(?:their\s+)?name)?|"
    r"introduce\s+(?:yourself|herself|himself|the\s+agent|the\s+business|us)|"
    r"identify\s+(?:yourself|herself|himself)|"
    r"say\s+who\s+(?:you\s+are|is\s+calling|(?:we|i)\s+(?:are|am))|"
    r"(?:ask|check)\w*(?:\s+them)?\s+(?:if|whether)\s+[^.;]{0,30}?"
    r"\b(?:talk|speak|good\s+time|convenient|free)\b(?:\s+now)?)",
    re.IGNORECASE,
)
_OPENING_STEP_NAME: Final = re.compile(
    r"^\s*(?:intro(?:duction|duce\w*)?|greeting|greet|opening|hello|who\s+is\s+calling)\b",
    re.IGNORECASE,
)
#: Words that only place a step ("right after the opening, from the business").
_PLACING_WORDS: Final = frozenset(
    {
        "right",
        "after",
        "before",
        "opening",
        "line",
        "first",
        "from",
        "then",
        "with",
        "their",
        "them",
        "name",
        "calling",
        "call",
        "briefly",
        "politely",
        "warmly",
    }
)


def opening_only(step: PlannedStep) -> bool:
    """Whether a planned step does nothing the opening line of a placed call has not already
    done: its instruction greets, says who is calling or asks whether now suits (or its name
    calls it the introduction), and nothing else is left once that is taken out. A
    capitalised word is a name (the business's) and adds no job of its own."""
    text = " ".join(step.instruction.split())
    if not (_OPENING_ACTS.search(text) or _OPENING_STEP_NAME.match(step.name)):
        return False
    rest = _OPENING_ACTS.sub(" ", text)
    jobs = [
        word
        for token in rest.split()
        if (word := token.strip(".,;:!?()\"'"))
        and len(word) > 3
        and not word[0].isupper()
        and word.casefold() not in _PLACING_WORDS
    ]
    return not jobs


def opening_folded(plan: OwnerPlan) -> OwnerPlan:
    """`plan` for a placed call without a first numbered step that only redoes the opening
    (`opening_only`): the opening already says who is calling and why and asks whether now
    suits, so a step kept for it says it all a second time (Rytu Khata, 27-28 Nov 2026: an
    "Introduction" step restating the opening before "Why we called" restated it again).
    Its ways out move to the step after it, ways into it go there too, and the steps after
    it are numbered one less, so the owner's plan and every check of it agree. Unchanged when
    fewer than two numbered steps would be left."""
    numbered = [step for step in plan.steps if step.number is not None]
    if len(numbered) < 3 or not opening_only(numbered[0]):
        return plan
    lead, after = numbered[0], numbered[1]
    lead_key, after_key = lead.key, after.key
    have = {(name_key(b.when), name_key(b.goes_to)) for b in after.branches}
    moved = tuple(
        b
        for b in lead.branches
        if name_key(b.goes_to) != after_key and (name_key(b.when), name_key(b.goes_to)) not in have
    )

    def kept(step: PlannedStep) -> PlannedStep:
        branches = tuple(
            replace(b, goes_to=after.name) if b.goes_to and name_key(b.goes_to) == lead_key else b
            for b in (step.branches + moved if step is after else step.branches)
        )
        number = step.number - 1 if step.number is not None else None
        return replace(step, branches=branches, number=number)

    return OwnerPlan(tuple(kept(step) for step in plan.steps if step is not lead))


#: A case where the person cannot do something ("Cannot log in", "They are unable to find
#: the icon"), with where "still" goes in it.
_CANNOT: Final = re.compile(
    r"^\s*(?P<who>(?:they|the person|he|she|the caller)\s+(?:(?:is|are)\s+)?)?"
    r"(?P<cannot>cannot|can'?t|can not|could not|couldn'?t|unable to|"
    r"do(?:es)? not know how to|do(?:es)?n'?t know how to)\b",
    re.IGNORECASE,
)
_STILL: Final = re.compile(r"\b(?:still|after)\b", re.IGNORECASE)
LAST_RESORT_TAIL: Final = " after being guided step by step"


def last_resort_condition(when: str) -> str:
    """`when`, a case where the person cannot do something, said as the last resort: "Cannot
    log in" reads "Still cannot log in after being guided step by step". A call back is
    offered only when the agent cannot help after trying everything it can (founder, 25 Nov
    2026: the agent guides the person through every step in detail), and a condition that
    says so keeps the in-call model from reaching for it at the first difficulty. Any other
    condition, or one already saying so, is returned as it is."""
    said = " ".join(when.split())
    found = _CANNOT.match(said)
    if found is None or _STILL.search(said):
        return said
    who = found.group("who") or ""
    cannot = found.group("cannot")
    rest = said[found.end() :].rstrip(" .")
    if who:
        return f"{who}still {cannot}{rest}{LAST_RESORT_TAIL}"
    return f"Still {cannot.lower()}{rest}{LAST_RESORT_TAIL}"


def last_resort(branch: PlanBranch) -> str:
    """The condition of an owner's way out as the script states it: a call back for someone
    who cannot do something in its last-resort form (`last_resort_condition`), every other
    condition in the owner's own words."""
    when = " ".join(branch.when.split())
    return last_resort_condition(when) if branch.goes_to == CALL_BACK else when


def _target_words(goes_to: str) -> str:
    if goes_to in SPECIAL_TARGETS:
        return goes_to
    return f'the step "{goes_to}"' if goes_to else "where the owner's words say"


def plan_block(plan: OwnerPlan) -> str:
    """The plan as the writer reads it, one step per line and one way out per line below it,
    each named in the owner's words, a call back for someone who cannot do something in its
    last-resort form (`last_resort`)."""
    lines = []
    for step in plan.steps:
        home = plan.side_home(step) if step.number is None else None
        head = (
            f'Step {step.number} "{step.name}"'
            if step.number is not None
            else f'Side step "{step.name}" (a scenario of step {home}, reached only by a way out)'
            if home is not None
            else f'Side step "{step.name}" (reached only by a way out)'
        )
        outcome = f" Outcome: {step.outcome}" if step.outcome else ""
        lines.append(f"{head}: {step.instruction}{outcome}")
        lines += [
            f'  - way out when "{last_resort(b)}" ({b.said}) goes to {_target_words(b.goes_to)}'
            for b in step.branches
        ]
        if step.number is not None and not step.branches:
            lines.append("  - no ways out: guide them through it")
    if plan.over:
        names = ", ".join(f'"{step.name}"' for step in plan.over)
        lines.append(
            f"Only {MAX_SCRIPT_STAGES} steps fit a script: write the first {MAX_SCRIPT_STAGES} "
            f"and name {names} in the goal as left out."
        )
    return "\n".join(lines)


#: A step that is only where a way out goes. Call back, end and hand over are end points the
#: engine acts on (`call_script.SPECIAL_TARGETS`); written as steps they draw a second path
#: beside the way out and say nothing the platform's own call-back and closing rules do not.
_END_POINT_NAME: Final = re.compile(
    r"^(?:(?:arrange|schedule|offer|book)\s+(?:a\s+)?)?(?:call\s*back|callback|end(?:\s+the)?"
    r"(?:\s+call)?|hang\s*up|hand\s*over|transfer(?:\s+the\s+call)?)$",
    re.IGNORECASE,
)


def _reach(script: CallScript, starts: set[int]) -> set[str]:
    """Where the call can go from the stages `starts`, following the scenarios of the same
    step they lead to: stage ids and end points."""
    steps = stage_steps(script.stages)
    own = {steps[i] for i in starts}
    by_id = {stage.id: i for i, stage in enumerate(script.stages)}
    seen = set(starts)
    todo = list(starts)
    out: set[str] = set()
    while todo:
        for target in next_steps(script, todo.pop()):
            out.add(target)
            i = by_id.get(target)
            if i is not None and i not in seen and steps[i] in own:
                seen.add(i)
                todo.append(i)
    return out


def plan_problems(
    script: CallScript, plan: OwnerPlan | None, before: CallScript | None = None
) -> list[str]:
    """Where `script` departs from the owner's plan: a step missing, duplicated, out of order
    or not the owner's; an outcome missing; a way out the owner named missing or one they did
    not name; a call back, end or hand over written as a step. With `before` (an edit of
    Pip's own draft), a departure that draft already had is not the edit's."""
    if plan is None or script.raw_override is not None or not script.stages:
        return []
    found = _plan_problems(script, plan)
    if before is not None and before.stages:
        had = set(_plan_problems(before, plan))
        found = [problem for problem in found if problem not in had]
    return found


def _plan_problems(script: CallScript, plan: OwnerPlan) -> list[str]:
    stages = script.stages
    steps = stage_steps(stages)
    keys = [name_key(stage.name) for stage in stages]
    planned = plan.fitting
    planned_keys = {step.key for step in planned}
    at: dict[str, list[int]] = {
        step.key: [i for i, key in enumerate(keys) if key == step.key] for step in planned
    }
    problems: list[str] = []
    for step in planned:
        where = at[step.key]
        if not where:
            if step.number is not None:
                outcome = f', with the outcome "{step.outcome}"' if step.outcome else ""
                problems.append(
                    f'stages: the owner\'s step {step.number} "{step.name}" is missing; add it '
                    f'as step {step.number}, named "{step.name}"{outcome}.'
                )
            else:
                problems.append(
                    f'stages: the owner\'s step "{step.name}" is missing; add it as a scenario '
                    f'of the step whose way out reaches it, named "{step.name}".'
                )
            continue
        if len({steps[i] for i in where}) > 1:
            problems.append(
                f'stages.{where[1]}: "{step.name}" is written as {len(where)} steps; the owner '
                "gave it once, so keep one step by that name and fold the rest into it."
            )
    numbered = [step for step in planned if step.number is not None and at[step.key]]
    order = [steps[at[step.key][0]] for step in numbered]
    if any(b <= a for a, b in pairwise(order)):
        wanted = ", ".join(f'{n}. "{step.name}"' for n, step in enumerate(numbered, 1))
        problems.append(
            f"stages: the owner's steps are not in the owner's order; number them as the "
            f"owner did: {wanted}."
        )
    outcomes = {o.step: o.outcome for o in script.step_outcomes}
    for step in numbered:
        number = steps[at[step.key][0]]
        if step.outcome and not outcomes.get(number, "").strip():
            problems.append(
                f'step_outcomes: step {number} "{step.name}" has no outcome; give it the '
                f'owner\'s: "{step.outcome}".'
            )
    planned_steps = {steps[i] for step in planned for i in at[step.key]}
    closes = any(closes_the_call(stages[i]) for i in {i for w in at.values() for i in w})
    last_step = max(steps)
    for number in sorted(set(steps) - planned_steps):
        members = [i for i, s in enumerate(steps) if s == number]
        if all(_END_POINT_NAME.match(stages[i].name.strip()) for i in members):
            for i in members:
                problems.append(
                    f'stages.{i}: "{stages[i].name}" is written as a step of its own; call '
                    "back, end and hand over are where a way out goes (call_back, end, "
                    "hand_over), never steps. Take it out and point the ways out that reach "
                    "it there."
                )
            continue
        if number == last_step and not closes and any(closes_the_call(stages[i]) for i in members):
            continue
        for i in members:
            if keys[i] not in planned_keys:
                problems.append(
                    f'stages.{i}: "{stages[i].name}" is a step the owner did not ask for; fold '
                    "what it does into the owner's step it belongs to, or leave it out."
                )
    ids_of = {step.key: {stages[i].id for i in at[step.key]} for step in planned}
    for step in planned:
        where = at[step.key]
        if not where:
            continue
        starts = (
            {i for i, s in enumerate(steps) if s == steps[where[0]]}
            if step.number is not None
            else set(where)
        )
        reach = _reach(script, starts)
        for branch in step.branches:
            goes = branch.goes_to
            if not goes:
                continue
            if goes in SPECIAL_TARGETS:
                ok = goes in reach
                said = goes
            else:
                target = plan.named(goes)
                ids = ids_of.get(target.key, set()) if target is not None else set()
                if not ids:
                    continue
                ok = bool(ids & reach)
                said = f'the step "{goes}"'
            if not ok:
                problems.append(
                    f'stages.{where[0]}.branches: the owner\'s step "{step.name}" has the way '
                    f'out "{branch.when}" going to {said}; give it that way out.'
                )
        own = {b.goes_to for b in step.branches} & SPECIAL_TARGETS
        allowed = own | _platform_ways(step, plan)
        # A side step sharing this step's number has ways out of its own.
        mine = [i for i in starts if keys[i] == step.key or keys[i] not in planned_keys]
        for i in mine:
            for way in stages[i].branches:
                if way.target in SPECIAL_TARGETS and way.target not in allowed:
                    problems.append(
                        f'stages.{i}.branches: the way out "{way.when}" goes to '
                        f'{way.target}, which the owner did not give step "{step.name}"; '
                        "guide them through the step instead and keep only the ways out the "
                        "owner named for it."
                    )
        # Another case the owner sends to a call back ("Busy now") is not a difficulty.
        other_cases = {
            name_key(b.when) for b in step.branches if last_resort(b) == " ".join(b.when.split())
        }
        for branch in step.branches:
            wanted = last_resort(branch)
            if wanted == " ".join(branch.when.split()):
                continue
            plain = [
                (i, way.when)
                for i in mine
                for way in stages[i].branches
                if way.target == CALL_BACK
                and not _STILL.search(way.when)
                and name_key(way.when) not in other_cases
            ]
            for i, when in plain:
                problems.append(
                    f'stages.{i}.branches: the way out "{when}" offers a call back at the first '
                    f'difficulty; it is the last resort, so say "{wanted}", and have the '
                    "step's instruction guide them through it in detail first."
                )
    problems += _side_problems(script, plan, at)
    return list(dict.fromkeys(problems))


def _platform_ways(step: PlannedStep, plan: OwnerPlan) -> set[str]:
    """The end points a plan step may go to that the owner did not write: on the first step,
    a call back for someone busy now and the end for someone not interested or the wrong
    person, which every placed call needs because its opening asks whether they can talk
    (`script_assist.way_out_problems`); on the last, the end. Nowhere else: a step the owner
    gave no ways out is one the agent guides them through (founder, 25 Nov 2026)."""
    numbers = [s.number for s in plan.numbered if s.number is not None]
    if not numbers or step.number is None:
        return set()
    if step.number == min(numbers):
        return {CALL_BACK, END_OF_CALL}
    return {END_OF_CALL} if step.number == max(numbers) else set()


def _side_problems(script: CallScript, plan: OwnerPlan, at: dict[str, list[int]]) -> list[str]:
    """A side step placed anywhere but its home (`OwnerPlan.side_home`), or with no way on of
    its own, so the call would fall from it into the next step."""
    stages = script.stages
    steps = stage_steps(stages)
    found: list[str] = []
    for side in plan.fitting:
        home = plan.side_home(side) if side.number is None else None
        anchor = next((s for s in plan.numbered if s.number == home), None)
        if anchor is None or not at.get(side.key) or not at.get(anchor.key):
            continue
        want = steps[at[anchor.key][0]]
        for i in at[side.key]:
            if steps[i] != want:
                found.append(
                    f'stages.{i}: "{side.name}" is reached only by a way out, so it is a '
                    f'scenario of step {want}, beside "{anchor.name}", never a step of its own '
                    "or one after the last step; give it that step's number."
                )
            elif not stages[i].otherwise:
                found.append(
                    f'stages.{i}: "{side.name}" has no Otherwise, so the call would fall from '
                    "it into the next step; give it an Otherwise to where its own ways out go."
                )
    return found


def with_owner_plan(script: CallScript, plan: OwnerPlan | None) -> CallScript:
    """`script` with each step that is the owner's by name carrying the owner's exact name and,
    for a numbered step, the owner's outcome: the owner wrote both, so code keeps them rather
    than spending a repair round on a model's paraphrase. An outcome in an Indian script stays
    the model's, since outcomes are read as English instructions."""
    if plan is None or script.raw_override is not None or not script.stages:
        return script
    script = _last_resort_ways(_sides_placed(script, plan), plan)
    steps = stage_steps(script.stages)
    stages = list(script.stages)
    outcomes = {o.step: o.outcome for o in script.step_outcomes}
    pinned: set[int] = set()
    for step in plan.fitting:
        where = [i for i, stage in enumerate(stages) if name_key(stage.name) == step.key]
        if not where:
            continue
        if len(step.name) <= STAGE_TITLE_MAX:
            for i in where:
                if stages[i].name != step.name:
                    stages[i] = stages[i].model_copy(update={"name": step.name})
        number = steps[where[0]]
        if (
            step.number is not None
            and step.outcome
            and number not in pinned
            and len(step.outcome) <= STEP_OUTCOME_MAX
            and not has_indic_letters(step.outcome)
        ):
            outcomes[number] = step.outcome
            pinned.add(number)
    out = script.model_copy(
        update={
            "stages": stages,
            "step_outcomes": [
                StepOutcome(step=n, outcome=text)
                for n, text in sorted(outcomes.items())
                if text.strip()
            ],
        }
    )
    return script if out == script else CallScript.model_validate(out.model_dump())


def _side_default(side: PlannedStep, rest: Sequence[ConversationStage]) -> str:
    """Where a side step goes when none of its ways out holds: the step its owner's first way
    out to a step names ("Yes: go to App on the home screen"), else its first end point. The
    call then never falls from the side scenario into whatever step follows it."""
    by_key = {name_key(stage.name): stage.id for stage in reversed(rest)}
    for branch in side.branches:
        if branch.goes_to and branch.goes_to not in SPECIAL_TARGETS:
            target = by_key.get(name_key(branch.goes_to))
            if target is not None:
                return target
    return next((b.goes_to for b in side.branches if b.goes_to in SPECIAL_TARGETS), "")


def _sides_placed(script: CallScript, plan: OwnerPlan) -> CallScript:
    """`script` with each of the owner's side steps moved to its home (`OwnerPlan.side_home`)
    as a scenario of that step, after its other scenarios, with an Otherwise of its own
    (`_side_default`), and the steps numbered 1, 2, 3 ... again. A model told so still put
    "Not registered" as a step after the close (25 Nov 2026); where it goes is the plan's to
    say, so code places it rather than spending a repair round."""
    numbers = stage_steps(script.stages)
    stages = [
        stage if stage.step == n else stage.model_copy(update={"step": n})
        for stage, n in zip(script.stages, numbers, strict=True)
    ]
    changed = False
    for side in plan.fitting:
        home = plan.side_home(side) if side.number is None else None
        anchor = next((s for s in plan.numbered if s.number == home), None)
        if anchor is None:
            continue
        moving = [stage for stage in stages if name_key(stage.name) == side.key]
        rest = [stage for stage in stages if name_key(stage.name) != side.key]
        want = next((s.step for s in rest if name_key(s.name) == anchor.key), None)
        if not moving or want is None:
            continue
        default = _side_default(side, rest)
        placed = [
            stage.model_copy(update={"step": want, "otherwise": stage.otherwise or default})
            for stage in moving
        ]
        after = max(i for i, stage in enumerate(rest) if stage.step == want) + 1
        before = rest[after - 1]
        if not before.otherwise and after < len(rest):
            # Its way on was the stage after it in the list, which is now the side scenario:
            # it goes on to the next step as it did, and never into "Not registered".
            rest = [
                *rest[: after - 1],
                before.model_copy(update={"otherwise": rest[after].id}),
                *rest[after:],
            ]
        candidate = [*rest[:after], *placed, *rest[after:]]
        if candidate != stages:
            stages, changed = candidate, True
    if not changed:
        return script
    order = {n: k for k, n in enumerate(sorted({stage.step or 0 for stage in stages}), 1)}
    stages = [stage.model_copy(update={"step": order[stage.step or 0]}) for stage in stages]
    # An outcome moves with its step; the side step's own former step had none of the owner's.
    sides = _side_keys(plan)
    still = {
        n
        for stage, n in zip(script.stages, numbers, strict=True)
        if name_key(stage.name) not in sides
    }
    outcomes = [
        o.model_copy(update={"step": order[o.step]})
        for o in script.step_outcomes
        if o.step in still and o.step in order
    ]
    return CallScript.model_validate(
        script.model_copy(update={"stages": stages, "step_outcomes": outcomes}).model_dump()
    )


def _side_keys(plan: OwnerPlan) -> set[str]:
    return {step.key for step in plan.fitting if step.number is None}


def _last_resort_ways(script: CallScript, plan: OwnerPlan) -> CallScript:
    """`script` with each way out to the call back on a plan step that offers it for a case
    where the person cannot do something said in its last-resort form
    (`last_resort_condition`). Only a step the owner sent such a case to the call back from:
    elsewhere a way out to the call back is not the owner's, and `plan_problems` names it."""
    steps = stage_steps(script.stages)
    by_key: dict[str, int] = {}
    for i, stage in enumerate(script.stages):
        by_key.setdefault(name_key(stage.name), steps[i])
    homes = {
        by_key[step.key]
        for step in plan.fitting
        if step.key in by_key
        and any(last_resort(b) != " ".join(b.when.split()) for b in step.branches)
    }
    stages = []
    for stage, n in zip(script.stages, steps, strict=True):
        if n not in homes:
            stages.append(stage)
            continue
        branches = [
            b.model_copy(update={"when": last_resort_condition(b.when)})
            if b.target == CALL_BACK
            else b
            for b in stage.branches
        ]
        stages.append(
            stage if branches == stage.branches else stage.model_copy(update={"branches": branches})
        )
    out = script.model_copy(update={"stages": stages})
    return script if out == script else out


__all__ = [
    "OwnerPlan",
    "PlanBranch",
    "PlannedStep",
    "name_key",
    "numbered_items",
    "opening_folded",
    "opening_only",
    "owner_plan",
    "plan_block",
    "plan_problems",
    "with_owner_plan",
]
