"""After each call on a campaign or inbound line: which steps of its script reached their outcome
(founder, 24 Nov 2026). The reading and what it feeds are `crm/step_progress`.

One answer on the Gemini leg alone (`ask_json(gemini_only=True)`): it reads callers' words,
redacted, and must not reach a vendor whose terms permit training on inputs (Sarvam ToS
s.17.5, D-827), the lead-detail suggestions' reason. Nobody pressed a button for it, so an
account whose owner has not turned Pip on is not read (`account_content_may_reach_models`)
and its calls keep the extraction's own reading.

A REACHED CLAIM NEEDS THE PERSON'S OWN WORDS. Each `reached` names a caller line and quotes
it; the code checks the line is the caller's and the quote is copied from it
(`campaign_script_ask.copied_in`), the campaign script review's evidence rule, and a claim
that fails is stored as `unclear`. A `moved_on_turn` must name an agent line. The model also
maps the choices of each detail the call notes onto the steps, where the choices follow them;
the mapping is a property of the script and the details, and which choice is noted is then
decided by the furthest step the evidence shows (`crm/step_progress.progress_values`). The
campaign goal and the agent's business outcomes are mapped onto steps the same way, for the
goal verdict and the outcome tag (`workers/step_truth`).

The reading is taken BEFORE the extraction, so the extraction is asked against it and
settled by it before anything is stored (`pipeline._step_facts`).

Idempotent per call: a stored reading is reused, so a re-driven pipeline never pays twice.
Metered at our cost (`ASSIST_FEATURE_STEP_PROGRESS`, absorbed like the language pass).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.call_script import CallScript, ConversationStage, stage_steps
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionSchemaSpec

from apps.api.agents.assist_leg import google_assist_leg
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_STEP_PROGRESS
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.crm.step_progress import (
    STEP_STATES,
    StepProgress,
    StepReading,
    holder_script,
    store_progress,
    stored_progress,
)
from apps.api.db.session import tenant_session
from apps.workers.campaign_script_ask import copied_in
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

MAX_TOKENS: Final = 3_000
TIMEOUT_S: Final = 40.0
#: The transcript the judge reads, in characters: a long call's tail is where steps end, so
#: the head is cut, never the tail.
TRANSCRIPT_CHARS: Final = 24_000
_QUOTE_MAX: Final = 300
#: How many lines either side of the one the model named a quote is looked for in.
_NEAR_LINES: Final = 2

ASK: Final = (
    "You read a finished phone call against the steps of the script the agent followed. For "
    "each step under STEPS, say whether its outcome was reached. reached: only when the "
    "person's own words show it; give caller_turn, the number of that person's line, and "
    "quote, words copied exactly from that line in the letters it is written in, never "
    "translated or transliterated. A short reply such as done, I did it, or I can see it, "
    "right after the agent asked for that step's action, is the person's own words showing "
    "it. The agent saying it is done, or assuming it, does not count. A step can have "
    "several scenarios: scenario is the one the call was in when the step's outcome was "
    "reached, else the last one of that step it went through, named as under STEPS; empty "
    "for a step with one scenario or none gone through. "
    "not_reached: the call never got there; give moved_on_turn, the number "
    "of the agent line that went on to a later step while it was not reached and the person "
    "had not refused, could not do it now or was not the right person, else -1. unclear: the "
    "call does not show either way. Use -1 and an empty quote where a number or quote does "
    "not apply. Under fields, for each detail under DETAILS whose choices follow the steps of "
    "the call (a status or how far they got), map each choice to the step whose outcome it "
    "means, leaving out a choice that means no step; leave out a detail whose choices do not "
    "follow the steps. A yes-or-no detail (choices true) that means one step's outcome was "
    "reached, such as the goal being met or the set-up being done, maps true to that step. "
    "goal_step: the step whose outcome means the GOAL is met, else -1. Under outcomes, map "
    "each outcome under OUTCOMES that means a step's outcome was reached to that step; leave "
    "out an outcome that means no step. claimed_done_turn: the number of the agent line that "
    "told the person the whole task or every step was done while a step on their way through "
    "the call had not reached its outcome, else -1."
)

_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "call_step_progress",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "state": {"type": "string", "enum": list(STEP_STATES)},
                            "caller_turn": {"type": "integer"},
                            "quote": {"type": "string"},
                            "scenario": {"type": "string"},
                            "moved_on_turn": {"type": "integer"},
                        },
                        "required": [
                            "step",
                            "state",
                            "caller_turn",
                            "quote",
                            "scenario",
                            "moved_on_turn",
                        ],
                        "additionalProperties": False,
                    },
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "choices": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "choice": {"type": "string"},
                                        "step": {"type": "integer"},
                                    },
                                    "required": ["choice", "step"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["key", "choices"],
                        "additionalProperties": False,
                    },
                },
                "goal_step": {"type": "integer"},
                "claimed_done_turn": {"type": "integer"},
                "outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}, "step": {"type": "integer"}},
                        "required": ["key", "step"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["steps", "fields", "goal_step", "outcomes", "claimed_done_turn"],
            "additionalProperties": False,
        },
    },
}


def steps_of(script: CallScript) -> dict[int, list[ConversationStage]]:
    out: dict[int, list[ConversationStage]] = defaultdict(list)
    for stage, step in zip(script.stages, stage_steps(script.stages), strict=True):
        out[step].append(stage)
    return dict(sorted(out.items()))


def step_scenarios(script: CallScript) -> dict[int, tuple[str, ...]]:
    """Each step's scenario names, the main one first: a side step comes after the step it
    is a scenario of in the script's order (`call_script.outcomes_by_stage`)."""
    return {n: tuple(s.name for s in stages) for n, stages in steps_of(script).items()}


