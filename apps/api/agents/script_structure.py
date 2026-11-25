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
from calevate_shared.extraction import whole_call_detail
from calevate_shared.spoken_guard import empty_title, without_empty_title

from apps.api.agents.script_lint import (
    CapabilityManifest,
    LintContext,
    asks_a_time,
    collected_label,
    next_steps,
    reachable_steps,
    stated_ways_out,
    step_numbers_broken,
    unpronounced_spellings,
    unreached_steps,
)
from apps.api.agents.script_shape import echo_branches

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


def _numbered_way_on(stages: Sequence[ConversationStage], i: int) -> bool:
    """Whether stage `i` is numbered as a later step than the one before it and an earlier
    stage reaches it as its way on (`otherwise`) rather than by a way out: the step after a
    scenario placed between them (a side step such as "Not registered" that a way out of step
    1 reaches), which the writer numbered on purpose and which is not another way step 1 can
    go. A way out named for the stage ("iPhone") still chooses between scenarios."""
    prev, own = stages[i - 1].step, stages[i].step
    if prev is None or own is None or own <= prev:
        return False
    return any(stage.otherwise == stages[i].id for stage in stages[: i - 1])


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
        alternative = _alternatives(stages, i - 1, i) and not _numbered_way_on(stages, i)
        steps.append(steps[-1] if same or alternative else steps[-1] + 1)
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


def time_taken(script: CallScript, mine: set[str], labels: Sequence[str] = ()) -> CallScript:
    """`script` with each of Pip's steps that asks when to call back noting the time and going
    to the call back once it is given (`script_lint.untaken_time_problems`). `labels`: the
    job's own names for what a call back takes (`LintContext.call_back`), each noted there;
    with none, the step notes `CALL_BACK_TIME` unless it already notes something."""
    stages = []
    for stage in script.stages:
        if stage.id not in mine or not asks_a_time(stage):
            stages.append(stage)
            continue
        collect = list(stage.collect)
        has = {c.casefold() for c in collect}
        wanted = [label for label in labels if label.casefold() not in has]
        if not labels and not collect:
            wanted = [CALL_BACK_TIME]
        collect += wanted[: max(MAX_STAGE_COLLECT - len(collect), 0)]
        branches = list(stage.branches)
        if CALL_BACK not in _explicit_exits(stage) and len(branches) < MAX_STAGE_BRANCHES:
            branches.insert(0, StageBranch(when=TIME_GIVEN, target=CALL_BACK))
        stages.append(stage.model_copy(update={"collect": collect, "branches": branches}))
    return script.model_copy(update={"stages": stages})


def ways_out_wired(
    script: CallScript, mine: set[str], manifest: CapabilityManifest | None
) -> CallScript:
    """`script` with each way out that one of the `mine` steps states only in its instruction
    ("If they cannot, offer to call back") given as the branch it states
    (`script_lint.stated_ways_out`), so the call flow draws it and the engine is sent it. The
    instruction keeps its words: they still tell the agent how to take the way out."""
    steps = stage_steps(script.stages)
    last = max(steps, default=0)
    stages = []
    for stage, step in zip(script.stages, steps, strict=True):
        found = (
            stated_ways_out(stage, last_step=step == last, manifest=manifest)
            if stage.id in mine
            else []
        )
        stages.append(
            stage.model_copy(update={"branches": [*stage.branches, *found]}) if found else stage
        )
    out = script.model_copy(update={"stages": stages})
    return script if out == script else out


def without_judged_asks(script: CallScript, mine: set[str]) -> CallScript:
    """`script` with no step of `mine` collecting a detail that is judged from the call
    (`extraction.whole_call_detail`: a status, whether the goal was met, a comfort or interest
    level): the pipeline writes it after the call, and a step that collects it asks the person
    for it, as "Technical Comfort Level" was asked on the 25 Nov 2026 call."""
    stages = [
        stage.model_copy(
            update={"collect": [c for c in stage.collect if not _judged(collected_label(c))]}
        )
        if stage.id in mine and any(_judged(collected_label(c)) for c in stage.collect)
        else stage
        for stage in script.stages
    ]
    out = script.model_copy(update={"stages": stages})
    return script if out == script else out


