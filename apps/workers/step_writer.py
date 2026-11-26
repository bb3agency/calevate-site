"""The words of one step of a call, written by one small request (DESIGN §3.2).

The structure is the plan's (`agents/script_plan`); this module only writes words. Each step
gets its own request of a few thousand characters: the step's plan entry, the facts and
source passages that step needs, the call language's register note, the opening line already
said (so the step never says it again), and the step before it. The answer is a strict JSON
object: an English instruction of one or two sentences, the actions one by one with what
shows each is done, and example turns in every call language (3 to 5 ordinary turns, a turn
for a confused caller, one for a caller stuck on the action, and on the first step a busy
one). Examples rather than rules: the in-call model copies what it is shown (03 §5).

Why one request per step rather than one whole-script pass: the whole-script requests were
32-72k characters against a rulebook that contradicted itself (01 §4-5), and models follow
long instruction lists less reliably and favour what comes first (03 §2, IFScale, Lost in the
Middle). Each step is checked as soon as it is written (`script_writer.checked`) and only a
failing step is written again, told exactly what failed.

What code decides is not in these prompts: the step's ways out, its number, its place, the
details it collects, the opening and the notices (hard rule 5) are the plan's and the
platform's. A rule code enforces is never also stated here (01 §5's conflicts).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from calevate_shared.business_frame import BUSINESS_FRAME
from calevate_shared.call_script import (
    MAX_PROCEDURE_STEPS,
    MAX_SCENARIO_QA,
    MAX_SCRIPT_OBJECTIONS,
    MAX_STEP_EXAMPLE_TURNS,
    PROCEDURE_STEP_MAX,
    PROCEDURE_WAIT_MAX,
    STAGE_DETAIL_MAX,
    STEP_EXAMPLE_MAX,
    Objection,
    ProcedureStep,
    ScenarioQa,
    StepExamples,
)
from calevate_shared.spoken_guard import english_problem, has_indic_letters, spoken_swapped
from calevate_shared.spoken_style import style_for

from apps.api.agents.script_plan import EXAMPLE_LIMITS, PlanStep, ScriptPlan
from apps.workers.script_assist import JsonAnswer, ScriptBrief, UnusableAnswerError, ask_json

if TYPE_CHECKING:
    from apps.workers.extraction import TenantModelLeg

#: Normal example turns a step must carry per language (DESIGN §2.3).
MIN_TURNS: Final = EXAMPLE_LIMITS.turns_min
#: One step's answer, in tokens: a ceiling, not a target (billing follows use).
STEP_MAX_TOKENS: Final = 3_000
#: The source passages one step's request carries, in characters.
PASSAGES_BUDGET: Final = 1_500
#: The owner's facts one request carries, in characters.
FACTS_BUDGET: Final = 600
#: The main task as one step's request carries it, in characters.
TASK_BUDGET: Final = 1_200
REGISTER_BUDGET: Final = 500

STEP_INSTRUCTION: Final = (
    f"You write one step of the phone call script of an AI voice agent for {BUSINESS_FRAME}. "
    "You are given the step's plan (what it does, what is true once it is done, the details "
    "it asks), the facts and source passages it may use, the call language and how people "
    "speak it on the phone, the opening line the agent already said, and the step before "
    "this one. Return JSON:\n"
    "instruction: one or two plain English sentences for the agent, under 300 characters: "
    "what it does in this step and when the step is done.\n"
    "procedure: when the step walks the person through doing something, the actions in "
    "order, one action each, as short English instructions; wait_for says what the person "
    "says or sees once that action is done, never a question the agent asks. Empty when "
    "there is nothing to do but talk.\n"
    "examples: for each call language given, written in that language as people really say "
    "it on the phone, in its own letters, with English product words as the owner writes "
    "them. turns: 3 to 5 different ways to say the agent's turn in this step; each gives "
    "ONE action or asks ONE question, then stops; in a step with actions every turn gives the "
    "first action only and asks nothing. confused: what the agent says when the "
    "person did not follow, the same action again in fewer, simpler words. stuck: one "
    "smaller hint when they cannot do it. busy: only when the plan says this is the first "
    "step, asking when would suit them instead; otherwise empty.\n"
    "qa: up to 3 questions a person may ask at this step, each answered in plain English "
    "only from the facts given.\n"
    "Every turn starts with its own point: the action, the answer or the question. The "
    "agent waits for the person to answer; a turn never asks them to say when they are done. "
    "Use only facts, figures and names the step is given, every screen, button and feature "
    "by the exact name the facts give. No brackets, symbols, lists or emoji. Return ONLY JSON."
)

OPENING_NOTE: Final = (
    "The opening line has already greeted the person, said who is calling and why, and asked "
    "whether now is a good time; this step goes on from their answer and says none of that "
    "again, nor asks again whether to go ahead: their yes to the opening is the go-ahead."
)
CLOSE_NOTE: Final = (
    "This is the last step: one short turn that says the one next thing, thanks them and "
    "says goodbye. confused and stuck stay empty."
)
SIDE_NOTE: Final = "Only some callers reach this step, through a way out: write it for them alone."


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_EXAMPLES: Final = _object(
    {
        "turns": {"type": "array", "items": {"type": "string"}},
        "confused": {"type": "string"},
        "stuck": {"type": "string"},
        "busy": {"type": "string"},
    }
)


def step_format(languages: Sequence[str]) -> dict[str, object]:
    """The step's answer under a strict schema, one examples object per call language."""
    schema = _object(
        {
            "instruction": {"type": "string"},
            "procedure": {
                "type": "array",
                "items": _object({"action": {"type": "string"}, "wait_for": {"type": "string"}}),
            },
            "examples": _object(dict.fromkeys(languages, _EXAMPLES)),
            "qa": {
                "type": "array",
                "items": _object({"question": {"type": "string"}, "answer": {"type": "string"}}),
            },
        }
    )
    return {
        "type": "json_schema",
        "json_schema": {"name": "calevate_script_step", "strict": True, "schema": schema},
    }


