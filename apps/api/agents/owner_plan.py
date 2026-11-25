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
from dataclasses import dataclass
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
    rf"(?P<label>[^\W\d_][^:.!?{_QUOTES}\n]{{0,59}}?):(?=\s|$)",
    re.MULTILINE,
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
    marks = [m for m in _LABEL.finditer(text) if len(m.group("label").split()) <= _LABEL_WORDS]
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


def owner_plan(text: str | None) -> OwnerPlan | None:
    """The steps `text` lays out, or None when it lays out none: at least two numbered items,
    each starting with its name ("Login: ..."), and at least half giving an outcome."""
    if not text:
        return None
    items = _numbered_items(text)
    if len(items) < 2:
        return None
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


def _target_words(goes_to: str) -> str:
    if goes_to in SPECIAL_TARGETS:
        return goes_to
    return f'the step "{goes_to}"' if goes_to else "where the owner's words say"


def plan_block(plan: OwnerPlan) -> str:
    """The plan as the writer reads it, one step per line and one way out per line below it,
    each named in the owner's words."""
    lines = []
    for step in plan.steps:
        head = (
            f'Step {step.number} "{step.name}"'
            if step.number is not None
            else f'Side step "{step.name}" (reached only by a way out)'
        )
        outcome = f" Outcome: {step.outcome}" if step.outcome else ""
        lines.append(f"{head}: {step.instruction}{outcome}")
        lines += [
            f'  - way out when "{b.when}" ({b.said}) goes to {_target_words(b.goes_to)}'
            for b in step.branches
        ]
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
    named_specials = {b.goes_to for s in planned for b in s.branches} & SPECIAL_TARGETS
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
        if step.number is None or not step.branches:
            continue
        own = {b.goes_to for b in step.branches} & SPECIAL_TARGETS
        # A side step sharing this step's number has ways out of its own.
        for i in (i for i in starts if keys[i] == step.key or keys[i] not in planned_keys):
            for way in stages[i].branches:
                if way.target in named_specials and way.target not in own:
                    problems.append(
                        f'stages.{i}.branches: the way out "{way.when}" goes to '
                        f'{way.target}, which the owner did not give step "{step.name}"; '
                        "keep only the ways out the owner named for it."
                    )
    return problems


def with_owner_plan(script: CallScript, plan: OwnerPlan | None) -> CallScript:
    """`script` with each step that is the owner's by name carrying the owner's exact name and,
    for a numbered step, the owner's outcome: the owner wrote both, so code keeps them rather
    than spending a repair round on a model's paraphrase. An outcome in an Indian script stays
    the model's, since outcomes are read as English instructions."""
    if plan is None or script.raw_override is not None or not script.stages:
        return script
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


__all__ = [
    "OwnerPlan",
    "PlanBranch",
    "PlannedStep",
    "name_key",
    "owner_plan",
    "plan_block",
    "plan_problems",
    "with_owner_plan",
]
