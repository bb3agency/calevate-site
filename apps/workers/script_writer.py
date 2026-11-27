"""THE way a holder's call script is written or changed: `write_script(request)` (DESIGN §3.3).

Every path that writes a script's words comes through here, with its context from the one
loader (`workers/script_context`): the campaign and line writer's first script, "Generate
again", Pip's asks, one-part asks and flow asks (`workers/campaign_script`), the rewrite under
the current rules and the first run's draft that rides on it, the repair of a saved script's
faulted lines (`workers/script_heal`), the step outcomes (`workers/step_outcomes`) and the
practice-test fixes (`agents/test_fixes`).

The modes:

- `whole`: build the plan (`agents/script_plan`), then write every step, the frame and the
  opening;
- `steps`: write the named steps again, keeping the rest of the script exactly as it is;
- `lines`: targeted repair of the lines at named paths, still through the step writer, only
  those fields taken from its answer;
- `outcomes`: the step outcomes' own request, through the same ladder and budget;
- `opening`: the opening line (`workers/opening_line.write_opening`).

Structure is code's, words are the model's: a step is written by its own small request
(`workers/step_writer`), the script is assembled by one applier (`laid`), checked by one
adapter (`checked`, the seam the check registry replaces), and only the steps a check names
are written again, at most `REWRITE_ROUNDS` times, told exactly what failed. What still fails
is a warning on that step, never thrown away. Every paid or refused request is returned for
the caller to meter (hard rule 7).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    MAX_SCRIPT_STAGES,
    CallScript,
    ConversationStage,
    ScriptPolicies,
    is_example_led,
)
from calevate_shared.opening_notices import OpeningNotices
from calevate_shared.spoken_guard import (
    ENGLISH_RUN,
    OWN_SCRIPT_RULE,
    english_problem,
    has_indic_letters,
    own_script_problem,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_checks, script_proposals
from apps.api.agents.owner_plan import OwnerPlan, numbered_items, owner_plan
from apps.api.agents.owner_words import owner_tasks
from apps.api.agents.retired_lines import retired_line_problem
from apps.api.agents.script_lint import instruction_fields, offers_call_back
from apps.api.agents.script_plan import (
    PlanStep,
    ScriptPlan,
    outline_problems,
    owner_notes,
    plan_from_owner,
    plan_from_playbook,
    plan_from_script,
    skeleton,
    with_base_ids,
)
from apps.api.agents.script_shape import structure_problems
from apps.api.agents.script_structure import policies_for_job, settled
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.crm import assist as crm_assist
from apps.api.tenancy.business_copy import provider_problem
from apps.workers.campaign_script_ask import (
    TASK_STEPS_FORMAT,
    TASK_STEPS_INSTRUCTION,
    TASK_STEPS_MAX_TOKENS,
    TONES,
    task_steps_request,
    task_steps_text,
)
from apps.workers.extraction import ASSIST_LADDER_LEGS
from apps.workers.opening_line import WrittenOpening, opening_problems, write_opening
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    JsonAnswer,
    LeftOut,
    ScriptBrief,
    UnusableAnswerError,
    ask_json,
    way_out_problems,
)
from apps.workers.script_context import ScriptContext
from apps.workers.step_writer import (
    Frame,
    StepAsk,
    StepWords,
    write_frame,
    write_parts,
    write_step,
)

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

Mode = Literal["whole", "steps", "lines", "outcomes", "opening"]

#: A step that fails its checks is written again at most this often (DESIGN §3.2).
REWRITE_ROUNDS: Final = 2
#: Steps written at once: parallel, without one account's model seeing a burst of twelve.
STEP_CONCURRENCY: Final = 6
#: One request's budget, at most: a step answer is short, so this is room, not a target.
REQUEST_TIMEOUT_S: Final = 50.0
#: A request starts only with this much left for it, so a job killed at the queue's
#: timeout never leaves a paid answer unmetered.
MIN_REQUEST_S: Final = 20.0
JOB_MARGIN_S: Final = 30.0

#: Anything a pass spent, paid or refused, for the caller's meter.
Spent = JsonAnswer[Any] | ProblemError


def request_timeout(started: float) -> float | None:
    """One request's budget starting now, or None when the job has too little left."""
    left = WORKER_JOB_TIMEOUT_S - JOB_MARGIN_S - (time.monotonic() - started)
    per = min(REQUEST_TIMEOUT_S, left / ASSIST_LADDER_LEGS)
    return per if per >= MIN_REQUEST_S else None


async def meter(session: AsyncSession, tenant_id: UUID, spends: Sequence[Spent]) -> None:
    """Meter every request a write spent, refusals included, under the script feature."""
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    for spent in spends:
        if isinstance(spent, ProblemError):
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=spent, feature=feature
            )
            continue
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=spent.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=spent,
            model=spent.model,
            feature=feature,
        )


@dataclass(frozen=True, slots=True)
class OutcomesAsk:
    """The step outcomes' own request (`workers/step_outcomes`): its text, instruction,
    strict format, and the parse and salvage that hold the answer to its code checks."""

    request: str
    instruction: str
    parse: Callable[[dict[str, Any]], Any]
    salvage: Callable[[dict[str, Any]], Any]
    azure_format: dict[str, object]
    max_tokens: int
    temperature: float = 0.2


@dataclass(frozen=True, slots=True)
class WriteRequest:
    mode: Mode
    context: ScriptContext
    started: float = field(default_factory=time.monotonic)
    #: The script being changed; None writes from nothing (`whole` only).
    base: CallScript | None = None
    #: `steps`: the stage ids to write again.
    step_ids: tuple[str, ...] = ()
    #: `steps`: what each step must now do, by stage id (a practice test's good answer).
    notes: Mapping[str, str] = field(default_factory=dict)
    #: `lines`: the findings ("<path>: <rule>") to clear; only lines at their paths change.
    problems: tuple[str, ...] = ()
    #: `lines`: the check the result is held to; default `checked` on the paths.
    check: Callable[[CallScript], list[str]] | None = None
    #: `whole`: plan from a model outline even when the script has a shape (the flow ask).
    outline: bool = False
    #: `steps`: only these stage fields are taken from the answer ("examples": the example
    #: turns alone, the instruction and actions kept word for word); None takes every one.
    fields: frozenset[str] | None = None
    outcomes: OutcomesAsk | None = None


