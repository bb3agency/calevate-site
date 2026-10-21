"""Draft a call script from a plain-language business description — the AI writing assist.

The founder's "draft/improve my script from a business description", asked of Pip since D-820
(`copilot/script_actions.py`). The owner answers five short questions; the brief adds the
business type, the calling direction, the call
language and its register, the details the agent collects and the knowledge titles
(`ScriptBrief`), and the assistant model returns a DRAFT of every script v2 section
(`calevate_shared.call_script`) — never applied to a live call, always the author's to edit
and then save through the ordinary staged path.

WHY IT LIVES IN `apps/workers` AND REUSES THE ASSIST LADDER. CLAUDE.md's Do-NOT rule keeps
model calls out of request handlers; the dashboard-AI assist (`crm/assist.py` +
`workers/extraction.run_assist`) is the established controlled path, so this is the same
shape rather than a second one: the SAME `assist_capability` selector decides who answers
(Azure preferred, Sarvam disclosed-fallback, else a refusal), the SAME `workers/chat.py`
makes the request and reads the `usage` block back for metering, the SAME `ASSIST_TIMEOUT_S`
bounds each leg. Only the PROMPT and the OUTPUT SHAPE differ, because the task differs —
drafting a script is not extracting a lead — and a different task is exactly when a second
request shape is warranted rather than a duplicated one. The two `httpx.post` bodies that
used to live here were the SECOND and THIRD copies of one request; `workers/chat.py` is the
one copy, and it is what the in-app copilot's streaming, tool-calling turn is built on.

WHAT IT IS ALLOWED TO SEE (D-127 G-2). Its input is a TENANT-AUTHORED business description
— the client's own words about their own business — which is the "tenant-authored config"
class `AzureOpenAIExtractor` already serves, not call-transcript PII. There is no transcript
here to redact; the redaction guard that governs the re-summarise path protects a different
input. The description is still never logged (hard rule 6): it is business content.

Metering and quota are NOT decided here — `billing/ai_quota` owns both, joined by
`workers/script_proposal.py` in SUBJECT → GATE → RUN → METER order, exactly
as `crm/resummarise.second_reading` does for re-summarise. This module returns the draft and, for
an Azure answer Azure counted, its `usage`; it charges nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Final

import httpx
from calevate_shared.call_script import (
    END_OF_CALL,
    MAX_EXAMPLE_TURNS,
    MAX_PRONUNCIATIONS,
    MAX_SAMPLE_PHRASES,
    MAX_SCRIPT_FAQS,
    MAX_SCRIPT_OBJECTIONS,
    MAX_SCRIPT_STAGES,
    SCRIPT_SCHEMA_VERSION,
    STAGE_DETAIL_MAX,
    CallScript,
    ConversationStage,
    ExampleLine,
    FaqEntry,
    Objection,
    Pronunciation,
    SpeakingStyle,
    StageBranch,
)
from calevate_shared.engine import (
    SARVAM_DEFAULT_LLM,
    azure_openai_base_url,
    google_openai_compat_base_url,
    keeps_default_temperature,
)
from calevate_shared.spoken_guard import english_problem, generation_guidance, textbook_problem
from pydantic import ValidationError

from apps.api.agents.call_rules import OPENING_LINE_RULE, said_line_problem, writer_rules
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.tenancy.business_copy import provider_problem
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    ASSIST_TIMEOUT_S,
    AZURE_PROVIDER,
    GOOGLE_PROVIDER,
    PROVIDER_UNAVAILABLE_REASON,
    SARVAM_CHAT_URL,
    AssistCapability,
    AssistDeadlineError,
    PaidTurn,
    TenantModelLeg,
    _first_json_object,
    assist_capability,
    assist_unavailable,
    azure_credentials,
    ladder_deadlines,
    refused_after_spend,
    request_timeout,
    time_left,
)

log = get_logger(__name__)

#: The instruction that turns the owner's answers into a v2 call script (first live call
#: review, 10 Oct 2026: founder decision 3). Instructions in English; only the words the
#: agent SAYS (opening, sample phrases, example call) are in the call's language, spoken and
#: code-mixed, because the in-call model follows English instructions best and the caller
#: hears only the spoken lines. A module constant so `tests/script_assist_prompt_test.py`
#: can pin its rules without a credential.
_SYSTEM_INSTRUCTION = (
    "You write call scripts for AI phone agents of small Indian businesses. You are given "
    "the business type, whether the agent answers or places calls, the call language and "
    "its spoken register, the details the agent must collect, the titles of the business's "
    "knowledge documents, and the owner's own short answers. Fill EVERY section.\n"
    "Write instructions (business_line, identity, goal, outbound_purpose, tone, "
    "address_form, stage instructions and exit conditions, objection responses, ending) in "
    "plain English letters, never in the call language's script, even when the call is in "
    "Telugu or Hindi. identity is one plain-English sentence describing the agent's job, "
    'for example "Answers calls for the shop: products, prices, orders and delivery", '
    "never just the business name. Write the words the agent will SAY (opening_line, "
    "sounds_like, sample_phrases, example_exchange) in the call language as people really "
    "speak it on the phone, in the script that language is normally written in, with the "
    "English words they use kept in English letters (order, delivery, booking, price), "
    "never formal written language. Follow the spoken-style guide in the brief exactly: use "
    "the spoken word and never its formal form, use its tags and fillers lightly, say "
    "prices, quantities and times as its number rules say, and copy how its example "
    "exchanges sound, never their facts. Keep every spoken line to one short sentence with "
    'a comma where you breathe and a "?" on every question; no dashes, slashes, brackets, '
    "ellipses or dotted abbreviations.\n"
    f"Rules, the same ones the agent's tests check: {writer_rules()} Facts live in the "
    "knowledge base, which the agent searches. "
    "quick_facts only restates facts the owner wrote. The example_exchange shows style "
    "only and contains no fact. Do not write anything about being an AI, about recording, "
    "about call backs or transfers, or about do-not-call requests: the platform adds those "
    f"rules itself and knows what this account can do. {OPENING_LINE_RULE} For an agent that "
    "places calls, "
    "outbound_purpose is one sentence on why we are calling, and a stage confirms it is a "
    "good time and that this is the right person ({{lead_name}} is the merge field for the "
    "lead's name); for an agent that only answers calls leave outbound_purpose empty. "
    "Stages are 3 to 6, each with a short name, an English instruction, exit_when, and "
    "sounds_like: one short line in the call language showing how that stage sounds. "
    "2 to 5 objections the business really meets. 3 to 6 sample "
    "phrases. pronunciations only for names a voice might misread. code_mix is light, "
    "natural or heavy. business_line is one line under 200 characters on what the business "
    "is.\n"
    "Return ONLY JSON matching the schema."
)

#: Converting a hand-written prompt into sections (founder, 10 Oct 2026): a proposal the
#: owner reviews, never a replacement. Keeping the owner's own sentences is what lets
#: `call_script.unplaced_lines` show anything that did not make it across.
CONVERT_INSTRUCTION = (
    "You convert a hand-written prompt for an AI phone agent into the sections of a call "
    "script. Keep the owner's own sentences word for word wherever they fit; do not "
    "summarise, drop or add facts. Put who the agent is in identity, the purpose in goal, "
    "the greeting in opening_line, each step of the call in stages (at most 12, in call "
    "order), push-back handling in objections, facts in quick_facts and the close in "
    "ending. Leave a field empty when the prompt says nothing for it. Do not write about "
    "being an AI, recording, call backs, transfers or do-not-call: the platform adds those. "
    "The words the agent will SAY (opening_line, sounds_like, sample_phrases, "
    "example_exchange) follow the spoken-style guide in the brief: where the owner's line "
    "uses a formal word the guide lists, use the spoken word instead and keep the meaning; "
    "English words stay in English letters; numbers and punctuation as the guide says. "
    "Return ONLY JSON matching the schema."
)

#: Making one change the owner asked for to the current script.
EDIT_INSTRUCTION = (
    "You edit the call script of an AI phone agent. You are given the current script as "
    "JSON and one change the owner wants. Return the WHOLE script as JSON in exactly the same "
    "shape, with only that change made: keep every other field, every section and every "
    "section id as it is, and give any new section a new short lowercase id. The steps of "
    "the call are the `stages` list; leave the `steps` list exactly as it is. A field the "
    "change does not need stays exactly as it is, and an EMPTY field stays empty: do not fill "
    "in parts the owner did not ask about. Instructions "
    "(business_line, identity, goal, outbound_purpose, tone, address_form, stage "
    "instructions, objection responses, ending) stay in plain English letters, never in the "
    "call language's script; words the agent says stay in the call language, spoken, with "
    "the English words people use, following the spoken-style guide in the brief (spoken "
    "words, never their formal forms; its number and punctuation rules). What you write "
    f"keeps the rules the agent's tests check: {writer_rules()} {OPENING_LINE_RULE} Do not "
    "write about being an AI, recording, call backs, transfers or do-not-call. Return ONLY "
    "JSON."
)

Parser = Callable[[dict[str, Any]], "CallScript | None"]


def _stages_where_they_belong(fields: dict[str, Any], current: CallScript) -> dict[str, Any]:
    """Move call steps the model wrote into the legacy `steps` list back into `stages`.

    A script has both: `steps` (schema 1, items carrying only an `instruction`) and
    `stages` (the steps an owner sees, each with an `id`). Asked to "keep every step", the
    model put the stages into `steps`, and every one failed as an unknown field (production,
    18 Oct 2026: 60 `extra_forbidden` errors, the same after the repair). An item with an
    `id` can only be a stage, so it is moved; the legacy list is kept as it was.
    """
    steps = fields.get("steps")
    if not isinstance(steps, list) or not steps:
        return fields
    if not all(isinstance(item, dict) and "id" in item for item in steps):
        return fields
    moved = dict(fields)
    if "stages" not in moved:
        moved["stages"] = steps
    moved["steps"] = [step.model_dump() for step in current.steps]
    return moved


def _instruction_fields(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of every field that instructs the in-call model and is never heard.

    A step in "say" mode is said as written, so its instruction is a spoken line. A step's
    name, an objection's caller side, the facts and the legacy `steps` are not here: the
    first two are the caller's words or the owner's label, and the AI writes none of the rest
    as instructions."""
    fields = [
        ("business_line", script.business_line),
        ("identity", script.identity),
        ("goal", script.goal),
        ("outbound_purpose", script.outbound_purpose),
        ("style.tone", script.style.tone),
        ("style.address_form", script.style.address_form),
        ("ending", script.ending),
    ]
    fields += [(f"objections.{i}.response", o.response) for i, o in enumerate(script.objections)]
    for i, stage in enumerate(script.stages):
        if stage.mode == "guide":
            fields.append((f"stages.{i}.instruction", stage.instruction))
        fields += [(f"stages.{i}.branches.{j}.when", b.when) for j, b in enumerate(stage.branches)]
    return fields


