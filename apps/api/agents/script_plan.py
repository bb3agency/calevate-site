"""A call script's structure, decided by code before any words are written (DESIGN §3.1).

A `ScriptPlan` is the steps of a call in order: each step's name, what it does (an English
intent), what is true once it is done, its ways out, the details it collects, and whether it
is a side step (a scenario of a numbered step, reached only by a way out). The step writer
(`workers/step_writer`) writes the words of one step at a time against it and never re-plans.

Where a plan comes from, in this order:

1. the owner's own steps in their request (`owner_plan.owner_plan`);
2. the owner's steps in the main task, or the main task's numbered list read as steps
   (`campaign_script_ask.TASK_STEPS_INSTRUCTION`), both read into an `OwnerPlan`;
3. the script being changed, when the request lays out no steps: an edit keeps its shape;
4. a model-proposed outline for a free-form request, read through the same `OwnerPlan`
   parse and checked here (`outline_problems`) before any words are written;
5. the trade's playbook steps (`trade_playbooks.playbook_for`).

The rules the writer prompts used to state, and code can keep, live here instead:
renumbering, side steps placed as scenarios of their home step, call back / end / hand over
kept as end points (never steps), the ways out every placed call needs on its first step,
and a first step that never asks again whether now is a good time (the opening did).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final, Literal

from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    MAX_SCRIPT_STAGES,
    MAX_STAGE_BRANCHES,
    MAX_STEP_EXAMPLE_TURNS,
    SPECIAL_TARGETS,
    STAGE_DETAIL_MAX,
    STAGE_TITLE_MAX,
    STEP_EXAMPLE_MAX,
    STEP_OUTCOME_MAX,
    CallScript,
    ConversationStage,
    StageBranch,
    StepOutcome,
    stage_steps,
)
from calevate_shared.spoken_guard import has_indic_letters

from apps.api.agents.business_fit import UNKNOWN, BusinessFit
from apps.api.agents.owner_plan import (
    _CLOSING_LABEL,
    _END_POINT_NAME,
    _NUMBER_MARK,
    OwnerPlan,
    PlannedStep,
    last_resort,
    name_key,
)
from apps.api.agents.trade_playbooks import (
    OPENING_STEP_TITLES,
    playbook_for,
)

if TYPE_CHECKING:
    from apps.api.agents.starter_plans import Plan

PlanSource = Literal["owner", "task", "script", "outline", "playbook"]


@dataclass(frozen=True, slots=True)
class ExampleLimits:
    """How much a step's examples hold (`call_script.StepExamples`): at least `turns_min`
    ordinary turns are written per language, at most `turns_max` kept, each line at most
    `line_max` characters. The web reads these from the holder's read
    (`example_limits`) rather than spelling them again."""

    turns_min: int
    turns_max: int
    line_max: int


EXAMPLE_LIMITS: Final = ExampleLimits(
    turns_min=3, turns_max=MAX_STEP_EXAMPLE_TURNS, line_max=STEP_EXAMPLE_MAX
)

#: The ways out every placed call needs on its first step (`script_assist.way_out_problems`):
#: the opening asks whether they can talk, so "not now" and "not for me" are always met.
BUSY_WAY_OUT: Final = "They are busy now or say they will do it later"
NOT_FOR_THEM_WAY_OUT: Final = "They are not interested, or it is the wrong person"


@dataclass(frozen=True, slots=True)
class WayOut:
    """Where the call goes when `when` (the person's words, in plain English) holds: one of
    `SPECIAL_TARGETS`, or another step's `key`."""

    when: str
    to: str


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One step of the plan. `number` is its column in the call flow; a side step shares its
    home step's number and is placed after it."""

    key: str
    name: str
    intent: str
    number: int
    outcome: str = ""
    ways_out: tuple[WayOut, ...] = ()
    collect: tuple[str, ...] = ()
    side: bool = False
    #: Where a side step goes when none of its ways out holds; "" for the next step.
    otherwise: str = ""
    #: The owner wrote the name and outcome, so code pins them (`owner_plan.with_owner_plan`).
    owners: bool = False


@dataclass(frozen=True, slots=True)
class ScriptPlan:
    steps: tuple[PlanStep, ...]
    source: PlanSource
    #: The owner's plan this was read from, for `owner_plan.plan_problems` and its pins.
    owner: OwnerPlan | None = field(default=None, compare=False)

    def step(self, key: str) -> PlanStep | None:
        return next((s for s in self.steps if s.key == key), None)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.steps)

    def index(self, key: str) -> int:
        return self.keys.index(key)

    @property
    def first(self) -> PlanStep | None:
        return self.steps[0] if self.steps else None

    @property
    def close(self) -> PlanStep | None:
        numbered = [s for s in self.steps if not s.side]
        return numbered[-1] if numbered else None

    def before(self, key: str) -> PlanStep | None:
        """The numbered step the call reaches just before `key`, for the step writer."""
        at = self.index(key)
        return next((s for s in reversed(self.steps[:at]) if not s.side), None)