@dataclass(slots=True)
class WriteResult:
    script: CallScript
    spends: list[Spent] = field(default_factory=list)
    left_out: list[LeftOut] = field(default_factory=list)
    plan: ScriptPlan | None = None
    #: How Pip read the main task's numbered list, when it did.
    task_plan: OwnerPlan | None = None
    #: `outcomes`: the answer's value.
    value: Any = None


class WriteRefusedError(Exception):
    """No step could be written: the ladder's refusal, with what was spent before it."""

    def __init__(self, refused: ProblemError, spends: list[Spent]) -> None:
        super().__init__(refused.code)
        self.refused = refused
        self.spends = spends


# --- the one check adapter ---------------------------------------------------------------


def _example_lines(script: CallScript) -> list[tuple[int, str, str]]:
    out = []
    for i, stage in enumerate(script.stages):
        for tag, ex in stage.examples.items():
            base = f"stages.{i}.examples.{tag}"
            out += [(i, f"{base}.turns.{j}", t) for j, t in enumerate(ex.turns)]
            out += [
                (i, f"{base}.{name}", text)
                for name in ("confused", "stuck", "busy")
                if (text := getattr(ex, name))
            ]
    return out


#: How a person may reach the business, as an English line names it. A line in a call
#: language's own letters is not read here: its words belong in the registry's
#: `call_words.json` (`agents/script_checks`).
_CHANNELS: Final[dict[str, re.Pattern[str]]] = {
    "call": re.compile(r"\bcall(?:ing)?\b|\bphone\b|\bring\b", re.I),
    "message": re.compile(r"\bmessages?\b|\bwhats\s?app\b|\bsms\b|\btext(?:s|ing)?\b", re.I),
    "email": re.compile(r"\be-?mails?\b", re.I),
}


def _channel_problems(script: CallScript) -> list[str]:
    """An example turn that tells the person to reach the business by a way its step does not
    name: the Rytu Khata close of 26 Nov 2026 said "message us" where the owner wrote "call
    us with any doubt"."""
    found: list[str] = []
    for i, path, text in _example_lines(script):
        named = {
            c for c, pattern in _CHANNELS.items() if pattern.search(script.stages[i].instruction)
        }
        said = {c for c, pattern in _CHANNELS.items() if pattern.search(text)}
        if named and said - named:
            found.append(
                f"{path}: names a way to reach the business ({', '.join(sorted(said - named))}) "
                f"the step does not; say only {', '.join(sorted(named))}."
            )
    return found


def _help_call_back_problems(script: CallScript) -> list[str]:
    """A confused or stuck line that offers a call back. Those lines are the help the agent
    gives while it can still help; a call back is the step's last way out, after every way
    was tried (founder, 25 Nov 2026, `owner_plan.last_resort_condition`), and the Rytu Khata
    draft of 27 Nov 2026 offered one as the stuck hint."""
    found = []
    for i, stage in enumerate(script.stages):
        for tag, ex in stage.examples.items():
            for name in ("confused", "stuck"):
                if offers_call_back(getattr(ex, name)):
                    found.append(
                        f"stages.{i}.examples.{tag}.{name}: offers a call back; give one smaller "
                        "hint for the same action instead, since a call back comes only after "
                        "every way was tried."
                    )
    return found


#: A name of two or more capitalised Latin words ("Add Farm", "Home Screen"): how a screen
#: or button is written in a step's English instruction and actions. One word alone is too
#: often an ordinary sentence opener to be read as a name.
_NAME: Final = re.compile(r"\b[A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*)+")
_SENTENCE_START: Final = re.compile(r"(?:^|[.!?:;]\s+)$")


def _names(text: str) -> set[str]:
    """The screen and button names in `text`, a sentence's opening verb left off ("Tap Add
    Farm" names "Add Farm")."""
    out = set()
    for found in _NAME.finditer(text):
        name = found.group()
        if _SENTENCE_START.search(text[: found.start()]):
            name = name.partition(" ")[2]
        if " " in name.strip():
            out.add(name.strip().casefold())
    return out


def _stage_text(stage: ConversationStage) -> str:
    return " ".join(
        (stage.name, stage.instruction, *(f"{p.action}. {p.wait_for}" for p in stage.procedure))
    )


def _other_step_name_problems(script: CallScript, context: ScriptContext) -> list[str]:
    """An example line naming a screen or button that belongs to one other step: the Rytu
    Khata draft of 27 Nov 2026 had its expense step say "Please tap Add Farm.", the farm
    step's button. A name is a step's when exactly one step's instruction or actions name
    it; the business's and agent's names belong to every step."""
    texts = [_stage_text(s).casefold() for s in script.stages]
    shared = f"{context.brief.business_name} {context.brief.agent_name}".casefold()
    owner: dict[str, int] = {}
    for i, stage in enumerate(script.stages):
        for name in _names(f"{stage.instruction}. " + ". ".join(p.action for p in stage.procedure)):
            holders = [j for j, t in enumerate(texts) if re.search(rf"\b{re.escape(name)}\b", t)]
            if holders == [i] and name not in shared:
                owner[name] = i
    found = []
    for i, path, line in _example_lines(script):
        said = line.casefold()
        for name, j in owner.items():
            if j != i and re.search(rf"\b{re.escape(name)}\b", said):
                found.append(
                    f'{path}: names "{name}", which is step "{script.stages[j].name}"\'s; '
                    "keep each line to this step's own action."
                )
    return found


def example_problems(script: CallScript, context: ScriptContext) -> list[str]:
    """What the check registry does not read on the example turns: a provider's name (D-679)
    and a retired stock line, a way to reach the business or a call back the step does not
    give, another step's screen or button, and a guide step with no example turns in a call
    language."""
    owners = context.owners_words
    found = [
        p
        for _i, path, text in _example_lines(script)
        for p in (provider_problem(path, text, allowed=owners), retired_line_problem(path, text))
        if p
    ]
    found += _channel_problems(script)
    found += _help_call_back_problems(script)
    found += _other_step_name_problems(script, context)
    for i, stage in enumerate(script.stages):
        if stage.mode != "guide":
            continue
        missing = [
            tag
            for tag in context.languages
            if not (tag in stage.examples and stage.examples[tag].turns)
        ]
        if missing and not stage.sounds_like.strip():
            found.append(f"stages.{i}.examples: no example turns in {', '.join(missing)}.")
    return found