def _spoken_fields(script: CallScript) -> list[tuple[str, str]]:
    """(path, text) of every line the agent says, or that shows how a caller sounds."""
    fields = [("opening_line", script.opening_line)]
    for i, stage in enumerate(script.stages):
        fields.append((f"stages.{i}.sounds_like", stage.sounds_like))
        if stage.mode == "say":
            fields.append((f"stages.{i}.instruction", stage.instruction))
    fields += [(f"style.sample_phrases.{i}", p) for i, p in enumerate(script.style.sample_phrases)]
    fields += [
        (f"example_exchange.{i}.text", e.text) for i, e in enumerate(script.example_exchange)
    ]
    return fields


def language_problems(
    script: CallScript,
    language: str | None,
    *,
    before: CallScript | None = None,
    allowed: str = "",
    instructions: bool = True,
) -> list[str]:
    """What the model must fix in a script it wrote (D-831): an instruction in an Indic
    script, and a spoken line with a textbook word (`spoken_guard`), a provider's name
    (`business_copy.provider_problem`, D-679: callers hear these lines) or a break of the call
    rules the practice tests check (`call_rules.said_line_problem`, D-849).

    Only the model's own writing is judged: with `before` (an edit), a field whose text the
    script already held is the owner's and is skipped, and a textbook word that appears in
    `allowed` (the owner's own words the script was written from) is theirs. `instructions`
    False skips the English rule, for a conversion that keeps the owner's sentences."""
    kept = (
        {text for _, text in (*_instruction_fields(before), *_spoken_fields(before))}
        if before is not None
        else set()
    )
    problems: list[str] = []
    if instructions:
        problems += [
            problem
            for path, text in _instruction_fields(script)
            if text not in kept and (problem := english_problem(path, text))
        ]
    callers = {
        f"example_exchange.{i}.text"
        for i, line in enumerate(script.example_exchange)
        if line.speaker == "caller"
    }
    for path, text in _spoken_fields(script):
        if text in kept:
            continue
        problems += [
            problem
            for problem in (
                textbook_problem(path, text, language, allowed=allowed),
                provider_problem(path, text, allowed=allowed),
                # The call rules the practice tests hold the agent to (D-849); a caller's
                # example line is not the agent's to keep, and the owner's own line is theirs.
                None
                if path in callers or (allowed and text.strip() in allowed)
                else said_line_problem(path, text, opening=path == "opening_line"),
            )
            if problem
        ]
    return problems