def step_names(script: CallScript) -> dict[int, str]:
    """Each step by its main scenario's name. A step is not named by all its scenarios
    joined: a call goes through one of them, and the joined name read on the call page as
    if the caller had been through both."""
    return {n: names[0] for n, names in step_scenarios(script).items()}


def redacted_lines(turns: Sequence[TranscriptTurn]) -> dict[int, tuple[str, str]]:
    """{turn idx: (speaker, redacted words)} for each line with words."""
    out: dict[int, tuple[str, str]] = {}
    for turn in turns:
        words = (turn.text_redacted or redact(turn.text).text).strip()
        if words and turn.speaker in ("caller", "agent"):
            out[turn.idx] = (turn.speaker, " ".join(words.split()))
    return out


def request_text(
    script: CallScript,
    lines: dict[int, tuple[str, str]],
    spec: ExtractionSchemaSpec,
    *,
    goal: str | None = None,
    outcomes: Sequence[BusinessOutcome] = (),
) -> str:
    said = {o.step: o.outcome for o in script.step_outcomes}
    steps = []
    for n, stages in steps_of(script).items():
        names = (
            stages[0].name
            if len(stages) == 1
            else "scenarios: " + "; ".join(s.name for s in stages)
        )
        aim = said.get(n) or " ".join(s.instruction for s in stages)
        steps.append(redact(f"Step {n} ({names}): {aim}").text)
    details = [
        f"{f.key} ({redact(f.label).text}): "
        + ("true" if f.type == "bool" else "; ".join(f.enum_values or []))
        for f in spec.fields
        if (f.type == "enum" and f.enum_values) or f.type == "bool"
    ]
    ends = [redact(f"{o.key}: {o.label}. {o.meaning}".strip()).text for o in outcomes]
    goal_text = redact(" ".join((goal or script.goal or "").split())).text
    transcript = "\n".join(
        f"[{idx}] {'Person' if speaker == 'caller' else 'Agent'}: {words}"
        for idx, (speaker, words) in sorted(lines.items())
    )[-TRANSCRIPT_CHARS:]
    return "\n\n".join(
        [
            "STEPS\n" + "\n".join(steps),
            "DETAILS\n" + ("\n".join(details) if details else "None."),
            "GOAL\n" + (goal_text or "None."),
            "OUTCOMES\n" + ("\n".join(ends) if ends else "None."),
            "TRANSCRIPT\n" + transcript,
        ]
    )