def checked(
    script: CallScript, context: ScriptContext, *, before: CallScript | None = None
) -> list[str]:
    """What a written script's steps are rewritten for, as "<path>: <rule>" findings: the one
    check registry's repairable findings (`script_checks.writer_findings`, with the holder's
    lint context and the owner's plan), an instruction written in a call language's letters,
    the ways out every placed call needs, and the example turns' own (`example_problems`).
    With `before` (a change), a finding the script already had is the owner's, not the
    writer's. What no step rewrite can mend is warned by `_off_step_warnings`."""
    registry = script_checks.CheckContext(lint=context.lint(), plan=context.owner_plan)
    found = [
        *script_checks.writer_findings(script, registry),
        *(
            problem
            for path, text in instruction_fields(script)
            if (problem := english_problem(path, text))
        ),
        *(way_out_problems(script) if context.placed else ()),
        *example_problems(script, context),
    ]
    found = list(dict.fromkeys(found))
    if before is None:
        return found
    had = {_where(p, before) for p in checked(before, context)}
    return [p for p in found if _where(p, script) not in had]


def _where(problem: str, script: CallScript) -> tuple[str, str]:
    """A finding by its place (a step by id) and what it says, so the same finding on the
    same line is recognised across two versions of a script."""
    return script_proposals.finding_key(problem, script), problem.partition(": ")[2]


def _field_of(problem: str) -> str | None:
    """The stage field a finding's path names (`stages.3.procedure.1.action`: procedure)."""
    parts = problem.partition(": ")[0].split(".")
    return parts[2] if len(parts) > 2 else None


def by_step(problems: Sequence[str], script: CallScript) -> dict[str, list[str]]:
    """Findings by the stage id they are on; a finding on no stage is left out."""
    out: dict[str, list[str]] = {}
    for problem in problems:
        path = problem.partition(": ")[0].split(".")
        if path[0] == "stages" and len(path) > 1 and path[1].isdigit():
            index = int(path[1])
            if index < len(script.stages):
                out.setdefault(script.stages[index].id, []).append(problem)
    return out


# --- the one applier ---------------------------------------------------------------------

#: The fields of a stage the step writer's answer fills, by the path part that names them.
_WORD_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "instruction": ("instruction",),
    "procedure": ("procedure",),
    "examples": ("examples", "sounds_like", "scripts"),
    "sounds_like": ("examples", "sounds_like", "scripts"),
    "scripts": ("examples", "sounds_like", "scripts"),
    "qa": ("qa",),
}


def stage_with(
    stage: ConversationStage, words: StepWords, *, only: frozenset[str] | None = None
) -> ConversationStage:
    """`stage` with `words` laid on it: everything when `only` is None, else only the
    fields `only` names (`_WORD_FIELDS`). The legacy `sounds_like` and `scripts` lines go
    once examples replace them, so the in-call model is never shown both."""
    update: dict[str, Any] = {
        "instruction": words.instruction,
        "procedure": list(words.procedure),
        "examples": words.examples,
        "sounds_like": "",
        "scripts": {},
        "qa": list(words.qa),
    }
    if only is not None:
        allowed = {name for part in only for name in _WORD_FIELDS.get(part, ())}
        update = {k: v for k, v in update.items() if k in allowed}
    if "examples" in update and not words.examples:
        # An answer with no examples never wipes the lines a step already had.
        for name in ("examples", "sounds_like", "scripts"):
            update.pop(name, None)
    return _fitted({**stage.model_dump(), **update})


def _fitted(data: dict[str, Any]) -> ConversationStage:
    """The stage, its instruction cut at a word boundary when it and the pointers the
    compiler adds (`call_script.examples_pointer`, the scenario pointer) would not fit the
    engine's step detail (`STAGE_DETAIL_MAX`, ThinnestAI's 600 characters)."""
    instruction = str(data["instruction"])
    while True:
        try:
            return ConversationStage.model_validate({**data, "instruction": instruction})
        except ValueError:
            words = instruction.split()
            if len(words) <= 3:
                raise
            instruction = " ".join(words[: max(3, len(words) - 8)]).rstrip(",;:") + "."


def laid(
    script: CallScript,
    words: Mapping[str, StepWords],
    *,
    only: Mapping[str, frozenset[str]] | None = None,
) -> CallScript:
    """`script` with each stage whose id `words` holds rewritten by `stage_with`, nothing
    else changed. The one applier: whole scripts, rewritten steps and line repairs alike."""
    stages = [
        stage_with(stage, words[stage.id], only=(only or {}).get(stage.id))
        if stage.id in words
        else stage
        for stage in script.stages
    ]
    return CallScript.model_validate(script.model_copy(update={"stages": stages}).model_dump())


def _at_path(data: Any, path: str, value: str) -> bool:
    *parents, last = path.split(".")
    node = data
    for part in parents:
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    key: Any = int(last) if last.isdigit() else last
    if isinstance(node, dict) and isinstance(node.get(key), str):
        node[key] = value
        return True
    if (
        isinstance(node, list)
        and isinstance(key, int)
        and key < len(node)
        and isinstance(node[key], str)
    ):
        node[key] = value
        return True
    return False


def with_parts(script: CallScript, parts: Mapping[str, str]) -> CallScript:
    """`script` with each string at a path in `parts` replaced; a path to anything but a
    string, or one that would not validate, is left as it was."""
    out = script
    for path, value in parts.items():
        data = out.model_dump(mode="json")
        if not _at_path(data, path, value):
            continue
        try:
            out = CallScript.model_validate(data)
        except ValueError:
            log.info("script_part_not_applied", extra={"path": path.split(".")[0]})
    return out


# --- plans -------------------------------------------------------------------------------