def drafted_script(
    raw: dict[str, Any], *, language: str | None, allowed: str = "", instructions: bool = True
) -> CallScript:
    """A whole draft (or a conversion) as `_script_from_model_json` reads it, refused with
    the language problems for the one repair when it breaks the language rules."""
    script = _script_from_model_json(raw)
    problems = language_problems(script, language, allowed=allowed, instructions=instructions)
    if problems:
        log.warning("script_assist_language_unusable", extra={"count": len(problems)})
        raise UnusableAnswerError("; ".join(problems[:12]))
    return script


def edited_script(
    raw: dict[str, Any],
    current: CallScript,
    *,
    language: str | None = None,
    allowed: str = "",
) -> CallScript | None:
    """The model's edited script, validated like any save; None when it is not a valid
    script (the edit is then reported as no draft rather than half applied). A field the
    model changed must keep the language rules (`language_problems`); what the owner already
    had is never judged."""
    fields = _stages_where_they_belong(
        {k: v for k, v in raw.items() if k in CallScript.model_fields}, current
    )
    try:
        edited = CallScript.model_validate({**current.model_dump(), **fields})
    except ValidationError as invalid:
        errors = invalid.errors(include_input=False, include_url=False)
        # Where and which rule, never the value: the value is the client's script.
        problems = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in errors[:8]
        ]
        # One string, not a list: the log formatter reduces a list to "[N items]", which hid
        # exactly what an operator needs here. Paths and rule types only.
        where = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])} {error['type']}"
            for error in errors[:8]
        )
        log.warning("script_assist_edit_unusable", extra={"where": where, "count": len(errors)})
        raise UnusableAnswerError("; ".join(problems)) from invalid
    problems = language_problems(edited, language, before=current, allowed=allowed)
    if problems:
        log.warning("script_assist_language_unusable", extra={"count": len(problems)})
        raise UnusableAnswerError("; ".join(problems[:12]))
    return edited.model_copy(update={"raw_override": None, "schema_version": 2})


#: The ceiling on ONE draft answer, in tokens: a safety valve on a runaway generation, which
#: surfaces as `finish_reason == "length"` and is reported as "no draft" rather than parsed
#: (a truncation must not read as a short answer). A full v2 draft with a code-mixed example
#: call fits well under it.
_DRAFT_MAX_TOKENS = 4096

_STR: Final[dict[str, object]] = {"type": "string"}