_SLUG: Final = re.compile(r"[^a-z0-9]+")


def _key(name: str, taken: set[str]) -> str:
    """A section id for `name`, unique among `taken` (`call_script.SECTION_ID_PATTERN`)."""
    base = _SLUG.sub("-", name.casefold()).strip("-")[:32] or "step"
    if not base[0].isalnum():
        base = f"s{base}"
    key, n = base, 2
    while key in taken:
        key = f"{base[:30]}-{n}"
        n += 1
    taken.add(key)
    return key


def _special(name: str) -> str | None:
    """The end point a step named for one is ("Call back", "End the call"), or None."""
    if not _END_POINT_NAME.match(name.strip()):
        return None
    folded = name.casefold()
    if "hand" in folded or "transfer" in folded:
        return HAND_OVER
    if "back" in folded:
        return CALL_BACK
    return END_OF_CALL


def plan_from_owner(
    plan: OwnerPlan, *, source: PlanSource = "owner", placed: bool = False
) -> ScriptPlan:
    """The owner's steps as a plan: numbered steps in order, each side step right after its
    home step (`OwnerPlan.side_home`), a step that is only an end point dropped and the ways
    to it sent to that end point, and on a placed call the first step's required ways out."""
    taken: set[str] = set()
    ends = {step.key: kind for step in plan.fitting if (kind := _special(step.name))}
    kept = [step for step in plan.fitting if step.key not in ends]
    keys = {step.key: _key(step.name, taken) for step in kept}

    def target(goes_to: str) -> str:
        if goes_to in SPECIAL_TARGETS:
            return goes_to
        if not goes_to:
            return ""
        key = name_key(goes_to)
        return ends.get(key) or keys.get(key, "")

    numbered = [step for step in kept if step.number is not None]
    number_of = {step.key: n for n, step in enumerate(numbered, 1)}
    built: list[PlanStep] = []
    for step in numbered:
        owned = _owners_step(step, keys[step.key], number_of[step.key], target)
        if placed and not built:
            owned = replace(owned, intent=without_opening_acts(owned.intent) or owned.intent)
        built.append(owned)
    for side in (step for step in kept if step.number is None):
        home = plan.side_home(side)
        anchor = next((s for s in numbered if s.number == home), None)
        if anchor is None:
            continue
        ways = _ways(side, target)
        otherwise = next((w.to for w in ways if w.to not in SPECIAL_TARGETS), "") or next(
            (w.to for w in ways if w.to in SPECIAL_TARGETS), END_OF_CALL
        )
        at = max(i for i, s in enumerate(built) if s.number == number_of[anchor.key]) + 1
        built.insert(
            at,
            PlanStep(
                key=keys[side.key],
                name=side.name[:STAGE_TITLE_MAX],
                intent=owners_text(side, target),
                number=number_of[anchor.key],
                ways_out=ways,
                side=True,
                otherwise=otherwise,
                owners=source == "owner",
            ),
        )
    out = ScriptPlan(tuple(built), source, owner=plan)
    return with_required_ways(out) if placed else out