@dataclass(frozen=True, slots=True)
class StepWords:
    """One step's words as the writer returned them, read and shaped by code."""

    instruction: str
    procedure: tuple[ProcedureStep, ...] = ()
    examples: dict[str, StepExamples] = field(default_factory=dict)
    qa: tuple[ScenarioQa, ...] = ()


_WORD: Final = re.compile(r"[^\W_]{3,}", re.UNICODE)
_PARAGRAPH: Final = re.compile(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])")


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text)}


def passages(text: str, about: str, *, budget: int = PASSAGES_BUDGET) -> str:
    """The parts of `text` (the sources) that share the most words with `about` (the step),
    in their own order, within `budget` characters. Picked by word overlap rather than by a
    second model call: deterministic, free, and a step about logging in gets the passage
    that names the login screen."""
    wanted = _words(about)
    if not text.strip() or not wanted:
        return ""
    parts = [" ".join(p.split()) for p in _PARAGRAPH.split(text) if p.strip()]
    scored = sorted(
        ((len(_words(p) & wanted), i) for i, p in enumerate(parts)), key=lambda s: (-s[0], s[1])
    )
    chosen: list[int] = []
    used = 0
    for score, i in scored:
        if score == 0:
            break
        size = min(len(parts[i]), 600)
        if used + size > budget:
            continue
        chosen.append(i)
        used += size
    return "\n".join(f"- {parts[i][:600]}" for i in sorted(chosen))


def register_note(language: str) -> str:
    """How the call language is spoken, in a few sentences (the reviewed style file's own
    register text, never edited here)."""
    style = style_for(language)
    if style is None:
        return ""
    return f"{style.register_name}. {style.register}"[:REGISTER_BUDGET]


@dataclass(frozen=True, slots=True)
class StepAsk:
    """What one step's request is written from."""

    brief: ScriptBrief
    plan: ScriptPlan
    step: PlanStep
    languages: tuple[str, ...]
    opening: str
    main_task: str = ""
    sources: str = ""
    instruction: str = ""
    tone: str = ""
    #: The step as it stands, when it is written again.
    current: str = ""
    #: What failed the checks last time, exactly as the checks said it.
    problems: tuple[str, ...] = ()