OUTLINE_INSTRUCTION: Final = (
    "You plan the steps of a phone call by an AI voice agent: the order the call goes in "
    "after its opening line. The opening line has already greeted the person, said who is "
    "calling and why, and asked whether now is a good time, so the first step starts from "
    "their answer. Return one entry per step, in call order, at most 10: `name` is 1 to 4 "
    "plain words; `does` says in one or two plain English sentences what the agent does in "
    "it; `outcome` is one sentence saying what is true once it is done, checkable from what "
    "the person says; `ways_out` only where the person may say something that sends the call "
    'elsewhere: `when` in a few words and `to` another step\'s name, "end" or "call_back" '
    "(a call back only for someone who still cannot after being guided step by step). A call "
    "back, an end or a transfer is never a step of its own. Each separate thing the call asks "
    "the person to do is its own step, in the order the call gives them, and no step does two "
    "of them; `tasks` lists the number of the owner's task a step does, at most one, or [] "
    "for a step that does none. The last step closes the call on the one next thing: it "
    "never asks them to confirm that everything is done and never says that it is, since "
    "only what they said on the call shows that. Return ONLY JSON."
)

#: The outline's answer: the task-steps shape, each step also naming the owner's task it
#: does, so code can hold the outline to one step per task in the owner's order.
OUTLINE_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "call_outline",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "does": {"type": "string"},
                            "outcome": {"type": "string"},
                            "ways_out": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "when": {"type": "string"},
                                        "to": {"type": "string"},
                                    },
                                    "required": ["when", "to"],
                                    "additionalProperties": False,
                                },
                            },
                            "tasks": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["name", "does", "outcome", "ways_out", "tasks"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
}

#: A close that has the agent declare or ask that the whole job is done: the 27 Nov 2026
#: founder call heard "all done" with steps left, and the 28 Nov first run planned "Confirm
#: all steps are done" as its last step.
_ALL_DONE: Final = re.compile(
    r"\b(?:all|every|each)\b[^.]{0,40}\b(?:steps?|tasks?|entries|things)\b[^.]{0,40}"
    r"\b(?:done|completed?|finished|saved)\b"
    r"|\bconfirm\b[^.]{0,30}\b(?:all|everything)\b"
    r"|\beverything\b[^.]{0,20}\b(?:is|was|has been)\s+(?:done|completed?|finished|set)\b",
    re.IGNORECASE,
)


def outline_task_problems(raw: dict[str, Any], tasks: Sequence[str]) -> list[str]:
    """What an outline answer gets wrong of the owner's tasks (`owner_words.owner_tasks`):
    a step doing two, a task with no step, one in two steps or out of order; and a close
    that declares or asks that everything is done. Sent back as the repair's problems."""
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        return []
    problems: list[str] = []
    placed: list[int] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        done = [n for n in step.get("tasks") or [] if isinstance(n, int) and 1 <= n <= len(tasks)]
        if len(done) > 1:
            listed = " and ".join(f'{n} ("{tasks[n - 1]}")' for n in done)
            problems.append(f"steps.{index}: does tasks {listed}; give each its own step")
        placed += done
    for number, task in enumerate(tasks, 1):
        count = placed.count(number)
        if count == 0:
            problems.append(f'task {number} ("{task}") has no step; add one in its place')
        elif count > 1:
            problems.append(f'task {number} ("{task}") is in {count} steps; keep it in one')
    if placed != sorted(placed):
        problems.append("the steps do the owner's tasks out of their order; keep the order")
    last = steps[-1]
    if isinstance(last, dict) and _ALL_DONE.search(
        f"{last.get('name', '')} {last.get('does', '')}"
    ):
        problems.append(
            f"steps.{len(steps) - 1}: has them confirm, or says, that everything is done; "
            "close by thanking them and saying the one next thing"
        )
    return problems


def outline_request(
    context: ScriptContext,
    base: CallScript | None,
    hint: ScriptPlan,
    tasks: Sequence[str] = (),
) -> str:
    lines = [f"What the call is for:\n{context.main_task.strip()}"]
    if tasks:
        lines.append(
            "The owner's tasks for the person, in their order (each its own step):\n"
            + "\n".join(f"{n}. {task}" for n, task in enumerate(tasks, 1))
        )
    if context.instruction.strip():
        lines.append(f"The owner asks: {' '.join(context.instruction.split())}")
    if base is not None and base.stages:
        lines.append(
            "The steps the script has now:\n"
            + "\n".join(f"- {s.name}: {s.instruction}" for s in base.stages)
        )
    elif hint.steps:
        lines.append(
            "A usual plan for this kind of call, to adapt to what the call is for:\n"
            + "\n".join(f"- {s.name}: {s.intent}" for s in hint.steps)
        )
    if context.situation.strip():
        lines.append(context.situation.strip())
    return "\n\n".join(lines)


async def _read_plan(
    context: ScriptContext,
    request: str,
    instruction: str,
    started: float,
    *,
    expect: int | None,
    tasks: Sequence[str] | None = None,
) -> tuple[OwnerPlan | None, Spent | None]:
    """A plan the model laid out in the task-steps shape, read like an owner's own; None
    when the answer does not hold one (`expect`: the steps it must keep, one per item).
    `tasks`: an outline, held to the owner's tasks and a close that claims nothing
    (`outline_task_problems`), repaired once and otherwise taken as it came."""
    timeout_s = request_timeout(started)
    if timeout_s is None:
        return None, None
    try:
        answer = await _ask_steps(context, request, instruction, timeout_s, tasks=tasks)
    except ProblemError as refused:
        log.info("script_plan_refused", extra={"reason": refused.code})
        return None, refused
    except Exception:
        # The plan falls back to the next source; a failed reading never stops the script.
        log.exception("script_plan_crashed", extra={"kind": context.kind})
        return None, None
    plan = owner_plan(answer.value)
    steps = sum(s.number is not None for s in plan.steps) if plan is not None else 0
    if plan is None or (expect is not None and steps != expect):
        return None, answer
    return plan, answer


