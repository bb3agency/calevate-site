"""Draft a call script from a plain-language business description — the AI writing assist.

The founder's "draft/improve my script from a business description". A client types what
their business does and how they want calls handled, and the assistant model returns a
DRAFT opening line, ordered steps and FAQ pairs the builder pre-fills — never applied to a
live call, always the author's to edit and then save through the ordinary staged path.

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

from dataclasses import dataclass, field

import httpx
from calevate_shared.call_script import CallScript, FaqEntry, ScriptStep
from calevate_shared.engine import SARVAM_DEFAULT_LLM, azure_openai_base_url

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

#: The instruction that turns a business description into a call script. Kept as a module
#: constant, not an f-string at the call site, so `tests/script_assist_prompt_test.py` can
#: assert its rules — Telugu-first, no invented facts, phone-appropriate brevity — the same
#: way `extraction_prompt_test.py` pins the extraction prompt (the artefact CI can gate
#: without a credential).
_SYSTEM_INSTRUCTION = (
    "You write scripts for AI voice agents that answer phone calls for small Indian "
    "businesses. The primary language is Telugu; write natural, warm, conversational Telugu "
    "(Tenglish code-switching is fine), in SHORT spoken sentences a phone agent can say out "
    "loud — no markdown, no lists inside a sentence, one idea per line. "
    "From the business description, produce: an opening line the agent says after "
    "introducing itself; an ordered list of steps for handling a typical call (greet, "
    "understand the need, answer or qualify, capture details, next step, wrap up); and a few "
    "FAQ question/answer pairs for things callers commonly ask. "
    "NEVER invent prices, addresses, phone numbers, hours or availability the description "
    "does not state — leave those for the client to fill in, and where useful reference a "
    "merge field like {{lead_name}} or {{product_interest}}. "
    "Do not write any promise about being human or about recording; the platform adds those "
    "rules itself. "
    "Return ONLY JSON of the form "
    '{"opening_line": str, "steps": [str], "faqs": [{"question": str, "answer": str}]}.'
)

#: The ceiling on ONE draft answer, in tokens — `EXTRACTION_MAX_TOKENS`'s safety valve,
#: on the one assist surface that had none. A draft is an opening line, a handful of steps
#: and "a few" FAQ pairs, all bounded by `_script_from_model_json`'s truncation lengths;
#: even a verbose Telugu draft (~2.1-2.3 tokens/word) sits far under this, so the valve can
#: only fire on a runaway generation — which, uncapped, was bounded by nothing but the leg
#: timeout, i.e. paid output tokens for as long as the model kept talking. A hit surfaces
#: as `finish_reason == "length"` and the leg reports "no draft" rather than parsing JSON
#: cut off mid-string (the `ExtractionTruncatedError` argument: a truncation must not read
#: as a small answer). `max_tokens` is a verified body key on BOTH dialects used here
#: (`workers/chat.py::_request_body` — standard OpenAI/Azure, and on Sarvam's own client's
#: fourteen-key list).
_DRAFT_MAX_TOKENS = 4096

#: The strict JSON Schema for the draft, so Azure's Structured Outputs guarantees the shape
#: (`build_azure_response_schema`'s argument, applied to this task). Sarvam gets
#: `json_object` and `_first_json_object` as the belt, like every non-Azure JSON path here.
_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "opening_line": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "faqs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["question", "answer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["opening_line", "steps", "faqs"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ScriptDraft:
    """One AI-drafted script, what it cost, and who wrote it.

    `script` is a structured `CallScript` the builder can load directly — opening line,
    steps and FAQ, in raw pydantic-validated form so a malformed model answer is caught here
    rather than in the editor. `usage` is non-None only for an Azure answer Azure counted,
    exactly as `AssistResult.usage` is: the one leg `record_ai_assist_usage` can price.
    `capability` carries the fallback disclosure the response and screen must show (G-6).
    """

    script: CallScript
    capability: AssistCapability
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class _RawDraft:
    """The model's JSON, normalised into a `CallScript`, plus usage. Internal to this file."""

    script: CallScript
    usage: TokenUsage | None = field(default=None)