def step_request(ask: StepAsk) -> str:
    """One step's request text."""
    brief, plan, step = ask.brief, ask.plan, ask.step
    first = plan.first is not None and step.key == plan.first.key
    close = plan.close is not None and step.key == plan.close.key
    about = " ".join((step.name, step.intent, step.outcome, *step.collect))
    lines = [
        f"Business: {brief.business_name or 'not given'}",
        *([f"Agent name: {brief.agent_name}"] if brief.agent_name else []),
        ("The agent places this call." if brief.places_calls() else "The agent answers this call."),
        f"Call languages: {', '.join(ask.languages)}",
    ]
    register = register_note(brief.language)
    if register:
        lines.append(f"How {brief.language} is spoken on these calls: {register}")
    if ask.tone:
        lines.append(f"Tone: {ask.tone}")
    if ask.main_task.strip():
        lines.append(f"What the call is for: {' '.join(ask.main_task.split())[:TASK_BUDGET]}")
    if ask.instruction.strip():
        lines.append(f"The owner asks: {' '.join(ask.instruction.split())[:TASK_BUDGET]}")
    facts = "; ".join(brief.facts)[:FACTS_BUDGET]
    if facts:
        lines.append(f"The owner's facts: {facts}")
    found = passages(ask.sources, about)
    if found:
        lines.append(f"From the business's sources:\n{found}")
    if ask.opening.strip():
        lines.append(f"The opening line, already said: {ask.opening.strip()}")
    previous = plan.before(step.key)
    if previous is not None and not first:
        lines.append(f'The step before: "{previous.name}": {previous.intent}')
    lines.append(f'THIS STEP: "{step.name}"')
    lines.append(f"What it does: {step.intent}")
    if step.outcome:
        lines.append(f"Done when: {step.outcome}")
    if step.collect:
        lines.append("Details it asks, one a turn: " + "; ".join(step.collect))
    if first:
        lines.append(f"This is the first step. {OPENING_NOTE}")
    if close:
        lines.append(CLOSE_NOTE)
    if step.side:
        lines.append(SIDE_NOTE)
    if ask.current.strip():
        lines.append(f"The step as it is now (JSON): {ask.current}")
    if ask.problems:
        lines.append(
            "Write the step again. The last answer failed these checks; fix each and keep "
            "everything else:\n" + "\n".join(f"- {p}" for p in ask.problems)
        )
    return "\n".join(lines)


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def parsed_step(
    raw: dict[str, Any], *, languages: Sequence[str], first: bool, close: bool, allowed: str = ""
) -> StepWords:
    """The answer read into a step's words, with the textbook words in every turn swapped for
    their spoken forms by code (`spoken_guard.spoken_swapped`). Refused with what is wrong
    when it has no English instruction or too few turns in a call language."""
    problems: list[str] = []
    instruction = _text(raw.get("instruction"), STAGE_DETAIL_MAX)
    if not instruction:
        problems.append("instruction: is empty; say what the agent does in this step")
    elif (wrong := english_problem("instruction", instruction)) is not None:
        problems.append(wrong)
    procedure = []
    for row in raw.get("procedure") or []:
        if not isinstance(row, dict):
            continue
        action = _text(row.get("action"), PROCEDURE_STEP_MAX)
        if not action:
            continue
        if has_indic_letters(action):
            problems.append("procedure: write each action in plain English")
            break
        procedure.append(
            ProcedureStep(action=action, wait_for=_text(row.get("wait_for"), PROCEDURE_WAIT_MAX))
        )
    examples: dict[str, StepExamples] = {}
    given = raw.get("examples") if isinstance(raw.get("examples"), dict) else {}
    for tag in languages:
        block = given.get(tag) if isinstance(given, dict) else None
        block = block if isinstance(block, dict) else {}

        def said(value: Any, *, tag: str = tag) -> str:
            return spoken_swapped(_text(value, STEP_EXAMPLE_MAX), tag, allowed=allowed)

        turns = [t for t in (said(v) for v in block.get("turns") or []) if t]
        wanted = 1 if close else MIN_TURNS
        if len(turns) < wanted:
            problems.append(
                f"examples.{tag}.turns: give {wanted} to {MAX_STEP_EXAMPLE_TURNS} different turns"
            )
        examples[tag] = StepExamples(
            turns=turns[:MAX_STEP_EXAMPLE_TURNS],
            confused="" if close else said(block.get("confused")),
            stuck="" if close else said(block.get("stuck")),
            busy=said(block.get("busy")) if first else "",
        )
    qa = [
        ScenarioQa(question=q, answer=a)
        for row in (raw.get("qa") or [])[:3]
        if isinstance(row, dict)
        and (q := _text(row.get("question"), 300))
        and (a := _text(row.get("answer"), 1000))
        and not has_indic_letters(a)
    ]
    if problems:
        raise UnusableAnswerError("; ".join(problems))
    return StepWords(
        instruction=instruction,
        procedure=tuple(procedure[:MAX_PROCEDURE_STEPS]),
        examples={tag: ex for tag, ex in examples.items() if not ex.is_empty},
        qa=tuple(qa[:MAX_SCENARIO_QA]),
    )