async def _ask_steps(
    context: ScriptContext,
    request: str,
    instruction: str,
    timeout_s: float,
    *,
    tasks: Sequence[str] | None = None,
) -> JsonAnswer[str]:
    if tasks is None:
        return await ask_json(
            request,
            instruction,
            parse=task_steps_text,
            azure_format=TASK_STEPS_FORMAT,
            tenant_leg=context.tenant_leg,
            quota_exhausted=context.quota_exhausted,
            max_tokens=TASK_STEPS_MAX_TOKENS,
            temperature=0.2,
            timeout_s=timeout_s,
        )
    owners = tuple(tasks)

    def parse(raw: dict[str, Any]) -> str | None:
        problems = outline_task_problems(raw, owners)
        if problems:
            raise UnusableAnswerError("; ".join(problems))
        return task_steps_text(raw)

    # The salvage takes an outline the repair could not fix as it came: a bundled step is
    # still a better plan for this business than the trade's playbook it would fall back to.
    return await ask_json(
        request,
        instruction,
        parse=parse,
        salvage=task_steps_text,
        azure_format=OUTLINE_FORMAT,
        tenant_leg=context.tenant_leg,
        quota_exhausted=context.quota_exhausted,
        max_tokens=TASK_STEPS_MAX_TOKENS,
        temperature=0.2,
        timeout_s=timeout_s,
    )


async def plan_for(
    context: ScriptContext, base: CallScript | None, started: float, *, outline: bool = False
) -> tuple[ScriptPlan, list[Spent], OwnerPlan | None]:
    """The plan a whole script is written to, the requests it spent, and how the main task's
    list was read when it was: the owner's steps (request, then main task), the main task's
    numbered list read as steps, the script's own shape, a checked model outline, the
    playbook."""
    placed = context.placed
    spends: list[Spent] = []
    brief = context.brief
    owners = context.owner_plan
    if owners is not None and not outline:
        return with_base_ids(plan_from_owner(owners, placed=placed), base), spends, None
    if base is None and not outline and (items := numbered_items(context.main_task)):
        read, spent = await _read_plan(
            context,
            task_steps_request(context.main_task, items),
            TASK_STEPS_INSTRUCTION,
            started,
            expect=len(items),
        )
        spends += [spent] if spent is not None else []
        if read is not None:
            return plan_from_owner(read, source="task", placed=placed), spends, read
    if base is not None and base.stages and not outline and not context.instruction.strip():
        return plan_from_script(base), spends, None
    playbook = plan_from_playbook(
        brief.business_type, placed=placed, plans=dict(brief.step_plans), fit=brief.fit
    )
    if context.main_task.strip() or context.instruction.strip():
        tasks = owner_tasks(context.main_task)
        # Past the step limit (with a first and a last step around them) they cannot each
        # have a step; the outline then plans them as it judges.
        if len(tasks) > MAX_SCRIPT_STAGES - 2:
            tasks = []
        read, spent = await _read_plan(
            context,
            outline_request(context, base, playbook, tasks),
            OUTLINE_INSTRUCTION,
            started,
            expect=None,
            tasks=tasks,
        )
        spends += [spent] if spent is not None else []
        if read is not None:
            proposed = with_base_ids(plan_from_owner(read, source="outline", placed=placed), base)
            problems = outline_problems(proposed)
            if not problems:
                return proposed, spends, None
            log.info("script_outline_refused", extra={"problems": len(problems)})
    if base is not None and base.stages:
        return plan_from_script(base), spends, None
    return playbook, spends, None


# --- writing the steps -------------------------------------------------------------------


@dataclass(slots=True)
class _Steps:
    words: dict[str, StepWords] = field(default_factory=dict)
    spends: list[Spent] = field(default_factory=list)
    refused: ProblemError | None = None


def _ask(
    context: ScriptContext,
    plan: ScriptPlan,
    step: PlanStep,
    script: CallScript,
    *,
    problems: Sequence[str] = (),
    note: str = "",
) -> StepAsk:
    stage = next((s for s in script.stages if s.id == step.key), None)
    current = ""
    if stage is not None and (problems or note):
        current = json.dumps(
            stage.model_dump(
                mode="json",
                include={"instruction", "procedure", "examples", "sounds_like", "scripts", "qa"},
            ),
            ensure_ascii=False,
        )
    # A request that lays out the steps reaches each step as its plan entry; only what the
    # owner said around the steps (tone, "Rules: ...") is the owner's ask for every step.
    asked = owner_notes(context.instruction) if context.replans else context.instruction
    instruction = " ".join(p for p in (asked, note) if p.strip())
    return StepAsk(
        brief=context.written_brief(),
        plan=plan,
        step=step,
        languages=context.languages,
        opening=spoken_opening(context, script),
        main_task=context.main_task,
        sources=context.grounding,
        instruction=instruction,
        tone=TONES.get(context.tone or "", ""),
        current=current,
        problems=tuple(problems),
    )


def owners_words_kept(plan: ScriptPlan, key: str, words: StepWords) -> StepWords:
    """`words` with the instruction of a step the owner laid out kept as the owner wrote it
    (`script_plan.owners_text`): the model writes the actions and the example turns around
    it and never rewords it. A model asked to keep the owner's detail paraphrased it away
    (Rytu Khata, 26 Nov 2026: "open the website and add the app" for the owner's Android and
    iPhone paths). Cut to the step detail's room by `stage_with`."""
    step = plan.step(key)
    if plan.source != "owner" or step is None or not step.owners or not step.intent.strip():
        return words
    return replace(words, instruction=" ".join(step.intent.split()))


async def _written(
    context: ScriptContext,
    plan: ScriptPlan,
    script: CallScript,
    keys: Sequence[str],
    started: float,
    *,
    problems: Mapping[str, Sequence[str]] | None = None,
    notes: Mapping[str, str] | None = None,
) -> _Steps:
    """The steps `keys` written in parallel, each by its own request."""
    out = _Steps()
    gate = asyncio.Semaphore(STEP_CONCURRENCY)

    async def one(step: PlanStep) -> tuple[str, JsonAnswer[StepWords] | ProblemError | None]:
        async with gate:
            timeout_s = request_timeout(started)
            if timeout_s is None:
                return step.key, None
            try:
                answer = await write_step(
                    _ask(
                        context,
                        plan,
                        step,
                        script,
                        problems=(problems or {}).get(step.key, ()),
                        note=(notes or {}).get(step.key, ""),
                    ),
                    tenant_leg=context.tenant_leg,
                    quota_exhausted=context.quota_exhausted,
                    timeout_s=timeout_s,
                    allowed=context.owners_words,
                )
            except ProblemError as refused:
                return step.key, refused
            return step.key, answer

    steps = [s for k in keys if (s := plan.step(k)) is not None]
    for key, result in await asyncio.gather(*(one(s) for s in steps)):
        if result is None:
            continue
        out.spends.append(result)
        if isinstance(result, ProblemError):
            log.info("script_step_refused", extra={"reason": result.code})
            out.refused = out.refused or result
            continue
        out.words[key] = owners_words_kept(plan, key, result.value)
    return out


