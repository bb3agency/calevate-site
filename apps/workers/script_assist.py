"""Draft a call script from a plain-language business description — the AI writing assist.

The founder's "draft/improve my script from a business description". The owner answers five
short questions; the builder adds the business type, the calling direction, the call
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
`apps/api/agents/script_assist_service.py` in SUBJECT → GATE → RUN → METER order, exactly
as `crm/routes.assist_call` does for re-summarise. This module returns the draft and, for
an Azure answer Azure counted, its `usage`; it charges nothing.
"""

from __future__ import annotations

from collections.abc import Callable
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
from calevate_shared.engine import SARVAM_DEFAULT_LLM, azure_openai_base_url
from pydantic import ValidationError

from apps.api.core import provider_health
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    ASSIST_TIMEOUT_S,
    AZURE_PROVIDER,
    PROVIDER_UNAVAILABLE_REASON,
    SARVAM_CHAT_URL,
    AssistCapability,
    TenantModelLeg,
    _first_json_object,
    assist_capability,
    assist_unavailable,
    azure_credentials,
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
    "Write instructions (identity, goal, stage instructions and exit conditions, "
    "objections, ending) in plain English. Write the words the agent will SAY (opening_line, "
    "sample_phrases, example_exchange) in the call language as people really speak it on "
    "the phone in that register, with the English words they use (order, delivery, "
    "booking, price), never formal written language, in the script that language is "
    "normally written in. Keep every spoken line to one short sentence.\n"
    "Rules: NEVER invent prices, stock, hours, addresses, phone numbers, offers or any fact "
    "the owner did not give; facts live in the knowledge base, which the agent searches. "
    "quick_facts only restates facts the owner wrote. The example_exchange shows style "
    "only and contains no fact. Do not write anything about being an AI, about recording, "
    "about call backs or transfers, or about do-not-call requests: the platform adds those "
    "rules itself and knows what this account can do. The opening_line greets and names the "
    "business; do not put an AI or recording notice in it. For an agent that places calls, "
    "outbound_purpose is one sentence on why we are calling, and a stage confirms it is a "
    "good time and that this is the right person ({{lead_name}} is the merge field for the "
    "lead's name); for an agent that only answers calls leave outbound_purpose empty. "
    "Stages are 3 to 6, each with a short name, an English instruction, exit_when, and "
    "sounds_like: one short line in the call language showing how that stage sounds. Ask "
    "only for "
    "the listed details. 2 to 5 objections the business really meets. 3 to 6 sample "
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
    "Return ONLY JSON matching the schema."
)

#: Making one change the owner asked for to the current script.
EDIT_INSTRUCTION = (
    "You edit the call script of an AI phone agent. You are given the current script as "
    "JSON and one change the owner wants. Return the WHOLE script as JSON in exactly the same "
    "shape, with only that change made: keep every other field, every section and every "
    "section id as it is, and give any new section a new short lowercase id. Instructions "
    "stay in plain English; words the agent says stay in the call language, spoken, with "
    "the English words people use. Never invent prices or facts. Do not write about being "
    "an AI, recording, call backs, transfers or do-not-call. Return ONLY JSON."
)

Parser = Callable[[dict[str, Any]], "CallScript | None"]


def _edited_script(raw: dict[str, Any], current: CallScript) -> CallScript | None:
    """The model's edited script, validated like any save; None when it is not a valid
    script (the edit is then reported as no draft rather than half applied)."""
    fields = {k: v for k, v in raw.items() if k in CallScript.model_fields}
    try:
        edited = CallScript.model_validate({**current.model_dump(), **fields})
    except ValidationError:
        log.warning("script_assist_edit_unusable")
        return None
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