async def write_step(
    ask: StepAsk,
    *,
    tenant_leg: TenantModelLeg | None,
    quota_exhausted: bool,
    timeout_s: float,
    allowed: str = "",
) -> JsonAnswer[StepWords]:
    """One step's words, or the ladder's refusal (metered by the caller). A shape problem
    gets the ladder's one repair round; what the checks find is the caller's to send back."""
    plan, step = ask.plan, ask.step
    first = plan.first is not None and step.key == plan.first.key
    close = plan.close is not None and step.key == plan.close.key

    def parse(raw: dict[str, Any]) -> StepWords:
        return parsed_step(raw, languages=ask.languages, first=first, close=close, allowed=allowed)

    return await ask_json(
        step_request(ask),
        STEP_INSTRUCTION,
        parse=parse,
        azure_format=step_format(ask.languages),
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        max_tokens=STEP_MAX_TOKENS,
        temperature=0.6,
        timeout_s=timeout_s,
        repair_rounds=1,
        # A step is short enough for the standby's ceiling, so it may answer.
        standby_after_answer=True,
    )


# --- the parts outside the steps -------------------------------------------------------

FRAME_INSTRUCTION: Final = (
    f"You write the frame of the phone call script of an AI voice agent for {BUSINESS_FRAME}, "
    "in plain English, from the business, what the call is for and its steps. Return JSON: "
    "identity: one sentence on the agent's job in this business's own terms; goal: one "
    "sentence on what a good call reaches; business_line: under 200 characters on what the "
    "business is; outbound_purpose: for a call the agent places, one sentence on why it calls, "
    "else empty; ending: one sentence on how the agent closes the call; objections: 2 to 5 "
    "things this business's callers really say against it, each with how the agent answers, "
    "only from the facts given, offering to find out where the facts say nothing. Never an "
    "offer, discount or figure the facts do not give. Return ONLY JSON."
)

_FRAME_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "calevate_script_frame",
        "strict": True,
        "schema": _object(
            {
                "identity": {"type": "string"},
                "goal": {"type": "string"},
                "business_line": {"type": "string"},
                "outbound_purpose": {"type": "string"},
                "ending": {"type": "string"},
                "objections": {
                    "type": "array",
                    "items": _object(
                        {"objection": {"type": "string"}, "response": {"type": "string"}}
                    ),
                },
            }
        ),
    },
}


@dataclass(frozen=True, slots=True)
class Frame:
    identity: str = ""
    goal: str = ""
    business_line: str = ""
    outbound_purpose: str = ""
    ending: str = ""
    objections: tuple[Objection, ...] = ()

    def fields(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "goal": self.goal,
            "business_line": self.business_line,
            "outbound_purpose": self.outbound_purpose,
            "ending": self.ending,
            "objections": list(self.objections),
        }


def frame_request(brief: ScriptBrief, plan: ScriptPlan, main_task: str, sources: str) -> str:
    steps = "\n".join(f"{i}. {s.name}: {s.intent}" for i, s in enumerate(plan.steps, 1))
    facts = "; ".join(brief.facts)[:FACTS_BUDGET]
    found = passages(sources, f"{main_task} {steps}")
    return "\n".join(
        line
        for line in (
            f"Business: {brief.business_name or 'not given'}",
            "The agent places the calls." if brief.places_calls() else "The agent answers calls.",
            brief.fit.brief_text(),
            f"What the call is for: {' '.join(main_task.split())[:TASK_BUDGET]}"
            if main_task.strip()
            else "",
            f"The owner's facts: {facts}" if facts else "",
            f"From the business's sources:\n{found}" if found else "",
            f"The steps:\n{steps}",
        )
        if line
    )