@dataclass(slots=True)
class _Checked:
    script: CallScript
    spends: list[Spent]
    left: list[str]


async def _rounds(
    context: ScriptContext,
    plan: ScriptPlan,
    script: CallScript,
    targets: Sequence[str],
    started: float,
    *,
    check: Callable[[CallScript], list[str]],
    only: Mapping[str, frozenset[str]] | None = None,
) -> _Checked:
    """Each target step checked, and a failing one written again alone with its exact
    problems, at most `REWRITE_ROUNDS` times; the findings still there are returned."""
    spends: list[Spent] = []
    left = [p for p in check(script) if by_step([p], script).keys() & set(targets)]
    for _round in range(REWRITE_ROUNDS):
        failing = by_step(left, script)
        keys = [k for k in targets if k in failing]
        if not keys or request_timeout(started) is None:
            break
        again = await _written(context, plan, script, keys, started, problems=failing)
        spends += again.spends
        if not again.words:
            break
        rewritten = laid(script, again.words, only=only)
        if rewritten == script:
            break
        script = rewritten
        left = [p for p in check(script) if by_step([p], script).keys() & set(targets)]
    log.info("script_steps_checked", extra={"steps": len(targets), "left": len(left)})
    return _Checked(script, spends, left)


# --- the opening -------------------------------------------------------------------------

_OPENINGS: Final = (("opening_line", False), ("outbound_opening_line", True))


def openings_kept(
    script: CallScript, base: CallScript | None, *, fields: Sequence[str] | None = None
) -> CallScript:
    """`script` with any opening line it lacks put back from `base`: a blank opening is
    never a fix, the agent would open the call with nothing. `fields`: only these openings
    (the ones the holder speaks, `_opening_fields`); None is both."""
    if base is None:
        return script
    names = [name for name, _placed in _OPENINGS if fields is None or name in fields]
    restored = {
        name: kept
        for name in names
        if not str(getattr(script, name)).strip() and (kept := str(getattr(base, name)).strip())
    }
    return script.model_copy(update=restored) if restored else script


def spoken_opening(context: ScriptContext, script: CallScript) -> str:
    """The first words the holder's calls actually open with: a "both" agent's placed-call
    line on a campaign, else `opening_line`. An agent of one direction never speaks
    `outbound_opening_line` (`engine.compose_placed_call_first_words`), so a stale one must
    not reach the steps' context."""
    if context.brief.direction == "both" and context.placed:
        return script.outbound_opening_line or script.opening_line
    return script.opening_line


def with_opening(script: CallScript, written: WrittenOpening, *, placed: bool) -> CallScript:
    """`script` with `written` as its opening (`placed`: the one for calls it places) and
    the words in it that say each notice kept beside it (D-971)."""
    name, notices = (
        ("outbound_opening_line", "outbound_opening_notices")
        if placed
        else ("opening_line", "opening_notices")
    )
    return script.model_copy(update={name: written.line, notices: written.notices()})


def _opening_fields(context: ScriptContext) -> tuple[tuple[str, bool], ...]:
    """The openings this holder's script has: a "both" agent's line also opens the calls it
    places; every other script has one."""
    return _OPENINGS if context.brief.direction == "both" else (_OPENINGS[0],)


async def _opening(
    context: ScriptContext,
    script: CallScript,
    base: CallScript | None,
    started: float,
    *,
    force: bool = False,
) -> tuple[CallScript, list[Spent]]:
    """Each opening line written where it is empty (or `force`), and repaired where Pip's
    breaks the opening rule; a line the owner had or wrote word for word is theirs."""
    script = openings_kept(script, base, fields=[name for name, _ in _opening_fields(context)])
    brief = replace(context.written_brief(), description=context.main_task)
    dialled_all = brief.direction == "outbound"
    spends: list[Spent] = []
    for name, placed in _opening_fields(context):
        line = str(getattr(script, name)).strip()
        # A line carried over from a script Pip still owns is Pip's own earlier draft, so it
        # is checked and repaired like a new one; kept unchecked, a broken opening survived
        # every regeneration (26 Nov 2026: romanised Telugu with an English sentence).
        carried = base is not None and line == str(getattr(base, name)).strip()
        owners = carried and not context.pip_owned
        if line and (owners or line in context.owners_words) and not force:
            continue
        dialled = placed or dialled_all
        problems = (
            opening_problems(
                line,
                brief.language,
                names=(brief.business_name, brief.agent_name),
                introduced=brief.introduced,
                woven=brief.woven,
                placed=dialled,
                agent_name=brief.agent_name,
                business_name=brief.business_name,
            )
            if line and not force
            else []
        )
        if line and not problems and not force:
            continue
        written, spent = await _opening_written(
            context,
            brief,
            name,
            line,
            asked=("" if force else line, problems),
            placed=placed,
            dialled=dialled,
            started=started,
        )
        spends += spent
        if written is not None:
            script = with_opening(script, written, placed=placed)
    return script, spends


#: Ladders the opening writer may run for an opening that would otherwise stay EMPTY. A
#: campaign call speaks only its opening line, so an empty one is a call that opens with
#: nothing (28 Nov 2026 first run: "No opening line yet"); a line already there is kept
#: instead, so it gets one.
EMPTY_OPENING_ATTEMPTS: Final = 2