def _quoted_turn(quote: str, turn: object, lines: dict[int, tuple[str, str]]) -> int | None:
    """The caller line `quote` is copied from (`copied_in`): the line named, else the nearest
    caller line within `_NEAR_LINES` of it, so a line numbered one off still stands on the
    words it quotes. None when no caller line there holds the quote."""
    if not quote or not isinstance(turn, int) or isinstance(turn, bool):
        return None
    near = sorted(range(turn - _NEAR_LINES, turn + _NEAR_LINES + 1), key=lambda i: abs(i - turn))
    for idx in near:
        line = lines.get(idx)
        if line is not None and line[0] == "caller" and copied_in(quote, line[1]):
            return idx
    return None


def _scenario(row: dict[str, Any], scenarios: Sequence[str]) -> str | None:
    """The scenario the model says the call went through, as the script names it."""
    said = " ".join(str(row.get("scenario") or "").split()).casefold()
    return next((s for s in scenarios if " ".join(s.split()).casefold() == said), None)


def checked(
    raw: dict[str, Any],
    *,
    names: dict[int, str],
    lines: dict[int, tuple[str, str]],
    spec: ExtractionSchemaSpec,
    outcomes: Sequence[BusinessOutcome] = (),
    scenarios: dict[int, tuple[str, ...]] | None = None,
) -> StepProgress:
    """What the code can stand behind: a `reached` whose caller line and quote check out, a
    `moved_on_turn` that is an agent line, every step present (`unclear` when not judged),
    a detail's choices mapped onto steps (`_fields`), and a goal step and outcome keys that
    name real steps and real outcomes.

    `names` is each step's main scenario (`step_names`); a step with several (`scenarios`)
    is named by the one the model says the call went through when it is one of them."""
    last = max(names) if names else 0
    found: dict[int, StepReading] = {}
    rows = raw.get("steps")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        step, state = row.get("step"), row.get("state")
        if not isinstance(step, int) or step not in names or step in found:
            continue
        if state not in STEP_STATES:
            continue
        quote = " ".join(str(row.get("quote") or "").split())[:_QUOTE_MAX]
        moved = row.get("moved_on_turn")
        name = _scenario(row, (scenarios or {}).get(step, ())) or names[step]
        reading = StepReading(step=step, name=name, state="unclear")
        if state == "reached":
            turn = _quoted_turn(quote, row.get("caller_turn"), lines)
            if turn is not None:
                reading = StepReading(step, name, "reached", turn_idx=turn)
        elif state == "not_reached":
            agent = isinstance(moved, int) and lines.get(moved, ("", ""))[0] == "agent"
            reading = StepReading(
                step,
                name,
                "not_reached",
                moved_on_turn=moved if agent and step < last else None,
            )
        found[step] = reading
    steps = tuple(found.get(n, StepReading(n, name, "unclear")) for n, name in names.items())
    goal_step = raw.get("goal_step")
    progress = StepProgress(
        steps=steps,
        fields=_fields(raw, names, spec),
        goal_step=goal_step if isinstance(goal_step, int) and goal_step in names else None,
        outcomes=_outcomes(raw, names, outcomes),
    )
    claimed = raw.get("claimed_done_turn")
    # Kept only where the code agrees a step before the last is unfinished: the judge's word
    # that the agent claimed it all done is not enough on a call the evidence shows complete.
    unfinished = any(not progress.shows_reached(n) for n in names if n < last)
    if isinstance(claimed, int) and lines.get(claimed, ("", ""))[0] == "agent" and unfinished:
        return replace(progress, claimed_done_turn=claimed)
    return progress