#: The five short questions the builder asks the owner. Keys are the wire's.
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
        if self.register:
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
    rather than in the editor. `usage` is non-None only for Azure tokens Azure counted —
    including an Azure turn that failed in front of a Sarvam draft — exactly as
    `AssistResult.usage` is: the one leg `record_ai_assist_usage` can price.
    `capability` carries the fallback disclosure the response and screen must show (G-6).
    """

    script: CallScript
    capability: AssistCapability
    usage: TokenUsage | None = None


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


async def _draft_via_azure(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """Ask Azure OpenAI for a draft, or None if it holds no credential or did not answer.

    The request goes through `workers/chat.py`, the ONE chat client — the v1 surface built
    by the ONE endpoint builder, a static bearer key, Structured Outputs with a degrade to
    `json_object`. It used to be a hand-rolled `httpx.post` mirroring
    `AzureOpenAIExtractor.run`'s wire shape, which is exactly the "second dialect of the
    same request" that module's docstring exists to stop having.
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
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": description},
    ]
    # An edit returns the whole current script, whose shape the strict draft schema does
    # not describe, so it asks for plain JSON and is validated by `CallScript` instead.
    strict: dict[str, object] = (
        {
            "type": "json_schema",
            "json_schema": {
                "name": "calevate_script_draft",
                "strict": True,
                "schema": _DRAFT_SCHEMA,
            },
        }
        if parse is None
        else {"type": "json_object"}
    )
    try:
        outcome = await chat.complete(
            leg,
            messages,
            timeout_s=ASSIST_TIMEOUT_S,
            temperature=0.4,
            response_format=strict,
            max_tokens=_DRAFT_MAX_TOKENS,
        )
    except httpx.HTTPStatusError as refusal:
        if refusal.response.status_code != 400:
            log.warning(
                "script_assist_azure_failed", extra={"status": refusal.response.status_code}
            )
            await provider_health.note_failure("script", AZURE_PROVIDER, refusal)
            return None
        # The resource refused Structured Outputs (documented, unobserved here — see
        # `AzureOpenAIExtractor`). Degrade ONCE to plain json_object; the belt is
        # `_first_json_object`. No body logged (hard rule 6): it quotes the request.
        log.warning("script_assist_azure_json_schema_unsupported")
        try:
            outcome = await chat.complete(
                leg,
                messages,
                timeout_s=ASSIST_TIMEOUT_S,
                temperature=0.4,
                response_format={"type": "json_object"},
                max_tokens=_DRAFT_MAX_TOKENS,
            )
        except httpx.HTTPError as retry_refusal:
            # HTTPError, not only HTTPStatusError: this handler sits inside the first
            # `except`, so a transport failure on the retry would skip the outer
            # `except httpx.HTTPError` below and escape to the caller.
            log.warning(
                "script_assist_azure_failed",
                extra=provider_health.failure_fields(retry_refusal),
            )
            await provider_health.note_failure("script", AZURE_PROVIDER, retry_refusal)
            return None
    except httpx.HTTPError as failure:
        # A transport failure is the same OUTCOME as a refusal for this caller — the
        # selector is re-asked with `provider_unavailable=True` — and it used to escape
        # this function entirely, because the old hand-rolled `post` only ever looked at a
        # status code it had already received.
        log.warning(
            "script_assist_azure_unreachable", extra=provider_health.failure_fields(failure)
        )
        await provider_health.note_failure("script", AZURE_PROVIDER, failure)
        return None
    await provider_health.note_success("script", AZURE_PROVIDER)
    if outcome.finish_reason == "length":
        # The `_DRAFT_MAX_TOKENS` valve fired. The JSON was cut off mid-generation, so
        # parsing it would either fail (→ an inexplicable empty editor) or, worse, yield
        # a balanced PREFIX that reads as a short draft. "No draft" is the honest answer;
        # the caller falls back exactly as it does for any other non-answer — carrying the
        # billed tokens, which the valve firing means were the most this turn could cost.
        log.warning("script_assist_draft_truncated", extra={"provider": "azure"})
        return _RawDraft(script=None, usage=outcome.usage)
    raw = _first_json_object(outcome.content)
    if not raw:
        return _RawDraft(script=None, usage=outcome.usage)
    return _RawDraft(script=(parse or _script_from_model_json)(raw), usage=outcome.usage)