async def _opening_written(
    context: ScriptContext,
    brief: ScriptBrief,
    name: str,
    line: str,
    *,
    asked: tuple[str, Sequence[str]],
    placed: bool,
    dialled: bool,
    started: float,
) -> tuple[WrittenOpening | None, list[Spent]]:
    """The opening `write_opening` writes for field `name`, or None to keep `line`. Where
    `line` is empty a refusal, or an answer that leaves the call's language, is asked once
    more while there is time: the second time with the refused line and its problem, so
    the repair is told what was wrong rather than sampled again."""
    names = (brief.business_name, brief.agent_name)
    ask_line, ask_problems = asked
    spends: list[Spent] = []
    for _attempt in range(1 if line else EMPTY_OPENING_ATTEMPTS):
        if request_timeout(started) is None:
            break
        try:
            answer = await write_opening(
                brief,
                line=ask_line,
                problems=ask_problems,
                tenant_leg=context.tenant_leg,
                quota_exhausted=context.quota_exhausted,
                placed=placed,
                placed_rules=dialled,
            )
        except ProblemError as refused:
            log.info("script_opening_unwritten", extra={"reason": refused.code, "field": name})
            spends.append(refused)
            continue
        spends.append(answer)
        if keeps_language(line, answer.value.line, brief.language, names=names):
            return answer.value, spends
        log.info("script_opening_kept", extra={"field": name, "reason": "language"})
        ask_line = answer.value.line
        ask_problems = [
            own_script_problem(name, ask_line, brief.language, names=names)
            or f"{name}: write it {OWN_SCRIPT_RULE}"
        ]
    return None, spends


def keeps_language(old: str, new: str, language: str, *, names: Sequence[str] = ()) -> bool:
    """Whether an opening rewritten for a call in `language` stays in it: in an Indian
    language it keeps the language's own letters where the old line had them, and holds no
    English sentence (production, 26 Nov 2026: a Telugu opening came back as romanised
    Telugu with "We are calling to help you install and start using the app.").

    `names` (the business's and the agent's) are taken out first, as `own_script_problem`
    takes them out: a placed call's opening must say both, and "Anjali, Rytu Khata app" is
    four English-letter words in a row that are no English sentence. Without this the line
    the writer's own check passed was thrown away here and the opening stayed empty."""
    if language.split("-")[0].lower() == "en":
        return True
    plain = re.sub(r"\{\{[^}]*\}\}", " ", new)
    for each in names:
        if each.strip():
            plain = plain.replace(each.strip(), " ")
    if ENGLISH_RUN.search(plain):
        return False
    return not (has_indic_letters(old) and not has_indic_letters(new))


# --- the modes ---------------------------------------------------------------------------


def _policies(context: ScriptContext, script: CallScript, base: CallScript | None) -> CallScript:
    """What the job cannot back switched off, while the policies are not the owner's."""
    if base is not None and base.policies != ScriptPolicies():
        return script
    policies = policies_for_job(
        script.policies,
        sources=" ".join((context.grounding, *context.brief.facts)),
        manifest=context.brief.capabilities,
    )
    return (
        script if policies == script.policies else script.model_copy(update={"policies": policies})
    )


def _warnings(problems: Sequence[str], script: CallScript) -> list[LeftOut]:
    """One warning per part and rule, for the owner to read."""
    return list({(p.part, p.rule): p for p in script_proposals.fix_left(problems, script)}.values())


def _unspoken_cleared(context: ScriptContext, script: CallScript) -> CallScript:
    """A whole rewrite's starting point without what the call no longer says: the placed-call
    opening of an agent that never speaks it, and, while the script is still Pip's own, its
    old example call, which the steps' own examples replace (26 Nov 2026: a stale example
    and a WhatsApp ending outlived every regeneration; the frame is written again for the
    same reason)."""
    update: dict[str, Any] = {}
    if context.brief.direction != "both":
        update |= {"outbound_opening_line": "", "outbound_opening_notices": OpeningNotices()}
    if context.pip_owned:
        update["example_exchange"] = []
    return script.model_copy(update=update) if update else script


def _unread_cleared(script: CallScript) -> CallScript:
    """A rewritten script without the whole example call once its steps carry examples: the
    compiler then never reads it (`call_script.is_example_led`), so it would only sit in the
    editor as words the calls do not say, and in the text every check reads. Cleared whoever
    wrote it, unlike the frame: an owner's example call is not theirs to keep when no call
    hears it. The steps' legacy `sounds_like` and `scripts` lines go in `stage_with`."""
    if not script.example_exchange or not is_example_led(script):
        return script
    return script.model_copy(update={"example_exchange": []})


async def _whole(request: WriteRequest) -> WriteResult:
    context, base, started = request.context, request.base, request.started
    plan, spends, read = await plan_for(context, base, started, outline=request.outline)
    script = _unspoken_cleared(context, skeleton(plan, base))
    script, opened = await _opening(context, script, base, started)
    spends += opened
    keys = list(plan.keys)
    frame_task = (
        asyncio.create_task(
            write_frame(
                context.written_brief(),
                plan,
                main_task=context.main_task,
                sources=context.grounding,
                tenant_leg=context.tenant_leg,
                quota_exhausted=context.quota_exhausted,
                timeout_s=request_timeout(started) or MIN_REQUEST_S,
            )
        )
        if base is None or context.pip_owned or not (base.identity or base.goal)
        else None
    )
    first = await _written(context, plan, script, keys, started)
    spends += first.spends
    frame: Frame | None = None
    if frame_task is not None:
        try:
            answer = await frame_task
            spends.append(answer)
            frame = answer.value
        except ProblemError as refused:
            spends.append(refused)
    if not first.words:
        raise WriteRefusedError(first.refused or _nothing_written(), spends)
    script = _unread_cleared(laid(script, first.words))
    if frame is not None:
        script = CallScript.model_validate(script.model_copy(update=frame.fields()).model_dump())
    script = _settled(context, script, base=None)
    done = await _rounds(context, plan, script, keys, started, check=lambda s: checked(s, context))
    script = _policies(context, done.script, base)
    left = [*_warnings(done.left, script), *_off_step_warnings(context, script)]
    return WriteResult(script, [*spends, *done.spends], left, plan, read)


def _settled(context: ScriptContext, script: CallScript, *, base: CallScript | None) -> CallScript:
    """The structure mends code makes (`script_structure.settled`) and the owner's names and
    outcomes pinned (`owner_plan.with_owner_plan`)."""
    from apps.api.agents.owner_plan import with_owner_plan

    return with_owner_plan(settled(script, context.lint(), base=base), context.owner_plan)


