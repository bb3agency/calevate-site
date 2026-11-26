"""Checks on how a written script is built, beyond its single lines (25 Nov 2026).

The Rytu Khata campaign script Pip wrote that day was valid by every other check and still
made a bad call: step 1 asked five details at once, each step had a "way out" that was only
the next step's name, a case that arises in step 1 ("they do not remember registering") sat as
a step after the close, two of the six numbered tasks of the main task were dropped, and a
line had the agent "note" what the caller enters in the app. Each check here names one of
those shapes for any business and any call language:

* STRUCTURE (`structure_problems`), which only a rewrite of the whole script can mend: more
  than one detail asked in one step, a step after the close or reached only from it, and a
  numbered task of the main task that no step covers. The plan is built by code so these
  should not arise; the one writer's checks (`script_writer.checked`) name any that do, and
  what is left is a warning the owner reads.
* LINES (`line_problems`), which the targeted repair rewrites like any call-mistake finding
  (`script_writer.checked`, `agents/script_heal.heal_findings`): a line that gives
  several things to do at once, and a line in which the agent says it will note or record
  something in a step that notes nothing, which is the caller's own action or an empty
  promise. Read in English words only; a line in another language is judged by the review
  pass (`campaign_script_ask.REVIEW_INSTRUCTION`), which reads every language.
* ECHO WAYS OUT (`echo_branches`), which code removes (`script_structure.without_echo_ways`):
  a way out whose condition is only its target's name, going where the call goes anyway.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from calevate_shared.call_script import CallScript, ConversationStage, stage_steps
from calevate_shared.extraction import whole_call_detail
from calevate_shared.spoken_guard import has_indic_letters

from apps.api.agents.script_lint import (
    OPENING_FIELDS,
    agent_lines,
    closes_the_call,
    collected_label,
    next_steps,
    stacked_actions,
)

#: The name Pip gives the close (`campaign_script_ask.CLOSING_STEP`), read only for a script
#: none of whose steps closes the call by its role.
CLOSING_NAME: Final = re.compile(r"^\s*finali[sz]e\s+the\s+call\s*$", re.IGNORECASE)


def closing_index(script: CallScript) -> int | None:
    """The index of the step that closes the call, or None.

    By role first (`script_lint.closes_the_call`): an owner renames steps, and the 25 Nov
    2026 close said "close the call" whatever it was called. Of several, the one in the
    latest step: a scenario that ends the call early ("Wrong person, apologise and end the
    call") sits in the step where that case arises, the close after every task. The name
    is the fallback for a close that states neither."""
    steps = stage_steps(script.stages)
    closes = [i for i, stage in enumerate(script.stages) if closes_the_call(stage)]
    if closes:
        return max(closes, key=lambda i: (steps[i], i))
    return next((i for i, s in enumerate(script.stages) if CLOSING_NAME.match(s.name)), None)


def _default_next(script: CallScript, index: int) -> str:
    """Where step `index` goes when none of its ways out holds."""
    stage = script.stages[index]
    if stage.otherwise:
        return stage.otherwise
    return script.stages[index + 1].id if index + 1 < len(script.stages) else ""


def echo_branches(script: CallScript) -> list[tuple[int, int]]:
    """(step index, way-out index) of each way out whose condition says nothing but the name
    of the step it goes to, when that step is where the call goes anyway and it is the only
    scenario of its step. Such a way out tells the in-call model to move on when "Add Farms"
    holds, which is no condition, and draws a second arrow beside the default one. A name
    that chooses between scenarios of the next step is a real choice and stays."""
    steps = stage_steps(script.stages)
    by_id = {stage.id: i for i, stage in enumerate(script.stages)}
    found: list[tuple[int, int]] = []
    for i, stage in enumerate(script.stages):
        default = _default_next(script, i)
        for j, branch in enumerate(stage.branches):
            target = by_id.get(branch.target)
            if target is None or branch.target != default:
                continue
            alone = steps.count(steps[target]) == 1
            named = (
                " ".join(branch.when.split()).casefold()
                == " ".join(script.stages[target].name.split()).casefold()
            )
            if alone and named:
                found.append((i, j))
    return found


def named_way_problems(script: CallScript) -> list[str]:
    """A way out whose condition is only the name of the step it jumps to, where the call
    would not go anyway (code removes those, `echo_branches`): a condition must be a caller
    state (docs/evidence/voice-agent-research-2026-11-25.md §C "Branches"). Departure: a name
    that chooses between scenarios of one step ("Android", "iPhone") is a caller state too, so
    it stays."""
    steps = stage_steps(script.stages)
    by_id = {stage.id: i for i, stage in enumerate(script.stages)}
    echoes = set(echo_branches(script))
    found: list[str] = []
    for i, stage in enumerate(script.stages):
        for j, branch in enumerate(stage.branches):
            target = by_id.get(branch.target)
            if target is None or (i, j) in echoes or steps.count(steps[target]) > 1:
                continue
            name = script.stages[target].name
            if " ".join(branch.when.split()).casefold() == " ".join(name.split()).casefold():
                found.append(
                    f'stages.{i}.branches: the way out to "{name}" has only that step\'s name as '
                    "its condition; say what the person says or has done that leads there."
                )
    return found


def _predecessors(script: CallScript) -> dict[int, set[int]]:
    by_id = {stage.id: i for i, stage in enumerate(script.stages)}
    preds: dict[int, set[int]] = {i: set() for i in range(len(script.stages))}
    for i in range(len(script.stages)):
        for target in next_steps(script, i):
            if (j := by_id.get(target)) is not None and j != i:
                preds[j].add(i)
    return preds


def trailing_problems(script: CallScript) -> list[str]:
    """A step placed after the close, or reached only from it. A case that arises in a step
    ("they do not remember registering", "wrong person") belongs to that step, as a way out
    to a scenario of it; after the close the call has already thanked them and ended."""
    close = closing_index(script)
    if close is None:
        return []
    preds = _predecessors(script)
    name = script.stages[close].name
    return [
        f'stages.{j}: "{stage.name}" comes after the close ("{name}"), or only the close leads '
        "to it; make it a scenario of the step where that case arises, reached by a way out "
        "of that step whose condition says when, and keep the close the last step."
        for j, stage in enumerate(script.stages)
        if j != close and (j > close or (preds[j] and preds[j] <= {close}))
    ]


def piled_problems(script: CallScript, call_back: Sequence[str] = ()) -> list[str]:
    """A step that collects more than one detail: the in-call model asks them together, as
    step 1 of the 25 Nov 2026 call asked five. The details a call back takes are asked
    together on that path (`script_structure.time_taken`), so they count as one."""
    later = {label.casefold() for label in call_back}
    found: list[str] = []
    for i, stage in enumerate(script.stages):
        asked = [c for c in stage.collect if collected_label(c).casefold() not in later]
        if len(asked) > 1:
            names = ", ".join(f'"{collected_label(c)}"' for c in asked)
            found.append(
                f"stages.{i}.collect: asks for {len(asked)} details in one step ({names}); "
                "keep one here and ask each other one in the step where the call reaches it, "
                "one question per line."
            )
    return found


#: A numbered item of the owner's main task ("1. Install the app"), at a line start or after
#: a space for a list written on one line, and a bulleted one ("- Set the language") at a
#: line start.
_NUMBER_MARK: Final = re.compile(r"(?:^|(?<=\s))(\d{1,2})[.)]\s+", re.MULTILINE)
_BULLET_MARK: Final = re.compile(r"^[ \t]*[-*•]\s+", re.MULTILINE)
_WORD: Final = re.compile(r"[A-Za-z]+")
#: Words of a task that say nothing about which task it is.
_PLAIN_WORDS: Final = frozenset(
    {
        "the", "and", "for", "that", "this", "them", "they", "their", "then", "with", "from",
        "into", "onto", "how", "what", "which", "when", "where", "who", "why", "are", "was",
        "were", "has", "have", "had", "its", "our", "your", "you", "all", "any", "each", "one",
        "first", "also", "help", "ask", "tell", "call", "caller", "person", "customer", "user",
        "step", "steps", "way", "make", "sure", "out", "find", "explain", "better",
    }
)  # fmt: skip
#: Long enough to tell tasks apart, short enough that "installed" meets "install".
_STEM: Final = 5


def _stems(text: str) -> set[str]:
    return {
        word.casefold()[:_STEM]
        for word in _WORD.findall(text)
        if len(word) >= 3 and word.casefold() not in _PLAIN_WORDS
    }


def main_task_items(main_task: str) -> list[str]:
    """The numbered or bulleted items of the main task, in order; [] for a main task written
    as prose, whose tasks the review pass reads (`missing_task`). Numbers count only as the
    list 1, 2, 3 ..., so a price or a count in a sentence ("costs 99. Then") is not an item."""
    numbered = list(_NUMBER_MARK.finditer(main_task))
    numbers = [int(mark.group(1)) for mark in numbered]
    marks = (
        numbered
        if numbers and numbers == list(range(1, len(numbers) + 1))
        else list(_BULLET_MARK.finditer(main_task))
    )
    if len(marks) < 2:
        return []
    items = []
    for n, mark in enumerate(marks):
        end = marks[n + 1].start() if n + 1 < len(marks) else len(main_task)
        item = " ".join(main_task[mark.end() : end].split())
        if item:
            items.append(item)
    return items


def _step_texts(script: CallScript) -> list[str]:
    """Each step's English text, its scenarios together: names, instructions, small steps,
    conditions and the questions it answers."""
    texts: dict[int, list[str]] = {}
    for stage, step in zip(script.stages, stage_steps(script.stages), strict=True):
        texts.setdefault(step, []).append(_stage_words(stage))
    return [" ".join(parts) for _step, parts in sorted(texts.items())]


def _stage_words(stage: ConversationStage) -> str:
    return " ".join(
        [
            stage.name,
            stage.instruction,
            *(p.action for p in stage.procedure),
            *(b.when for b in stage.branches),
            *(qa.question for qa in stage.qa),
        ]
    )


def uncovered_items(script: CallScript, main_task: str) -> list[str]:
    """The main task's items (`main_task_items`) that no step carries: none of the call's
    steps has at least half of the item's words (three at most), by their first five letters.
    An item with no English-letter word cannot be compared with English instructions and is
    left to the review pass."""
    steps = [_stems(text) for text in _step_texts(script)]
    missing: list[str] = []
    for item in main_task_items(main_task):
        wanted = _stems(item)
        if not wanted:
            continue
        need = min(3, (len(wanted) + 1) // 2)
        if not any(len(wanted & said) >= need for said in steps):
            missing.append(item)
    return missing


def coverage_problems(script: CallScript, main_task: str) -> list[str]:
    if not script.stages:
        return []
    return [
        f'script: the main task asks "{item}", and no step covers it; give it a step with its '
        "outcome, or a scenario of the step it belongs to (a path for one device or plan is a "
        "scenario of the same step), walking the person through it one action at a time."
        for item in uncovered_items(script, main_task)
    ]


def structure_problems(
    script: CallScript, *, main_task: str = "", call_back: Sequence[str] = ()
) -> list[str]:
    """What only a rewrite of the whole script mends (see the module). [] for a hand-written
    script, which has no steps to read."""
    if script.raw_override is not None:
        return []
    return [
        *piled_problems(script, call_back),
        *trailing_problems(script),
        *named_way_problems(script),
        *coverage_problems(script, main_task),
    ]


#: The agent saying it will write something down ("I'll note it", "let me record that").
_AGENT_RECORDS: Final = re.compile(
    r"\b(?:i'?ll|i will|let me|i'?m going to|i am going to|i can)\s+(?:just\s+)?"
    r"(?:note|record|enter|save|write|fill|register|log|update|add)\b",
    re.IGNORECASE,
)


def _step_of(path: str) -> int | None:
    found = re.match(r"^stages\.(\d+)\.", path)
    return int(found.group(1)) if found else None


def _english_lines(script: CallScript) -> list[tuple[str, str]]:
    """The agent's lines in English words, the openings left alone: they carry the notices
    and have their own checks."""
    if script.raw_override is not None:
        return []
    return [
        (path, text)
        for path, text in agent_lines(script)
        if path not in OPENING_FIELDS and not has_indic_letters(text)
    ]


def several_action_problems(script: CallScript) -> list[str]:
    """A line that gives the person several things to do at once (`script_lint.
    stacked_actions`): one caller action per step (research §C "Step design")."""
    return [
        f"{path}: gives several things to do in one line; give one action, wait until they "
        "say it is done, then give the next."
        for path, text in _english_lines(script)
        if stacked_actions(text)
    ]


def caller_action_claimed_problems(script: CallScript) -> list[str]:
    """A line in which the agent says it will note or record something in a step that notes
    nothing: what the person enters in the app is theirs to do (research §C "Step design")."""
    found: list[str] = []
    for path, text in _english_lines(script):
        step = _step_of(path)
        if (
            step is not None
            and step < len(script.stages)
            and not script.stages[step].collect
            and _AGENT_RECORDS.search(text)
        ):
            found.append(
                f"{path}: says the agent will note or record something in a step that notes "
                "nothing; what the person does in the app is theirs to do, so ask them to do "
                "it and say when it is done."
            )
    return found


def echo_problems(script: CallScript) -> list[str]:
    """`echo_branches` as findings, for a screen or a scorer; code removes them."""
    return [
        f'stages.{i}.branches: the way out "{script.stages[i].branches[j].when}" only names '
        "the step the call goes to anyway; leave it out."
        for i, j in echo_branches(script)
    ]


#: An instruction sentence that has the agent ask. "Note" is left out, since noting a
#: judgement is the agent's own reading, and so is "confirm".
_ASK_VERB: Final = re.compile(
    r"\b(?:ask|asks|asking|collect|collects|get|gets|find out|request|tell me)\b", re.IGNORECASE
)
_ASK_NEGATED: Final = re.compile(
    r"\b(?:do not|don'?t|never|not|without)\s+(?:\w+\s+)?(?:ask|collect|request)", re.IGNORECASE
)
_SENTENCE: Final = re.compile(r"[^.?!;]+[.?!;]?")


def _judged_words(label: str) -> list[str]:
    """The words of `label` that make it judged (`whole_call_detail`): "goal" of "Campaign
    goal met", "interest" of "Primary usage interest", and a pair such as "tech level" only
    where neither word is one alone."""
    words = [w.casefold() for w in _WORD.findall(label)]
    single = [w for w in words if whole_call_detail("", w)]
    pairs = [
        f"{a} {b}"
        for a, b in pairwise(words)
        if a not in single and b not in single and whole_call_detail("", f"{a} {b}")
    ]
    return [*single, *pairs]


def _names_detail(sentence: str, label: str) -> bool:
    """Whether `sentence` names the detail `label`: every telling word of the label ("the
    caller name, campaign goal met"), or its judged word as the person's own ("your goal",
    "their interest"). The judged word alone is not enough: "the interest rate" is not
    the caller's interest."""
    wanted = _stems(label)
    if wanted and wanted <= _stems(sentence):
        return True
    return any(
        re.search(rf"\b(?:your|their|his|her)\s+(?:\w+\s+)?{re.escape(w)}s?\b", sentence, re.I)
        for w in _judged_words(label)
    )


def _asking_sentences(path: str, text: str) -> list[str]:
    """The sentences of `text` that ask something: in an instruction, one that tells the
    agent to ask; in a line, a question. A line in an Indian language is left to the review
    pass, which reads every language."""
    sentences = [s.strip() for s in _SENTENCE.findall(" ".join(text.split())) if s.strip()]
    if path.endswith(".instruction"):
        return [s for s in sentences if _ASK_VERB.search(s) and not _ASK_NEGATED.search(s)]
    if has_indic_letters(text):
        return []
    return [s for s in sentences if s.endswith(("?", "\uff1f"))]


def judged_ask_problems(script: CallScript, judged: Sequence[str]) -> list[str]:
    """An instruction or a line that asks one of the job's details judged from the whole call
    (`judged`, by `extraction.whole_call_detail`): nobody can answer "what is your technical
    comfort level?", and the 25 Nov 2026 call asked a farmer for "your goal, your tech
    awareness and your interest" from its instruction and line, never a collect list. The
    openings are left out, as the other line checks leave them."""
    if script.raw_override is not None or not judged:
        return []
    texts = [
        *((f"stages.{i}.instruction", stage.instruction) for i, stage in enumerate(script.stages)),
        *((path, text) for path, text in agent_lines(script) if path not in OPENING_FIELDS),
    ]
    found: list[str] = []
    for path, text in texts:
        asking = _asking_sentences(path, text)
        for label in judged:
            if any(_names_detail(sentence, label) for sentence in asking):
                found.append(
                    f'{path}: asks "{label}", which is worked out after the call, never asked; '
                    "leave it out and ask only what the person can answer."
                )
    return found


def line_problems(script: CallScript, judged: Sequence[str] = ()) -> list[str]:
    """The lines a targeted repair rewrites (see the module), with each instruction or line
    that asks a detail of `judged`. English words only."""
    return [
        *several_action_problems(script),
        *caller_action_claimed_problems(script),
        *judged_ask_problems(script, judged),
    ]


__all__ = [
    "CLOSING_NAME",
    "caller_action_claimed_problems",
    "closing_index",
    "coverage_problems",
    "echo_branches",
    "echo_problems",
    "judged_ask_problems",
    "line_problems",
    "main_task_items",
    "named_way_problems",
    "piled_problems",
    "several_action_problems",
    "structure_problems",
    "trailing_problems",
    "uncovered_items",
]