def _fields(
    raw: dict[str, Any], names: dict[int, str], spec: ExtractionSchemaSpec
) -> dict[str, dict[str, int]]:
    """A choice detail's choices mapped onto at least two different steps (one step is not
    progress), and a true/false detail's "true" mapped onto one step."""
    choices = {
        f.key: {v.casefold(): v for v in f.enum_values or []}
        for f in spec.fields
        if f.type == "enum" and f.enum_values
    }
    choices.update({f.key: {"true": "true"} for f in spec.fields if f.type == "bool"})
    yes_no = {f.key for f in spec.fields if f.type == "bool"}
    out: dict[str, dict[str, int]] = {}
    rows = raw.get("fields")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("key") not in choices:
            continue
        key = str(row["key"])
        mapping: dict[str, int] = {}
        for item in row.get("choices") or []:
            if not isinstance(item, dict):
                continue
            choice = choices[key].get(str(item.get("choice", "")).strip().casefold())
            step = item.get("step")
            if choice is not None and isinstance(step, int) and step in names:
                mapping.setdefault(choice, step)
        if len(set(mapping.values())) >= (1 if key in yes_no else 2):
            out[key] = mapping
    return out


def _outcomes(
    raw: dict[str, Any], names: dict[int, str], outcomes: Sequence[BusinessOutcome]
) -> dict[str, int]:
    keys = {o.key for o in outcomes}
    out: dict[str, int] = {}
    rows = raw.get("outcomes")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key, step = row.get("key"), row.get("step")
        if key in keys and isinstance(step, int) and step in names:
            out.setdefault(str(key), step)
    return out


async def judge_call_steps(
    tenant_id: UUID,
    call_id: UUID,
    turns: Sequence[TranscriptTurn],
    spec: ExtractionSchemaSpec,
    *,
    goal: str | None = None,
    outcomes: Sequence[BusinessOutcome] = (),
) -> StepProgress | None:
    """The call's stored reading, else a new one stored now; None for a call with no script
    of steps, no words, or an account whose owner has not turned Pip on. `goal` is the
    campaign's goal (the script's own when None) and `outcomes` the agent's business
    outcomes, each mapped onto the step it means."""
    async with tenant_session(tenant_id) as session:
        known = await stored_progress(session, call_id)
        if known is not None:
            return known
        script = await holder_script(session, call_id)
        if script is None:
            return None
        if not await account_content_may_reach_models(session, tenant_id=tenant_id):
            return None
    lines = redacted_lines(turns)
    if not any(speaker == "caller" for speaker, _ in lines.values()):
        return None
    names, scenarios = step_names(script), step_scenarios(script)
    feature = ASSIST_FEATURE_STEP_PROGRESS

    def parse(raw: dict[str, Any]) -> StepProgress | None:
        if not isinstance(raw.get("steps"), list):
            return None
        return checked(
            raw, names=names, lines=lines, spec=spec, outcomes=outcomes, scenarios=scenarios
        )

    try:
        answer: JsonAnswer[StepProgress] = await ask_json(
            request_text(script, lines, spec, goal=goal, outcomes=outcomes),
            ASK,
            parse=parse,
            azure_format=_FORMAT,
            tenant_leg=google_assist_leg(),
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            timeout_s=TIMEOUT_S,
            health_leg="extraction",
            gemini_only=True,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        log.info(
            "call_step_progress_refused", extra={"call_id": str(call_id), "reason": refused.code}
        )
        return None
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
        await store_progress(session, call_id, answer.value)
    log.info(
        "call_step_progress_stored",
        extra={
            "call_id": str(call_id),
            "steps": len(answer.value.steps),
            "furthest": answer.value.furthest,
        },
    )
    return answer.value


__all__ = [
    "ASK",
    "checked",
    "judge_call_steps",
    "redacted_lines",
    "request_text",
    "step_names",
    "step_scenarios",
]