def _script_from_model_json(raw: dict[str, object]) -> CallScript:
    """The model's `{opening_line, steps, faqs}` as a validated `CallScript`.

    Tolerant of the model omitting or malforming a piece — a draft is a starting point, not
    a stored record — but every value that DOES arrive is run through the same `CallScript`
    validators the builder enforces, so a draft can never carry a step or FAQ the editor
    would reject. Empty pieces simply come back empty for the author to fill.
    """
    opening = raw.get("opening_line")
    steps_raw = raw.get("steps")
    faqs_raw = raw.get("faqs")

    steps: list[ScriptStep] = []
    if isinstance(steps_raw, list):
        for item in steps_raw:
            text = str(item).strip()
            if text:
                steps.append(ScriptStep(instruction=text[:1000]))

    faqs: list[FaqEntry] = []
    if isinstance(faqs_raw, list):
        for item in faqs_raw:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if question and answer:
                faqs.append(FaqEntry(question=question[:500], answer=answer[:2000]))

    return CallScript(
        opening_line=(str(opening).strip()[:1000] if isinstance(opening, str) else ""),
        steps=steps,
        faqs=faqs,
    )


async def _draft_via_azure(description: str) -> _RawDraft | None:
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
        {"role": "system", "content": _SYSTEM_INSTRUCTION},
        {"role": "user", "content": description},
    ]
    strict: dict[str, object] = {
        "type": "json_schema",
        "json_schema": {"name": "calevate_script_draft", "strict": True, "schema": _DRAFT_SCHEMA},
    }
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
        except httpx.HTTPStatusError as retry_refusal:
            log.warning(
                "script_assist_azure_failed",
                extra={"status": retry_refusal.response.status_code},
            )
            return None
    except httpx.HTTPError:
        # A transport failure is the same OUTCOME as a refusal for this caller — the
        # selector is re-asked with `provider_unavailable=True` — and it used to escape
        # this function entirely, because the old hand-rolled `post` only ever looked at a
        # status code it had already received.
        log.warning("script_assist_azure_unreachable")
        return None
    if outcome.finish_reason == "length":
        # The `_DRAFT_MAX_TOKENS` valve fired. The JSON was cut off mid-generation, so
        # parsing it would either fail (→ an inexplicable empty editor) or, worse, yield
        # a balanced PREFIX that reads as a short draft. "No draft" is the honest answer;
        # the caller falls back exactly as it does for any other non-answer. (The paid
        # tokens go unmetered on this arm, as on every `None` return here — a
        # pre-existing failure-path gap, not widened by this check.)
        log.warning("script_assist_draft_truncated", extra={"provider": "azure"})
        return None
    raw = _first_json_object(outcome.content)
    if not raw:
        return None
    return _RawDraft(script=_script_from_model_json(raw), usage=outcome.usage)


async def _draft_via_sarvam(description: str) -> _RawDraft | None:
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
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
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
    return _RawDraft(script=_script_from_model_json(raw))


async def draft_script(
    description: str,
    *,
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
) -> ScriptDraft:
    """Draft a `CallScript` from a business description (the AI writing assist).

    Same control flow as `run_assist`: ask the ONE selector who serves, run Azure first,
    fall to the disclosed Sarvam leg if Azure cannot or does not answer, and refuse only
    when nothing can. `quota_exhausted` is the gate's verdict passed IN (this module has no
    session), so the ceiling reaches the one function that spends a token. `tenant_leg` is
    the account's own model, passed in the same way and for the same reason — it is a row.
    """
    capability = assist_capability(tenant_leg=tenant_leg, quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)

    if capability.provider == AZURE_PROVIDER:
        drafted = await _draft_via_azure(description)
        if drafted is not None:
            return ScriptDraft(script=drafted.script, capability=capability, usage=drafted.usage)
        # Azure could not answer — re-ask the selector with the fact we now have rather
        # than deciding locally what an outage means (run_assist's rule).
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            raise assist_unavailable(capability)

    drafted = await _draft_via_sarvam(description)
    if drafted is None:
        # Both legs silent: a refusal the author can act on, not an empty editor.
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )
    return ScriptDraft(script=drafted.script, capability=capability)


__all__ = ["ScriptDraft", "draft_script"]