async def _draft_via_sarvam(
    description: str,
    instruction: str = _SYSTEM_INSTRUCTION,
    parse: Parser | None = None,
) -> _RawDraft | None:
    """The disclosed fallback: Sarvam's OpenAI-compatible chat, `json_object` + the belt.

    No `usage` is returned — D-36 prices this leg at zero, so `ScriptDraft.usage` stays
    None and `meter_assist`'s Sarvam branch records nothing, exactly as re-summarise does.
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
            timeout_s=ASSIST_TIMEOUT_S,
            temperature=0.4,
            response_format={"type": "json_object"},
            max_tokens=_DRAFT_MAX_TOKENS,
        )
    except httpx.HTTPStatusError as refusal:
        log.warning("script_assist_sarvam_failed", extra={"status": refusal.response.status_code})
        return None
    except httpx.HTTPError:
        log.warning("script_assist_sarvam_unreachable")
        return None
    if outcome.finish_reason == "length":
        # Same valve, same honesty as the Azure leg: truncated JSON must not read as a
        # short draft.
        log.warning("script_assist_draft_truncated", extra={"provider": "sarvam"})
        return None
    raw = _first_json_object(outcome.content)
    if not raw:
        return None
    return _RawDraft(script=(parse or _script_from_model_json)(raw))


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
    `CONVERT_INSTRUCTION`, propose sections for a hand-written prompt.

    Same control flow as `run_assist`: ask the ONE selector who serves, run Azure first,
    fall to the disclosed Sarvam leg if Azure cannot or does not answer, and refuse only
    when nothing can. `quota_exhausted` is the gate's verdict passed IN (this module has no
    session), so the ceiling reaches the one function that spends a token. `tenant_leg` is
    the account's own model, passed in the same way and for the same reason — it is a row.
    """
    capability = assist_capability(tenant_leg=tenant_leg, quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)
    # A bare string is the old one-box description; the builder now sends a full brief.
    description = (
        ScriptBrief(description=brief) if isinstance(brief, str) else brief
    ).user_message()
    parse: Parser | None = None
    if edit_of is not None:
        # The AI helper's "change this" (founder, 10 Oct 2026): the current script with one
        # change made, section ids kept, so the builder can show it section by section.
        instruction = EDIT_INSTRUCTION
        description = (
            f"{description}\nThe owner's change: {change.strip()}\nCurrent script (JSON):\n"
            f"{edit_of.model_dump_json(exclude={'raw_override'})}"
        )
        parse = partial(_edited_script, current=edit_of)

    # What an Azure turn that produced no draft still cost — `run_assist`'s `spent`, for
    # its reason: billed as a request, refused as an answer, so it rides the fallback's
    # draft to the meter. The Sarvam leg itself adds nothing (D-36).
    spent: TokenUsage | None = None
    if capability.provider == AZURE_PROVIDER:
        azure = await _draft_via_azure(description, instruction, parse)
        if azure is not None and azure.script is not None:
            return ScriptDraft(script=azure.script, capability=capability, usage=azure.usage)
        spent = azure.usage if azure is not None else None
        # Azure could not answer — re-ask the selector with the fact we now have rather
        # than deciding locally what an outage means (run_assist's rule).
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            raise assist_unavailable(capability)

    drafted = await _draft_via_sarvam(description, instruction, parse)
    if drafted is None or drafted.script is None:
        # Both legs silent: a refusal the author can act on, not an empty editor.
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )
    return ScriptDraft(script=drafted.script, capability=capability, usage=spent)


__all__ = [
    "CONVERT_INSTRUCTION",
    "EDIT_INSTRUCTION",
    "OWNER_QUESTIONS",
    "ScriptBrief",
    "ScriptDraft",
    "draft_script",
]