def parsed_frame(raw: dict[str, Any], *, placed: bool) -> Frame:
    texts = {
        key: _text(raw.get(key), 200 if key == "business_line" else 1000)
        for key in ("identity", "goal", "business_line", "outbound_purpose", "ending")
    }
    wrong = [p for key, value in texts.items() if (p := english_problem(key, value))]
    if wrong:
        raise UnusableAnswerError("; ".join(wrong))
    objections = tuple(
        Objection(objection=o, response=r)
        for row in (raw.get("objections") or [])[:MAX_SCRIPT_OBJECTIONS]
        if isinstance(row, dict)
        and (o := _text(row.get("objection"), 300))
        and (r := _text(row.get("response"), 1000))
        and not has_indic_letters(r)
    )
    return Frame(
        identity=texts["identity"],
        goal=texts["goal"],
        business_line=texts["business_line"],
        outbound_purpose=texts["outbound_purpose"][:300] if placed else "",
        ending=texts["ending"],
        objections=objections[:5],
    )


async def write_frame(
    brief: ScriptBrief,
    plan: ScriptPlan,
    *,
    main_task: str,
    sources: str,
    tenant_leg: TenantModelLeg | None,
    quota_exhausted: bool,
    timeout_s: float,
) -> JsonAnswer[Frame]:
    placed = brief.places_calls()
    return await ask_json(
        frame_request(brief, plan, main_task, sources),
        FRAME_INSTRUCTION,
        parse=lambda raw: parsed_frame(raw, placed=placed),
        azure_format=_FRAME_FORMAT,
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        max_tokens=2_000,
        temperature=0.3,
        timeout_s=timeout_s,
    )


PARTS_INSTRUCTION: Final = (
    "You fix single lines of an AI phone agent's call script that failed a check. You are "
    "given each line with where it is and what failed. Return JSON: parts, one per line "
    "given, each with its path and the fixed text, changing only what the check named. A "
    "line in plain English stays in plain English; a line the agent says stays in the call "
    "language as people speak it. Return ONLY JSON."
)

_PARTS_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "calevate_script_parts",
        "strict": True,
        "schema": _object(
            {
                "parts": {
                    "type": "array",
                    "items": _object({"path": {"type": "string"}, "text": {"type": "string"}}),
                }
            }
        ),
    },
}


def parts_request(lines: Sequence[tuple[str, str, Sequence[str]]], language: str) -> str:
    out = [f"Call language: {language}"]
    for path, said, problems in lines:
        out.append(f"{path}: {said}\n  failed: {'; '.join(problems)}")
    return "\n".join(out)


def parsed_parts(raw: dict[str, Any], paths: Sequence[str]) -> dict[str, str]:
    wanted = set(paths)
    out = {
        str(row.get("path")): _text(row.get("text"), 1000)
        for row in raw.get("parts") or []
        if isinstance(row, dict) and row.get("path") in wanted and _text(row.get("text"), 1000)
    }
    if not out:
        raise UnusableAnswerError("parts: give each line given, fixed, under its path")
    return out


async def write_parts(
    lines: Sequence[tuple[str, str, Sequence[str]]],
    *,
    language: str,
    tenant_leg: TenantModelLeg | None,
    quota_exhausted: bool,
    timeout_s: float,
) -> JsonAnswer[dict[str, str]]:
    """Lines outside the steps (a quick fact's answer, an objection's, the goal) fixed one by
    one, in one small request."""
    paths = [path for path, _said, _problems in lines]
    return await ask_json(
        parts_request(lines, language),
        PARTS_INSTRUCTION,
        parse=lambda raw: parsed_parts(raw, paths),
        azure_format=_PARTS_FORMAT,
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        max_tokens=1_500,
        temperature=0.3,
        timeout_s=timeout_s,
    )


__all__ = [
    "CLOSE_NOTE",
    "FRAME_INSTRUCTION",
    "MIN_TURNS",
    "OPENING_NOTE",
    "PARTS_INSTRUCTION",
    "STEP_INSTRUCTION",
    "Frame",
    "StepAsk",
    "StepWords",
    "parsed_frame",
    "parsed_parts",
    "parsed_step",
    "passages",
    "register_note",
    "step_format",
    "step_request",
    "write_frame",
    "write_parts",
    "write_step",
]