def _ways(step: PlannedStep, target: Callable[[str], str]) -> tuple[WayOut, ...]:
    ways = []
    for branch in step.branches:
        to = target(branch.goes_to)
        if to:
            ways.append(WayOut(when=last_resort(branch), to=to))
    return tuple(ways[:MAX_STAGE_BRANCHES])


#: A clause of the first step that asks for permission to talk, which a placed call's
#: opening already asks (`call_rules.PLACED_OPENING_RULE`).
_PERMISSION_CLAUSE: Final = re.compile(
    r"(?:,?\s*(?:and\s+|then\s+)*)?(?:ask|check)(?:\s+them)?\s+(?:if|whether)\s+(?:now\s+is|"
    r"it\s+is|this\s+is)\s+a\s+good\s+time(?:\s+to\s+talk)?|"
    r"(?:,?\s*(?:and\s+|then\s+)*)?ask\s+(?:if|whether)\s+(?:they\s+)?can\s+talk(?:\s+now)?",
    re.IGNORECASE,
)


def without_permission_ask(text: str) -> str:
    """`text` without its clause asking whether now is a good time, everything else kept word
    for word: on a placed call the opening asks it, and a first step that asks again was asked
    three times on the call of 26 Nov 2026, while dropping the whole step lost who is calling
    and why (production, 26 Nov 2026, 23:20 IST)."""
    out = _PERMISSION_CLAUSE.sub("", text)
    out = re.sub(r"\s+([.,;])", r"\1", out)
    return " ".join(out.split()).replace(",.", ".").strip(" ,")


#: A clause of the first step that says who is calling ("right after the opening, say who is
#: calling and from <Business>"), which a placed call's opening already says
#: (`call_rules.PLACED_OPENING_RULE`). The business is a capitalised name.
_WHO_CLAUSE: Final = re.compile(
    r"(?i:(?:(?:right\s+)?after\s+the\s+opening(?:\s+line)?,?\s*)?"
    r"(?:,?\s*(?:and\s+|then\s+)*)?say\s+who\s+(?:is\s+calling|you\s+are))"
    r"(?:\s+(?i:and\s+from)\s+[A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*)*)?,?"
)


def without_opening_acts(text: str) -> str:
    """`text` without its clauses asking whether now suits (`without_permission_ask`) and
    saying who is calling, everything else kept word for word: on a placed call the opening
    says both, and a first step told to say them again said them again (Rytu Khata,
    28 Nov 2026)."""
    out = _WHO_CLAUSE.sub("", without_permission_ask(text))
    out = re.sub(r"\s+([.,;])", r"\1", out)
    return " ".join(out.split()).replace(",.", ".").strip(" ,")


def owner_notes(text: str) -> str:
    """What an owner's request says around its numbered steps (a tone, "Rules: ..."), for every
    step's request: the steps themselves reach each step as its own plan entry."""
    first = _NUMBER_MARK.search(text)
    if first is None:
        return text
    head = text[: first.start()]
    closing = _CLOSING_LABEL.search(text, first.start())
    tail = text[closing.start() :] if closing is not None else ""
    head = re.sub(r"\bsteps?,?\s+in\s+this\s+order\s*:?\s*$", "", head.strip(), flags=re.I)
    return " ".join(f"{head} {tail}".split())


def owners_text(step: PlannedStep, target: Callable[[str], str]) -> str:
    """The owner's own words for a step, verbatim: its instruction, then each case they named
    that goes nowhere a way out can ("- Android: open Chrome ..."), which is guidance for the
    step rather than a branch. The written step keeps these words as its instruction
    (`script_writer`), so a model can never paraphrase the owner's detail away (Rytu Khata,
    26 Nov 2026: the Android and iPhone paths and "one field at a time" were lost)."""
    said = [step.instruction or step.name]
    said += [
        f"{branch.when}: {branch.said}" for branch in step.branches if not target(branch.goes_to)
    ]
    return " ".join(part.strip() for part in said if part.strip())