def _off_step_warnings(context: ScriptContext, script: CallScript) -> list[LeftOut]:
    """Findings on no step (the goal, a quick fact, the script as a whole) as warnings."""
    registry = script_checks.CheckContext(lint=context.lint(), plan=context.owner_plan)
    found = [
        *script_checks.texts(script_checks.run(script, registry)),
        *structure_problems(
            script,
            # The main task's items are not read where the owner laid out the steps.
            main_task="" if context.owner_plan is not None else context.main_task,
            call_back=registry.lint.call_back,
        ),
    ]
    return _warnings([p for p in dict.fromkeys(found) if not by_step([p], script)], script)


def _nothing_written() -> ProblemError:

    return ProblemError.business_rule(
        ANSWER_UNUSABLE_CODE,
        "AI help could not write this script cleanly this time.",
        remediation="Try again, or add a note saying what the calls should say.",
    )


async def _steps(request: WriteRequest) -> WriteResult:
    """The named steps written again; every other part of the script exactly as it was."""
    context, started = request.context, request.started
    base = request.base or CallScript(schema_version=2)
    plan = plan_from_script(base)
    keys = [k for k in request.step_ids if plan.step(k) is not None]
    first = await _written(context, plan, base, keys, started, notes=request.notes)
    if not first.words:
        raise WriteRefusedError(first.refused or _nothing_written(), first.spends)
    only = dict.fromkeys(keys, request.fields) if request.fields is not None else None
    script = laid(base, first.words, only=only)

    def check(s: CallScript) -> list[str]:
        return checked(s, context, before=base)

    done = await _rounds(context, plan, script, keys, started, check=check, only=only)
    return WriteResult(
        done.script, [*first.spends, *done.spends], _warnings(done.left, done.script), plan
    )


async def _lines(request: WriteRequest) -> WriteResult:
    """The lines at the findings' paths repaired: a step's through the step writer, with
    only the fields the paths name taken from the answer; any other line by one small parts
    request. Held to `request.check` when given."""
    context, started = request.context, request.started
    base = request.base or CallScript(schema_version=2)
    plan = plan_from_script(base)
    on_steps = by_step(request.problems, base)
    only: dict[str, frozenset[str]] = {
        key: frozenset(f for p in found if (f := _field_of(p)) is not None)
        or frozenset({"instruction"})
        for key, found in on_steps.items()
    }
    spends: list[Spent] = []
    script = base
    if on_steps:
        first = await _written(context, plan, base, list(on_steps), started, problems=on_steps)
        spends += first.spends
        if not first.words and first.refused is not None:
            # No faulted step could be written: the refusal, its spends to be metered.
            raise WriteRefusedError(first.refused, spends)
        script = laid(base, first.words, only=only)
    off = [p for p in request.problems if not by_step([p], base)]
    lines = [
        (path, said, [p.partition(": ")[2] for p in off if p.partition(": ")[0] == path])
        for path in dict.fromkeys(p.partition(": ")[0] for p in off)
        if (said := _string_at(base, path)) is not None
    ]
    if lines and (timeout_s := request_timeout(started)) is not None:
        try:
            answer = await write_parts(
                lines,
                language=context.language,
                tenant_leg=context.tenant_leg,
                quota_exhausted=context.quota_exhausted,
                timeout_s=timeout_s,
            )
            spends.append(answer)
            script = with_parts(script, answer.value)
        except ProblemError as refused:
            spends.append(refused)
    keys = frozenset(script_proposals.finding_key(p, base) for p in request.problems)

    def check(s: CallScript) -> list[str]:
        found = request.check(s) if request.check is not None else checked(s, context, before=base)
        return [p for p in found if script_proposals.finding_key(p, s) in keys]

    done = await _rounds(context, plan, script, list(on_steps), started, check=check, only=only)
    left = check(done.script)
    return WriteResult(done.script, [*spends, *done.spends], _warnings(left, done.script), plan)


def _string_at(script: CallScript, path: str) -> str | None:
    node: Any = script.model_dump(mode="json")
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, str) else None


async def _opening_only(request: WriteRequest) -> WriteResult:
    script = request.base or CallScript(schema_version=2)
    written, spends = await _opening(
        request.context, script, request.base, request.started, force=True
    )
    return WriteResult(written, spends)


async def _outcomes(request: WriteRequest) -> WriteResult:

    ask = request.outcomes
    if ask is None:
        raise ValueError("outcomes mode needs its request")
    context = request.context
    answer = await ask_json(
        ask.request,
        ask.instruction,
        parse=ask.parse,
        salvage=ask.salvage,
        azure_format=ask.azure_format,
        tenant_leg=context.tenant_leg,
        quota_exhausted=context.quota_exhausted,
        max_tokens=ask.max_tokens,
        temperature=ask.temperature,
        timeout_s=request_timeout(request.started) or MIN_REQUEST_S,
    )
    return WriteResult(request.base or CallScript(schema_version=2), [answer], value=answer)


_MODES: Final = {
    "whole": _whole,
    "steps": _steps,
    "lines": _lines,
    "opening": _opening_only,
    "outcomes": _outcomes,
}


async def write_script(request: WriteRequest) -> WriteResult:
    """Write or change a holder's script (see the module). Raises `WriteRefusedError` when
    nothing could be written (its spends still to be metered), and the ladder's
    `ProblemError` for the outcomes mode."""
    result = await _MODES[request.mode](request)
    log.info(
        "script_written",
        extra={
            "mode": request.mode,
            "kind": request.context.kind,
            "requests": len(result.spends),
            "left": len(result.left_out),
            "plan": result.plan.source if result.plan is not None else None,
        },
    )
    return result


__all__ = [
    "REWRITE_ROUNDS",
    "Mode",
    "OutcomesAsk",
    "Spent",
    "WriteRefusedError",
    "WriteRequest",
    "WriteResult",
    "by_step",
    "checked",
    "example_problems",
    "laid",
    "meter",
    "openings_kept",
    "plan_for",
    "request_timeout",
    "stage_with",
    "with_opening",
    "with_parts",
    "write_script",
]