def _array_of(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


_DRAFT_PROPERTIES: Final[dict[str, object]] = {
    "business_line": _STR,
    "identity": _STR,
    "goal": _STR,
    "outbound_purpose": _STR,
    "opening_line": _STR,
    "tone": _STR,
    "address_form": _STR,
    "code_mix": {"type": "string", "enum": ["light", "natural", "heavy"]},
    "sample_phrases": {"type": "array", "items": _STR},
    "pronunciations": _array_of({"word": _STR, "say_as": _STR}),
    "stages": _array_of(
        {"name": _STR, "instruction": _STR, "sounds_like": _STR, "exit_when": _STR}
    ),
    "objections": _array_of({"objection": _STR, "response": _STR}),
    "ending": _STR,
    "quick_facts": _array_of({"question": _STR, "answer": _STR}),
    "example_exchange": _array_of(
        {"speaker": {"type": "string", "enum": ["caller", "agent"]}, "text": _STR}
    ),
}

#: The strict JSON Schema for a v2 draft, so Azure's Structured Outputs guarantees the shape.
#: Sarvam gets `json_object` and `_first_json_object` as the belt.
_DRAFT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": _DRAFT_PROPERTIES,
    "required": list(_DRAFT_PROPERTIES),
    "additionalProperties": False,
}

#: The five short questions Pip asks the owner before drafting a whole script. Keys are
#: `agent_script_suggest`'s `answers` (`copilot/script_actions.py`).
OWNER_QUESTIONS: Final[dict[str, str]] = {
    "what_you_offer": "What do you sell or do?",
    "customers": "Who calls you, or who will the agent call?",
    "good_outcome": "What should a good call end with?",
    "common_questions": "What do callers ask most often?",
    "never_say": "Anything the agent must never say or promise?",
}

_DIRECTION_SENTENCES: Final[dict[str, str]] = {
    "inbound": "The agent answers calls.",
    "outbound": "The agent places calls to leads.",
    "both": "The agent answers calls and places calls to leads.",
}