def _owners_step(
    step: PlannedStep, key: str, number: int, target: Callable[[str], str]
) -> PlanStep:
    outcome = step.outcome if len(step.outcome) <= STEP_OUTCOME_MAX else ""
    return PlanStep(
        key=key,
        name=step.name[:STAGE_TITLE_MAX],
        intent=owners_text(step, target),
        number=number,
        outcome="" if has_indic_letters(outcome) else outcome,
        ways_out=_ways(step, target),
        owners=True,
    )


def with_required_ways(plan: ScriptPlan) -> ScriptPlan:
    """`plan` with the first step's ways out for "busy now" (to the call back) and "not
    interested or the wrong person" (to the end), each added only where the step has no way
    to that end point already: a placed call's opening asks whether they can talk."""
    first = plan.first
    if first is None or len(plan.steps) < 2:
        return plan
    have = {w.to for w in first.ways_out}
    added = [
        WayOut(when, to)
        for when, to in ((BUSY_WAY_OUT, CALL_BACK), (NOT_FOR_THEM_WAY_OUT, END_OF_CALL))
        if to not in have
    ]
    if not added:
        return plan
    ways = (*first.ways_out, *added)[:MAX_STAGE_BRANCHES]
    return replace(plan, steps=(replace(first, ways_out=ways), *plan.steps[1:]))


def plan_from_script(script: CallScript) -> ScriptPlan:
    """The plan a saved script already has: its stages, order, numbers, outcomes and ways out
    as they stand, so a rewrite of its words keeps its structure exactly."""
    steps = stage_steps(script.stages)
    outcomes = {o.step: o.outcome for o in script.step_outcomes}
    seen: set[int] = set()
    built: list[PlanStep] = []
    for stage, number in zip(script.stages, steps, strict=True):
        side = number in seen
        seen.add(number)
        built.append(
            PlanStep(
                key=stage.id,
                name=stage.name,
                intent=stage.instruction,
                number=number,
                outcome="" if side else outcomes.get(number, ""),
                ways_out=tuple(WayOut(b.when, b.target) for b in stage.branches),
                collect=tuple(stage.collect),
                side=side,
                otherwise=stage.otherwise,
            )
        )
    return ScriptPlan(tuple(built), "script")


def plan_from_playbook(
    trade: str | None,
    *,
    placed: bool,
    plans: Mapping[str, Plan] | None = None,
    fit: BusinessFit = UNKNOWN,
) -> ScriptPlan:
    """The trade's step plan (`trade_playbooks.playbook_for`), the business's own step titles
    where it has them. On a placed call the steps the opening already does (a good time, who
    is calling and why) are left out: the first step starts from their yes."""
    from apps.api.agents.starters import trade_for, vertical_of

    job = "call_leads" if placed else "answer_calls"
    book = playbook_for(job, trade_for(vertical_of(trade), fit), fit)
    mine = (plans or {}).get(job)
    titles = (
        [own.title for own in mine]
        if mine is not None and len(mine) == len(book.steps)
        else [step.title for step in book.steps]
    )
    taken: set[str] = set()
    built: list[PlanStep] = []
    for step, title in zip(book.steps, titles, strict=True):
        if placed and step.title in OPENING_STEP_TITLES:
            continue
        built.append(
            PlanStep(
                key=_key(title, taken),
                name=title[:STAGE_TITLE_MAX],
                intent=step.instruction,
                number=len(built) + 1,
                outcome=step.exit_when,
            )
        )
    out = ScriptPlan(tuple(built), "playbook")
    return with_required_ways(out) if placed else out


#: An intent that has the first step greet, say who is calling, or ask whether now suits.
_REDOES_OPENING: Final = re.compile(
    r"\b(?:good time|now suits|(?:can|could) (?:they|you) talk|right time|greet|"
    r"introduce (?:yourself|the agent)|say who (?:is calling|you are))\b",
    re.IGNORECASE,
)


