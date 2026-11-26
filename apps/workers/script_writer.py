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
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    ScriptPolicies,
)
from calevate_shared.spoken_guard import latin_word_problem, textbook_problem
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.call_rules import said_line_problem
from apps.api.agents.mistake_lints import script_mistakes
from apps.api.agents.owner_plan import OwnerPlan, numbered_items, owner_plan, plan_problems
from apps.api.agents.retired_lines import retired_line_problem
from apps.api.agents.script_lint import (
    empty_title_problems,
    spoken_line_problems,
    stacked_actions,
    unasked_problems,
)
from apps.api.agents.script_plan import (
    PlanStep,
    ScriptPlan,
    outline_problems,
    plan_from_owner,
    plan_from_playbook,
    plan_from_script,
    skeleton,
    with_base_ids,
)
from apps.api.agents.script_shape import line_problems, structure_problems
from apps.api.agents.script_structure import policies_for_job, settled
from apps.api.agents.turn_checks import asked_opening_again, asks_done_too_soon, opened_again
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
    ask_json,
    language_problems,
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


def example_problems(script: CallScript, context: ScriptContext) -> list[str]:
    """The checks on each example turn: the said-line rules (no reaction first, no "noted"),
    textbook and provider words, English letters where the language takes none, a retired
    line, the spoken-line lint, several actions in one turn, a turn that asks whether it is
    done, and on the first step a turn that greets or asks again whether now suits."""
    lint = context.lint()
    brief = context.brief
    names = (brief.business_name, brief.agent_name)
    owners = context.owners_words
    last = len(script.stages) - 1
    openings = [s for s in (script.opening_line, script.outbound_opening_line) if s.strip()]
    found: list[str] = []
    for i, path, text in _example_lines(script):
        tag = path.split(".")[3]
        close = i == last
        found += [
            p
            for p in (
                said_line_problem(path, text, close=close),
                textbook_problem(path, text, tag, allowed=owners),
                provider_problem(path, text, allowed=owners),
                latin_word_problem(path, text, tag, names=names),
                retired_line_problem(path, text),
            )
            if p
        ]
        found += spoken_line_problems(path, text, lint)
        if stacked_actions(text):
            found.append(f"{path}: gives several actions at once; give one action and stop.")
        if asks_done_too_soon(text):
            found.append(
                f"{path}: asks whether it is done before they can do it; give the action and stop."
            )
        if i == 0 and openings and (opened_again(text) or asked_opening_again(text, openings)):
            found.append(
                f"{path}: greets again or asks again whether now is a good time; the opening "
                "did that. Start from their answer."
            )
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
    """Every check a written script is held to, as "<path>: <rule>" findings: the language
    and call rules, the shape and ways out, the owner's plan, the call-mistake checks, the
    line checks, details no step asks, and the example turns. With `before` (a change), a
    finding the script already had is the owner's, not the writer's.

    THE seam for the check registry (`agents/script_checks.run`): every path calls this and
    nothing else, so the swap is one line."""
    brief = context.written_brief()
    lint = context.lint()
    found = [
        *plan_problems(script, context.owner_plan, before),
        *language_problems(
            script,
            context.language,
            before=before,
            allowed=context.owners_words,
            names=(brief.business_name, brief.agent_name),
            introduced=brief.introduced,
            lint=lint,
            woven=brief.woven,
            direction=brief.direction,
        ),
        *script_mistakes(script, lint),
        *empty_title_problems(script),
        *line_problems(script, lint.judged),
        *unasked_problems(script, lint.collect, lint.call_back),
        # The main task's items are not read where the owner laid out the steps.
        *structure_problems(
            script,
            main_task="" if context.owner_plan is not None else context.main_task,
            call_back=lint.call_back,
        ),
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
    "back, an end or a transfer is never a step of its own. The last step closes the call on "
    "the one next thing. Return ONLY JSON."
)


def outline_request(context: ScriptContext, base: CallScript | None, hint: ScriptPlan) -> str:
    lines = [f"What the call is for:\n{context.main_task.strip()}"]
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
) -> tuple[OwnerPlan | None, Spent | None]:
    """A plan the model laid out in the task-steps shape, read like an owner's own; None
    when the answer does not hold one (`expect`: the steps it must keep, one per item)."""
    timeout_s = request_timeout(started)
    if timeout_s is None:
        return None, None
    try:
        answer = await _ask_steps(context, request, instruction, timeout_s)
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
    context: ScriptContext, request: str, instruction: str, timeout_s: float
) -> JsonAnswer[str]:

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
        read, spent = await _read_plan(
            context,
            outline_request(context, base, playbook),
            OUTLINE_INSTRUCTION,
            started,
            expect=None,
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
    instruction = " ".join(p for p in (context.instruction, note) if p.strip())
    return StepAsk(
        brief=context.written_brief(),
        plan=plan,
        step=step,
        languages=context.languages,
        opening=script.outbound_opening_line or script.opening_line,
        main_task=context.main_task,
        sources=context.grounding,
        instruction=instruction,
        tone=TONES.get(context.tone or "", ""),
        current=current,
        problems=tuple(problems),
    )


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
        out.words[key] = result.value
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


def openings_kept(script: CallScript, base: CallScript | None) -> CallScript:
    """`script` with any opening line it lacks put back from `base`: a blank opening is
    never a fix, the agent would open the call with nothing."""
    if base is None:
        return script
    restored = {
        name: kept
        for name, _placed in _OPENINGS
        if not str(getattr(script, name)).strip() and (kept := str(getattr(base, name)).strip())
    }
    return script.model_copy(update=restored) if restored else script


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
    script = openings_kept(script, base)
    brief = replace(context.written_brief(), description=context.main_task)
    dialled_all = brief.direction == "outbound"
    spends: list[Spent] = []
    for name, placed in _opening_fields(context):
        line = str(getattr(script, name)).strip()
        owners = base is not None and line == str(getattr(base, name)).strip()
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
        if request_timeout(started) is None:
            break
        try:
            answer = await write_opening(
                brief,
                line="" if force else line,
                problems=problems,
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
        script = with_opening(script, answer.value, placed=placed)
    return script, spends


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


async def _whole(request: WriteRequest) -> WriteResult:
    context, base, started = request.context, request.base, request.started
    plan, spends, read = await plan_for(context, base, started, outline=request.outline)
    script = skeleton(plan, base)
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
        if base is None or not (base.identity or base.goal)
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
    script = laid(script, first.words)
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
    found = checked(script, context)
    return _warnings([p for p in found if not by_step([p], script)], script)


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