@dataclass(frozen=True, slots=True)
class ScriptBrief:
    """Everything the draft is written from. Tenant-authored configuration only: no
    transcript and no caller data (D-127 G-2), and never logged (hard rule 6)."""

    description: str = ""
    business_name: str = ""
    business_type: str = "custom"
    direction: str = "inbound"
    language: str = "te-IN"
    register: str = ""
    collect: tuple[str, ...] = ()
    knowledge_titles: tuple[str, ...] = ()
    answers: tuple[tuple[str, str], ...] = ()

    def user_message(self) -> str:
        lines = [
            f"Business name: {self.business_name or 'not given'}",
            f"Business type: {self.business_type}",
            _DIRECTION_SENTENCES.get(self.direction, _DIRECTION_SENTENCES["inbound"]),
            f"Call language: {self.language}",
        ]
        # The spoken-style guide for the call language (D-744): every swap, the tags and
        # fillers, the number and punctuation rules and example exchanges, so draft,
        # convert and edit all write the founder's reviewed style.
        guide = generation_guidance(self.language, self.business_type)
        if guide:
            lines.append(f"Spoken-style guide for {self.language}:\n{guide}")
        elif self.register:
            lines.append(f"Spoken register: {self.register}")
        if self.collect:
            lines.append("Details to collect: " + "; ".join(self.collect))
        if self.knowledge_titles:
            lines.append("Knowledge documents: " + "; ".join(self.knowledge_titles))
        for key, answer in self.answers:
            question = OWNER_QUESTIONS.get(key)
            if question and answer.strip():
                lines.append(f"{question} {answer.strip()}")
        if self.description.strip():
            lines.append(f"In the owner's words: {self.description.strip()}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ScriptDraft:
    """One AI-drafted script, what it cost, and who wrote it.

    `script` is a structured `CallScript` the builder can load directly — opening line,
    steps and FAQ, in raw pydantic-validated form so a malformed model answer is caught here
    rather than in the editor. `usage`, `model` and `earlier` are `JsonAnswer`'s.
    `capability` carries the fallback disclosure the response and screen must show (G-6).
    """

    script: CallScript
    capability: AssistCapability
    usage: TokenUsage | None = None
    #: The model that wrote it (`JsonAnswer.model`), for the meter.
    model: str | None = None
    earlier: tuple[PaidTurn, ...] = ()


@dataclass(frozen=True, slots=True)
class _RawDraft:
    """The model's JSON, normalised into a `CallScript`, plus usage. Internal to this file.

    `script` is None when the model ANSWERED and the answer was unusable (truncated, or no
    JSON in it): no draft, but a billed turn whose `usage` must still reach the meter.
    """

    script: CallScript | None
    usage: TokenUsage | None = field(default=None)


def _text(raw: dict[str, Any], key: str, limit: int) -> str:
    value = raw.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


def _rows(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _script_from_model_json(raw: dict[str, Any]) -> CallScript:
    """The model's JSON as a validated v2 `CallScript`.

    Tolerant: a missing or malformed piece comes back empty for the author to fill, and
    every value that does arrive is cut to the builder's own limits and validated by the
    same `CallScript` the builder saves, so a draft never carries what the editor would
    refuse. A drafted example is marked as needing a native speaker's review.
    """
    rows = [r for r in _rows(raw, "stages") if _text(r, "instruction", STAGE_DETAIL_MAX)]
    rows = rows[:MAX_SCRIPT_STAGES]
    stages: list[ConversationStage] = []
    for i, row in enumerate(rows, 1):
        # Instruction and "sounds like" share one 600-character step detail.
        sounds_like = _text(row, "sounds_like", 200)
        room = STAGE_DETAIL_MAX - (len(sounds_like) + 20 if sounds_like else 0)
        exit_when = _text(row, "exit_when", 300)
        target = f"s{i + 1}" if i < len(rows) else END_OF_CALL
        stages.append(
            ConversationStage(
                id=f"s{i}",
                name=_text(row, "name", 80) or f"Section {i}",
                instruction=_text(row, "instruction", room),
                sounds_like=sounds_like,
                branches=[StageBranch(when=exit_when, target=target)] if exit_when else [],
            )
        )
    objections = [
        Objection(objection=_text(row, "objection", 300), response=_text(row, "response", 1000))
        for row in _rows(raw, "objections")[:MAX_SCRIPT_OBJECTIONS]
        if _text(row, "objection", 300) and _text(row, "response", 1000)
    ]
    facts = [
        FaqEntry(question=_text(row, "question", 500), answer=_text(row, "answer", 2000))
        for row in _rows(raw, "quick_facts")[:MAX_SCRIPT_FAQS]
        if _text(row, "question", 500) and _text(row, "answer", 2000)
    ]
    example = [
        ExampleLine(speaker=row["speaker"], text=_text(row, "text", 500))
        for row in _rows(raw, "example_exchange")[:MAX_EXAMPLE_TURNS]
        if row.get("speaker") in ("caller", "agent") and _text(row, "text", 500)
    ]
    phrases_raw = raw.get("sample_phrases")
    phrases = (
        [p for p in phrases_raw if isinstance(p, str) and p.strip()][:MAX_SAMPLE_PHRASES]
        if isinstance(phrases_raw, list)
        else []
    )
    pronunciations = [
        Pronunciation(word=_text(row, "word", 80), say_as=_text(row, "say_as", 120))
        for row in _rows(raw, "pronunciations")[:MAX_PRONUNCIATIONS]
        if _text(row, "word", 80) and _text(row, "say_as", 120)
    ]
    code_mix = raw.get("code_mix")
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        business_line=_text(raw, "business_line", 200),
        identity=_text(raw, "identity", 1000),
        goal=_text(raw, "goal", 1000),
        outbound_purpose=_text(raw, "outbound_purpose", 300),
        opening_line=_text(raw, "opening_line", 1000),
        style=SpeakingStyle(
            tone=_text(raw, "tone", 300),
            address_form=_text(raw, "address_form", 200),
            code_mix=code_mix if code_mix in ("light", "natural", "heavy") else "natural",
            sample_phrases=phrases,
            pronunciations=pronunciations,
        ),
        stages=stages,
        objections=objections,
        ending=_text(raw, "ending", 1000),
        faqs=facts,
        example_exchange=example,
        example_needs_review=bool(example),
    )


@dataclass(frozen=True, slots=True)
class _RawJson:
    """One leg's answer: the first JSON object in it (None when there was none), and what
    Azure counted. Internal to this file."""

    data: dict[str, Any] | None
    usage: TokenUsage | None = None


def _strict(schema_name: str, schema: dict[str, object]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
    }


async def _json_via_azure(
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
) -> _RawJson | None:
    """Ask Azure OpenAI for one JSON answer, or None if it holds no credential or did not
    answer.

    The request goes through `workers/chat.py`, the ONE chat client — the v1 surface built
    by the ONE endpoint builder, a static bearer key, Structured Outputs with a degrade to
    `json_object`.
    """
    credentials = azure_credentials()
    if credentials is None:
        return None
    resource, api_key, deployment = credentials
    leg = chat.ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )
    return await _json_via_leg(
        leg,
        AZURE_PROVIDER,
        description,
        instruction,
        response_format,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
        deadline=deadline,
        health_leg=health_leg,
    )


async def _json_via_google(
    model: str,
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
) -> _RawJson | None:
    """The account's own Gemini model on D-478's leg, or None without the key or an answer.

    Google's OpenAI-compatible surface takes a strict `json_schema` response format: its
    structured-output example passes a schema class through the client's `parse` helper
    (ai.google.dev/gemini-api/docs/openai, updated 13 Oct 2026, read 14 Oct 2026). A 400 on
    it degrades to `json_object` exactly as Azure's does.
    """
    api_key = get_settings().gemini_api_key
    if not api_key:
        return None
    leg = chat.ChatLeg(
        url=f"{google_openai_compat_base_url()}/chat/completions",
        api_key=api_key,
        wire_model=model,
        dialect="google",
    )
    return await _json_via_leg(
        leg,
        GOOGLE_PROVIDER,
        description,
        instruction,
        response_format,
        max_tokens=max_tokens,
        # Gemini 3: none sent, Google warns a lowered temperature loops (D-786).
        temperature=None if keeps_default_temperature(model) else temperature,
        timeout_s=timeout_s,
        deadline=deadline,
        health_leg=health_leg,
    )