def outline_problems(plan: ScriptPlan) -> list[str]:
    """What makes a model-proposed outline unusable before a word is written: too few or too
    many steps, a first step that redoes the opening, or a step with no intent."""
    numbered = [s for s in plan.steps if not s.side]
    problems = []
    if len(numbered) < 2:
        problems.append("steps: give at least two steps")
    if len(plan.steps) > MAX_SCRIPT_STAGES:
        problems.append(f"steps: give at most {MAX_SCRIPT_STAGES} steps")
    first = plan.first
    if first is not None and _REDOES_OPENING.search(f"{first.name} {first.intent}"):
        problems.append(
            f'steps.0: "{first.name}" greets or asks whether now is a good time, which the '
            "opening already did; start from their yes"
        )
    problems += [
        f"steps.{i}: has no instruction" for i, s in enumerate(plan.steps) if not s.intent.strip()
    ]
    return problems


def skeleton(plan: ScriptPlan, base: CallScript | None = None) -> CallScript:
    """The script `plan` lays out, with each step's intent standing as its instruction until
    the step writer writes it: stages, numbers, ways out, side steps' Otherwise, collect
    lists and the outcomes the plan holds. Everything outside the stages is kept from `base`."""
    stages = []
    for step in plan.steps:
        stages.append(
            ConversationStage(
                id=step.key,
                name=step.name,
                instruction=step.intent[:STAGE_DETAIL_MAX] or step.name,
                step=step.number,
                branches=[
                    StageBranch(when=w.when[:300], target=w.to)
                    for w in step.ways_out
                    if w.to in SPECIAL_TARGETS or w.to in plan.keys
                ],
                otherwise=step.otherwise,
                collect=list(step.collect),
            )
        )
    outcomes = [
        StepOutcome(step=s.number, outcome=s.outcome)
        for s in plan.steps
        if not s.side and s.outcome.strip() and (s.owners or plan.source == "script")
    ]
    kept = base or CallScript(schema_version=2)
    return CallScript.model_validate(
        kept.model_copy(
            update={"schema_version": 2, "stages": stages, "step_outcomes": outcomes}
        ).model_dump()
    )


def with_base_ids(plan: ScriptPlan, base: CallScript | None) -> ScriptPlan:
    """`plan` with each step named like one of `base`'s stages carrying that stage's id, so a
    rewrite reads as the same steps changed rather than every step replaced."""
    if base is None or not base.stages:
        return plan
    ids = {name_key(stage.name): stage.id for stage in base.stages}
    rename = {s.key: ids[name_key(s.name)] for s in plan.steps if name_key(s.name) in ids}
    if len(set(rename.values())) != len(rename):
        return plan
    taken = set(rename.values())
    clashes = {s.key for s in plan.steps if s.key not in rename and s.key in taken}
    if clashes:
        return plan

    def moved(to: str) -> str:
        return rename.get(to, to)

    return replace(
        plan,
        steps=tuple(
            replace(
                s,
                key=moved(s.key),
                otherwise=moved(s.otherwise),
                ways_out=tuple(WayOut(w.when, moved(w.to)) for w in s.ways_out),
            )
            for s in plan.steps
        ),
    )


def stage_index(script: CallScript, key: str) -> int | None:
    return next((i for i, stage in enumerate(script.stages) if stage.id == key), None)


def steps_of(script: CallScript, keys: Sequence[str]) -> list[int]:
    return [i for k in keys if (i := stage_index(script, k)) is not None]


__all__ = [
    "BUSY_WAY_OUT",
    "EXAMPLE_LIMITS",
    "NOT_FOR_THEM_WAY_OUT",
    "ExampleLimits",
    "PlanSource",
    "PlanStep",
    "ScriptPlan",
    "WayOut",
    "outline_problems",
    "plan_from_owner",
    "plan_from_playbook",
    "plan_from_script",
    "skeleton",
    "stage_index",
    "steps_of",
    "with_base_ids",
    "with_required_ways",
]