def _judged(label: str) -> bool:
    """Whether a detail of this label is judged from the call, never asked."""
    return whole_call_detail("", label)


def without_echo_ways(script: CallScript, mine: set[str]) -> CallScript:
    """`script` without the ways out of Pip's steps that only name the step the call goes to
    anyway (`script_shape.echo_branches`): "when: Add Farms -> Add Farms" is no condition,
    and the next step is where the call goes when no way out holds."""
    drop = {(i, j) for i, j in echo_branches(script) if script.stages[i].id in mine}
    if not drop:
        return script
    stages = [
        stage.model_copy(
            update={"branches": [b for j, b in enumerate(stage.branches) if (i, j) not in drop]}
        )
        if any(at == i for at, _j in drop)
        else stage
        for i, stage in enumerate(script.stages)
    ]
    return script.model_copy(update={"stages": stages})


def _takes_call_back(stage: ConversationStage) -> bool:
    """Whether a step is where a call back is arranged: it asks for a later time. A step that
    only goes to the call back leaves the time to the call-back path, which asks it."""
    return asks_a_time(stage)


def collected(
    script: CallScript, labels: Sequence[str], mine: set[str], call_back: Sequence[str] = ()
) -> CallScript:
    """`script` with each of Pip's steps noting only details the job notes (`labels`), each
    under the job's own name: an entry the writer copied with its "when" hint ("Name: only if
    not known") is cut to the label, and one the job does not note is dropped, since what a
    call asks and what is written down agree (D-1028). A detail a call back takes
    (`call_back`) stays only on a step that asks for a later time, when the call has a
    call-back path that asks it (such a step, or a way out to the call back):
    asked anywhere else it is asked of everyone (step 1 of the 25 Nov 2026 Rytu Khata call
    asked for another number). With no `labels` (an agent's own script, or a job that notes
    none) the steps are left as they are."""
    if not labels:
        return script
    named = {label.casefold(): label for label in labels}
    # Only where the call has a call-back path to ask them on: a step that asks for a later time
    # or a way out to the call back (`script_lint.unasked_details` reads them as asked there).
    has_path = any(
        asks_a_time(stage) or CALL_BACK in _explicit_exits(stage) for stage in script.stages
    )
    later = {label.casefold() for label in call_back} if has_path else set()
    stages = []
    for stage in script.stages:
        if stage.id not in mine:
            stages.append(stage)
            continue
        kept = list(
            dict.fromkeys(
                named[key]
                for entry in stage.collect
                if (key := collected_label(entry).casefold()) in named
                and (key not in later or _takes_call_back(stage))
            )
        )
        stages.append(
            stage if kept == stage.collect else stage.model_copy(update={"collect": kept})
        )
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
    lacks, Pip's unreached steps, ways out that only name the next step, titles with no name,
    the details each step notes, call-back times, ways out stated only in words, and
    spellings of taught words. A raw script is returned as it is. Validated again, so a mend
    that would break a rule never reaches the owner."""
    if script.raw_override is not None:
        return script
    mine = _mine(script, base)
    out = renumbered(script)
    out = without_stray_outcomes(out)
    out = reached(out, mine)
    out = without_echo_ways(out, mine)
    out = without_judged_asks(out, mine)
    out = without_empty_titles(out, mine)
    out = collected(out, context.collect, mine, context.call_back)
    out = time_taken(out, mine, context.call_back)
    out = ways_out_wired(out, mine, context.manifest)
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
    "collected",
    "policies_for_job",
    "pronounced",
    "reached",
    "renumbered",
    "settled",
    "time_taken",
    "ways_out_wired",
    "without_echo_ways",
    "without_empty_titles",
    "without_judged_asks",
    "without_stray_outcomes",
]