async def _json_via_leg(
    leg: chat.ChatLeg,
    provider: str,
    description: str,
    instruction: str,
    response_format: dict[str, object],
    *,
    max_tokens: int,
    temperature: float | None,
    timeout_s: float,
    deadline: float | None = None,
    health_leg: provider_health.AiLeg = "script",
) -> _RawJson | None:
    """One JSON answer from a paid leg (Azure or the account's Gemini), or None when it
    refused, could not be reached, or the assist's time budget left no room to ask."""
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": description},
    ]

    async def ask(fmt: Mapping[str, Any]) -> chat.ChatOutcome:
        return await chat.complete(
            leg,
            messages,
            timeout_s=request_timeout(timeout_s, deadline),
            temperature=temperature,
            response_format=fmt,
            max_tokens=max_tokens,
        )

    try:
        try:
            outcome = await ask(response_format)
        except httpx.HTTPStatusError as refusal:
            if refusal.response.status_code != 400 or response_format.get("type") != "json_schema":
                log.warning(
                    "script_assist_leg_failed",
                    extra={
                        "provider": provider,
                        "model": leg.wire_model,
                        "status": refusal.response.status_code,
                    },
                )
                await provider_health.note_failure(
                    health_leg, provider, refusal, model=leg.wire_model
                )
                return None
            # The leg refused Structured Outputs (documented, unobserved here — see
            # `AzureOpenAIExtractor`). Degrade ONCE to plain json_object; the belt is
            # `_first_json_object`. No body logged (hard rule 6): it quotes the request.
            log.warning(
                "script_assist_json_schema_unsupported",
                extra={"provider": provider, "model": leg.wire_model},
            )
            outcome = await ask({"type": "json_object"})
    except AssistDeadlineError:
        log.warning("script_assist_out_of_time", extra={"provider": provider})
        return None
    except httpx.HTTPError as failure:
        # A transport failure is the same OUTCOME as a refusal for this caller: the
        # selector is re-asked with `provider_unavailable=True`.
        log.warning(
            "script_assist_leg_unreachable",
            extra={
                "provider": provider,
                "model": leg.wire_model,
                **provider_health.failure_fields(failure),
            },
        )
        await provider_health.note_failure(health_leg, provider, failure, model=leg.wire_model)
        return None
    await provider_health.note_success(health_leg, provider)
    if outcome.finish_reason == "length":
        # The `max_tokens` valve fired. The JSON was cut off mid-generation, so parsing it
        # could yield a balanced PREFIX that reads as a short answer. "No answer" is the
        # honest result, carrying the billed tokens to the meter.
        log.warning("script_assist_draft_truncated", extra={"provider": provider})
        return _RawJson(data=None, usage=outcome.usage)
    return _RawJson(data=_first_json_object(outcome.content) or None, usage=outcome.usage)


async def _json_via_sarvam(
    description: str,
    instruction: str,
    *,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    deadline: float | None = None,
) -> _RawJson | None:
    """The disclosed fallback: Sarvam's OpenAI-compatible chat, `json_object` + the belt.

    Its usage travels with the answer so `meter_assist`'s standby branch records it at the
    attested Sarvam price (absorbed). None when it refused or could not be reached.
    """
    settings = get_settings()
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        return None
    try:
        outcome = await chat.complete(
            chat.ChatLeg(
                url=SARVAM_CHAT_URL,
                api_key=settings.sarvam_api_key,
                wire_model=SARVAM_DEFAULT_LLM,
                dialect="sarvam",
            ),
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": description},
            ],
            timeout_s=request_timeout(timeout_s, deadline),
            temperature=temperature,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
    except AssistDeadlineError:
        log.warning("script_assist_out_of_time", extra={"provider": "sarvam"})
        return None
    except httpx.HTTPStatusError as refusal:
        log.warning("script_assist_sarvam_failed", extra={"status": refusal.response.status_code})
        return None
    except httpx.HTTPError as failure:
        log.warning(
            "script_assist_sarvam_unreachable", extra=provider_health.failure_fields(failure)
        )
        return None
    if outcome.finish_reason == "length":
        log.warning("script_assist_draft_truncated", extra={"provider": "sarvam"})
        return _RawJson(data=None, usage=outcome.usage)
    return _RawJson(data=_first_json_object(outcome.content) or None, usage=outcome.usage)


def _draft_format(*, edit: bool) -> dict[str, object]:
    # An edit returns the whole current script, whose shape the strict draft schema does
    # not describe, so it asks for plain JSON and is validated by `CallScript` instead.
    if not edit:
        return _strict("calevate_script_draft", _DRAFT_SCHEMA)
    return {"type": "json_object"}


