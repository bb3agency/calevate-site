"""Deterministic repairs of a written script's structure, before anyone reads it.

`script_lint` finds these defects; this module mends the ones code can mend without guessing
what the business meant, so the model's repair rounds are spent on wording rather than on
bookkeeping (the Rytu Khata campaign script of 23 Nov 2026 had broken step numbers, a step
nothing led to, a title said with no name, a call-back time asked and lost, a business name
spelled two ways with one pronunciation, and prices and bookings allowed on a free app-install
call). `settled` is run on every script Pip writes (`workers/script_proposal.finish_written`);
in an edit, only the steps Pip wrote or changed are touched, the owner's own as they are.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from calevate_shared.call_script import (
    CALL_BACK,
    MAX_PRONUNCIATIONS,
    MAX_STAGE_BRANCHES,
    MAX_STAGE_COLLECT,
    CallScript,
    ConversationStage,
    Pronunciation,
    ScenarioQa,
    ScenarioQaText,
    ScriptPolicies,
    StageBranch,
    StepOutcome,
    stage_steps,
)
from calevate_shared.spoken_guard import empty_title, without_empty_title

from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    asks_a_time,
    next_steps,
    reachable_steps,
    step_numbers_broken,
    unpronounced_spellings,
    unreached_steps,
)

#: The detail a step that asks for a better time notes, as the details list shows it.
CALL_BACK_TIME: Final = "When to call back"
#: The way out such a step takes once the person gives a time.
TIME_GIVEN: Final = "They give a time that suits them"


def _explicit_exits(stage: ConversationStage) -> set[str]:
    return {t for t in (stage.otherwise, *(b.target for b in stage.branches)) if t}


def _alternatives(stages: Sequence[ConversationStage], a: int, b: int) -> bool:
    """Whether stages `a` and `b` are two ways the same moment can go: a step sends the call
    to both by a way out of its own, and neither leads to the other."""
    preds = [
        {j for j, other in enumerate(stages) if stage.id in _explicit_exits(other)}
        for stage in stages
    ]
    return (
        bool(preds[a] & preds[b])
        and stages[b].id not in _explicit_exits(stages[a])
        and stages[a].id not in _explicit_exits(stages[b])
    )


def renumbered(script: CallScript) -> CallScript:
    """`script` with its step numbers following the call: each stage the next step, unless it
    and the one before it are numbered alike or are alternatives (`_alternatives`), and each
    outcome moved with its step. Numbers already right, or a script with none, are kept."""
    stages = script.stages
    if not stages or all(stage.step is None for stage in stages):
        return script
    steps = [1]
    for i in range(1, len(stages)):
        same = stages[i].step is not None and stages[i].step == stages[i - 1].step
        steps.append(steps[-1] if same or _alternatives(stages, i - 1, i) else steps[-1] + 1)
    if steps == [stage.step for stage in stages] and not step_numbers_broken(script):
        return script
    old = [stage.step if stage.step is not None else i for i, stage in enumerate(stages, 1)]
    moved: dict[int, int] = {}
    for was, now in zip(old, steps, strict=True):
        moved.setdefault(was, now)
    outcomes: dict[int, StepOutcome] = {}
    for outcome in script.step_outcomes:
        step = moved.get(outcome.step)
        if step is not None:
            outcomes.setdefault(step, outcome.model_copy(update={"step": step}))
    return script.model_copy(
        update={
            "stages": [
                s.model_copy(update={"step": n}) for s, n in zip(stages, steps, strict=True)
            ],
            "step_outcomes": sorted(outcomes.values(), key=lambda o: o.step),
        }
    )


def without_stray_outcomes(script: CallScript) -> CallScript:
    """`script` without the outcomes of steps it has no scenario for."""
    steps = set(stage_steps(script.stages))
    kept = [o for o in script.step_outcomes if o.step in steps]
    return (
        script
        if len(kept) == len(script.step_outcomes)
        else script.model_copy(update={"step_outcomes": kept})
    )


def reached(script: CallScript, mine: set[str]) -> CallScript:
    """`script` with each of Pip's steps (`mine`) that nothing leads to given a way in, named
    by the step (as a drafted `next` is, `script_assist._next_branches`): from each step that
    leads to another scenario of its step, else from the nearest reached step before it."""
    stages = list(script.stages)
    for _ in range(len(stages)):
        current = script.model_copy(update={"stages": stages})
        lost = [i for i in unreached_steps(current) if stages[i].id in mine]
        if not lost:
            break
        u = lost[0]
        steps = stage_steps(stages)
        found = reachable_steps(current, 0) | {0}
        siblings = {stages[j].id for j in found if steps[j] == steps[u] and j != u}
        parents = [j for j in sorted(found) if next_steps(current, j) & siblings]
        if not parents:
            parents = [max(j for j in found if j < u)] if any(j < u for j in found) else []
        added = False
        for p in parents:
            if len(stages[p].branches) < MAX_STAGE_BRANCHES:
                way = StageBranch(when=stages[u].name[:300], target=stages[u].id)
                stages[p] = stages[p].model_copy(update={"branches": [*stages[p].branches, way]})
                added = True
        if not added:
            break
    return script.model_copy(update={"stages": stages})


def _titled(text: str) -> str:
    return without_empty_title(text) if empty_title(text) else text


def without_empty_titles(script: CallScript, mine: set[str]) -> CallScript:
    """`script` with a title said where a name belongs, with no name, taken out of each line
    of Pip's steps and of the example call and sample phrases (`spoken_guard.empty_title`):
    the founder's rule is the name field before it or neither, and neither is the one code can
    write without guessing where the name goes."""
    stages = []
    for stage in script.stages:
        if stage.id not in mine:
            stages.append(stage)
            continue
        qa = [
            ScenarioQa(
                question=item.question,
                answer=_titled(item.answer),
                translations={
                    tag: ScenarioQaText(question=t.question, answer=_titled(t.answer))
                    for tag, t in item.translations.items()
                },
            )
            for item in stage.qa
        ]
        stages.append(
            stage.model_copy(
                update={
                    "sounds_like": _titled(stage.sounds_like),
                    "scripts": {tag: _titled(text) for tag, text in stage.scripts.items()},
                    "qa": qa,
                }
            )
        )
    example = [
        line.model_copy(update={"text": _titled(line.text)}) if line.speaker == "agent" else line
        for line in script.example_exchange
    ]
    style = script.style.model_copy(
        update={"sample_phrases": [_titled(p) for p in script.style.sample_phrases]}
    )
    out = script.model_copy(update={"stages": stages, "example_exchange": example, "style": style})
    return script if out == script else out


def time_taken(script: CallScript, mine: set[str]) -> CallScript:
    """`script` with each of Pip's steps that asks when to call back noting the time and going
    to the call back once it is given (`script_lint.untaken_time_problems`)."""
    stages = []
    for stage in script.stages:
        if stage.id not in mine or not asks_a_time(stage):
            stages.append(stage)
            continue
        collect = list(stage.collect)
        if not collect and len(collect) < MAX_STAGE_COLLECT:
            collect.append(CALL_BACK_TIME)
        branches = list(stage.branches)
        if CALL_BACK not in _explicit_exits(stage) and len(branches) < MAX_STAGE_BRANCHES:
            branches.insert(0, StageBranch(when=TIME_GIVEN, target=CALL_BACK))
        stages.append(stage.model_copy(update={"collect": collect, "branches": branches}))
    return script.model_copy(update={"stages": stages})


def pronounced(script: CallScript, context: LintContext) -> CallScript:
    """`script` with every other spelling of a taught word that the agent says anywhere
    (`script_lint.unpronounced_spellings`) taught with the same sound."""
    room = MAX_PRONUNCIATIONS - len(script.style.pronunciations)
    added = [
        Pronunciation(word=spelling[:80], say_as=say_as)
        for spelling, say_as in unpronounced_spellings(script, context)[: max(room, 0)]
    ]
    if not added:
        return script
    style = script.style.model_copy(
        update={"pronunciations": [*script.style.pronunciations, *added]}
    )
    return script.model_copy(update={"style": style})


def _mine(script: CallScript, base: CallScript | None) -> set[str]:
    """The ids of the steps Pip wrote or changed: all of them in a new script."""
    if base is None:
        return {stage.id for stage in script.stages}
    was = {stage.id: stage for stage in base.stages}
    return {stage.id for stage in script.stages if was.get(stage.id) != stage}


def settled(
    script: CallScript, context: LintContext, *, base: CallScript | None = None
) -> CallScript:
    """`script` with its structure mended (see the module): step numbers, outcomes of steps it
    lacks, Pip's unreached steps, titles with no name, call-back times, and spellings of taught
    words. A raw script is returned as it is. Validated again, so a mend that would break a
    rule never reaches the owner."""
    if script.raw_override is not None:
        return script
    mine = _mine(script, base)
    out = renumbered(script)
    out = without_stray_outcomes(out)
    out = reached(out, mine)
    out = without_empty_titles(out, mine)
    out = time_taken(out, mine)
    out = pronounced(out, context)
    return CallScript.model_validate(out.model_dump())


#: Digits, a rupee sign or a word for a price: what a source must hold before an agent may
#: be allowed to quote a price.
_PRICE: Final = re.compile(r"₹|\b(?:rs\.?|inr|rupees?|price|cost|fee|charges?)\b|\d", re.I)


def policies_for_job(
    policies: ScriptPolicies, *, sources: str, manifest: CapabilityManifest | None
) -> ScriptPolicies:
    """`policies` with what the job cannot back switched off: quoting prices when nothing the
    script was written from gives a price, and making bookings when the agent has no calendar.
    Only ever switches off: what the writer or owner switched off stays off."""
    return policies.model_copy(
        update={
            "share_prices": policies.share_prices and bool(_PRICE.search(sources)),
            "take_bookings": policies.take_bookings
            and manifest is not None
            and manifest.booking_tool,
        }
    )


__all__ = [
    "CALL_BACK_TIME",
    "TIME_GIVEN",
    "policies_for_job",
    "pronounced",
    "reached",
    "renumbered",
    "settled",
    "time_taken",
    "without_empty_titles",
    "without_stray_outcomes",
]