async def _draft_via_azure(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """One Azure draft, or None if Azure holds no credential or did not answer."""
    raw = await _json_via_azure(description, instruction, _draft_format(edit=parse is not None))
    if raw is None:
        return None
    if raw.data is None:
        return _RawDraft(script=None, usage=raw.usage)
    return _RawDraft(script=(parse or _script_from_model_json)(raw.data), usage=raw.usage)


async def _draft_via_sarvam(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """One Sarvam draft, or None."""
    raw = await _json_via_sarvam(description, instruction)
    if raw is None or raw.data is None:
        return None
    return _RawDraft(script=(parse or _script_from_model_json)(raw.data))


@dataclass(frozen=True, slots=True)
class JsonAnswer[T]:
    """One answer from the dashboard AI ladder, parsed; what it cost; who answered.

    `usage` is what the leg that WROTE the answer counted (both attempts when a repair was
    needed); `model` is that leg's model, which the meter prices it by
    (`crm/assist.meter_assist(model=)`) and the test loop records beside each verdict.
    `earlier` is a paid leg that answered unusably before the standby answered, metered
    separately at its own model (`crm/assist.meter_earlier`). `capability` carries the
    fallback disclosure the screen must show (G-6)."""

    value: T
    capability: AssistCapability
    usage: TokenUsage | None = None
    model: str | None = None
    earlier: tuple[PaidTurn, ...] = ()


#: What the paid leg is told when its answer broke the caller's rules, before it is asked once
#: more. `problems` names fields and rules only, never the answer's text.
REPAIR_NOTE: Final = (
    "Your previous answer could not be used because of these problems: {problems}. "
    "Return the whole JSON again with exactly these fixed and nothing else changed."
)


#: The refusal code when the model answered but the answer still broke the rules after one
#: repair. Distinct from `provider_unavailable`, whose words ("no assistant answered") would be
#: untrue here.
ANSWER_UNUSABLE_CODE: Final = "assist_answer_unusable"


def _answer_unusable() -> ProblemError:
    return ProblemError.business_rule(
        ANSWER_UNUSABLE_CODE,
        "AI help could not make that change cleanly this time.",
        remediation="Try describing the change another way, or edit that part yourself.",
    )


class UnusableAnswerError(ValueError):
    """A parse refused the model's answer for reasons the model can be told and can fix."""

    def __init__(self, problems: str) -> None:
        super().__init__(problems)
        self.problems = problems


def _parsed_with_problems[T](
    parse: Callable[[dict[str, Any]], T | None], data: dict[str, Any] | None
) -> tuple[T | None, str | None]:
    """`_parsed`, plus the problems to send back when the parse said what was wrong."""
    if data is None:
        return None, None
    try:
        return parse(data), None
    except UnusableAnswerError as unusable:
        return None, unusable.problems
    except (TypeError, ValueError, KeyError, AttributeError) as failure:
        log.warning("script_assist_answer_unusable", extra={"error": type(failure).__name__})
        return None, None


def _usage_sum(first: TokenUsage | None, second: TokenUsage | None) -> TokenUsage | None:
    """Both answered attempts of one request as one metered quantity (`chat.sum_usage`): the
    reported part, marked incomplete when one attempt sent no usage block."""
    return chat.sum_usage([first, second])


def _parsed[T](
    parse: Callable[[dict[str, Any]], T | None], data: dict[str, Any] | None
) -> T | None:
    """The caller's parse of one model answer, or None. A model's JSON is untrusted input:
    a value of the wrong type (a list where a string was asked for) must read as an
    unusable answer, never escape as a 500."""
    if data is None:
        return None
    try:
        return parse(data)
    except (TypeError, ValueError, KeyError, AttributeError) as failure:
        log.warning("script_assist_answer_unusable", extra={"error": type(failure).__name__})
        return None


async def ask_json[T](
    description: str,
    instruction: str,
    *,
    parse: Callable[[dict[str, Any]], T | None],
    azure_format: dict[str, object] | None = None,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    max_tokens: int = _DRAFT_MAX_TOKENS,
    temperature: float = 0.4,
    timeout_s: float = ASSIST_TIMEOUT_S,
    health_leg: provider_health.AiLeg = "script",
    gemini_only: bool = False,
) -> JsonAnswer[T]:
    """THE dashboard AI ladder for a JSON answer: the paid leg `assist_capability` picks (the
    account's own Gemini model when it serves the dashboard, else Azure), the disclosed
    Sarvam leg if that cannot or does not answer, a refusal only when nothing can
    (`run_assist`'s rule).

    `gemini_only` is the ladder with one rung: the Gemini leg `tenant_leg` names, with the
    one repair, and a refusal where the ladder would have gone to Azure or the Sarvam
    standby. For a job that reads callers' redacted questions and must not reach a vendor
    whose terms permit training on inputs (Sarvam ToS s.17.5, D-827).

    `parse` turns the model's JSON into the caller's value and returns None for an unusable
    answer, which counts as no answer: the next leg gets its chance. `azure_format` is the
    `response_format` the paid leg is asked for (a strict schema where the caller has one);
    Sarvam always gets `json_object`. The caller owns the prompt's content and its redaction
    (D-127 G-1/G-2): nothing here reads a transcript.

    `timeout_s` is one request budget; the whole ladder spends at most `ASSIST_LADDER_LEGS`
    of them (`extraction.ladder_deadlines`), the standby always keeping at least one. A
    route keeps the default, which nginx's deadline is pinned against
    (`tests/assist_deadline_test.py`); a worker job may give a long answer more time.

    A refusal raised after the paid leg answered is a `SpentRefusalError` carrying that spend, so
    the caller meters it (`crm/assist.meter_refusal`) before the refusal reaches anyone.
    """
    capability = assist_capability(
        tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, allow_azure=not gemini_only
    )
    if not capability.available:
        raise assist_unavailable(capability)
    if gemini_only and capability.provider != GOOGLE_PROVIDER:
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )

    paid_until, standby_until = ladder_deadlines(timeout_s)
    earlier: list[PaidTurn] = []
    answered_unusably = False
    if capability.provider in (AZURE_PROVIDER, GOOGLE_PROVIDER):
        response_format = azure_format or {"type": "json_object"}
        model: str | None = (
            tenant_leg.model
            if capability.provider == GOOGLE_PROVIDER and tenant_leg is not None
            else None
        )

        async def paid_answer(text: str) -> _RawJson | None:
            if model is not None:
                return await _json_via_google(
                    model,
                    text,
                    instruction,
                    response_format,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_s=timeout_s,
                    deadline=paid_until,
                    health_leg=health_leg,
                )
            return await _json_via_azure(
                text,
                instruction,
                response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=timeout_s,
                deadline=paid_until,
                health_leg=health_leg,
            )

        paid = await paid_answer(description)
        value, problems = _parsed_with_problems(parse, paid.data if paid is not None else None)
        spent = paid.usage if paid is not None else None
        if value is None and problems is not None:
            # ONE REPAIR on the same leg, told what was wrong, before the fallback. A long
            # structured answer that breaks one validation rule is usually right everywhere
            # else, and the fallback leg is slower and weaker at exactly this kind of answer.
            repaired = await paid_answer(
                f"{description}\n\n{REPAIR_NOTE.format(problems=problems)}"
            )
            if repaired is not None:
                # A repair that never reached the provider cost nothing: the first
                # attempt's known spend stays known rather than becoming "unreported".
                spent = _usage_sum(spent, repaired.usage)
                value = _parsed(parse, repaired.data)
        if value is not None:
            # `None` on Azure: `meter_assist` names the live `azure_openai_model`.
            return JsonAnswer(
                value=value,
                capability=capability,
                usage=spent,
                model=model or get_settings().azure_openai_model,
            )
        if paid is not None:
            # Billed as a request, refused as an answer: metered at its own model.
            earlier.append(PaidTurn(spent, capability, model))
        answered_unusably = problems is not None
        if gemini_only:
            refusal = (
                _answer_unusable()
                if answered_unusably
                else assist_unavailable(
                    AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
                )
            )
            raise refused_after_spend(refusal, earlier)
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            refusal = _answer_unusable() if answered_unusably else assist_unavailable(capability)
            raise refused_after_spend(refusal, earlier)

    sarvam = await _json_via_sarvam(
        description,
        instruction,
        max_tokens=max_tokens,
        temperature=temperature,
        # The standby gets whatever the paid leg left, never less than one budget: a fixed
        # 15 s timed out on a long answer while the paid leg had failed in a second.
        timeout_s=time_left(standby_until),
        deadline=standby_until,
    )
    value = _parsed(parse, sarvam.data) if sarvam is not None else None
    if value is None:
        # Both legs silent: a refusal the owner can act on, not an empty answer. When the
        # paid leg DID answer and only the shape was wrong, saying "no assistant answered"
        # would be untrue and would send the owner to support for a rewording problem.
        if sarvam is not None:
            # The standby answered unusably: its spend is ours to record too.
            earlier.append(PaidTurn(sarvam.usage, capability, SARVAM_DEFAULT_LLM))
        refusal = (
            _answer_unusable()
            if answered_unusably
            else assist_unavailable(
                AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
            )
        )
        raise refused_after_spend(refusal, earlier)
    return JsonAnswer(
        value=value,
        capability=capability,
        usage=sarvam.usage if sarvam is not None else None,
        model=SARVAM_DEFAULT_LLM,
        earlier=tuple(earlier),
    )


async def draft_script(
    brief: ScriptBrief | str,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    instruction: str = _SYSTEM_INSTRUCTION,
    edit_of: CallScript | None = None,
    change: str = "",
) -> ScriptDraft:
    """Draft a `CallScript` from a business description (the AI writing assist), or, with
    `CONVERT_INSTRUCTION`, propose sections for a hand-written prompt, or, with `edit_of`,
    make one change to the current script keeping every step id.

    `quota_exhausted` is the gate's verdict passed IN (this module has no session), so the
    ceiling reaches the one function that spends a token. `tenant_leg` is the account's own
    model, passed in the same way and for the same reason — it is a row.
    """
    # A bare string is the old one-box description; the builder now sends a full brief.
    full = ScriptBrief(description=brief) if isinstance(brief, str) else brief
    description = full.user_message()
    parse: Parser
    if edit_of is not None:
        # "Change this" (founder, 10 Oct 2026): the current script with one change made,
        # section ids kept, so the Script page can show it section by section.
        instruction = EDIT_INSTRUCTION
        description = (
            f"{description}\nThe owner's change: {change.strip()}\nCurrent script (JSON):\n"
            f"{edit_of.model_dump_json(exclude={'raw_override'})}"
        )
        parse = partial(edited_script, current=edit_of, language=full.language, allowed=change)
    else:
        # A conversion keeps the owner's own sentences, in whatever language they wrote them,
        # so only a textbook word the owner did not write is the model's to fix.
        converting = instruction == CONVERT_INSTRUCTION
        parse = partial(
            drafted_script,
            language=full.language,
            allowed=full.description if converting else "",
            instructions=not converting,
        )
    answer = await ask_json(
        description,
        instruction,
        parse=parse,
        azure_format=_draft_format(edit=edit_of is not None),
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
    )
    return ScriptDraft(
        script=answer.value,
        capability=answer.capability,
        usage=answer.usage,
        model=answer.model,
        earlier=answer.earlier,
    )


__all__ = [
    "ANSWER_UNUSABLE_CODE",
    "CONVERT_INSTRUCTION",
    "EDIT_INSTRUCTION",
    "OWNER_QUESTIONS",
    "REPAIR_NOTE",
    "JsonAnswer",
    "ScriptBrief",
    "ScriptDraft",
    "UnusableAnswerError",
    "ask_json",
    "draft_script",
    "drafted_script",
    "edited_script",
    "language_problems",
]
