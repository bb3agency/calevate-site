"""Draft a call script from a plain-language business description — the AI writing assist.

The founder's "draft/improve my script from a business description". A client types what
their business does and how they want calls handled, and the assistant model returns a
DRAFT opening line, ordered steps and FAQ pairs the builder pre-fills — never applied to a
live call, always the author's to edit and then save through the ordinary staged path.

WHY IT LIVES IN `apps/workers` AND REUSES THE ASSIST LADDER. CLAUDE.md's Do-NOT rule keeps
model calls out of request handlers; the dashboard-AI assist (`crm/assist.py` +
`workers/extraction.run_assist`) is the established controlled path, so this is the same
shape rather than a second one: the SAME `assist_capability` selector decides who answers
(Azure preferred, Sarvam disclosed-fallback, else a refusal), the SAME `TokenUsage` /
`_azure_usage` carry what it cost back for metering, the SAME `ASSIST_TIMEOUT_S` bounds each
leg. Only the PROMPT and the OUTPUT SHAPE differ, because the task differs — drafting a
script is not extracting a lead — and a different task is exactly when a second request
shape is warranted rather than a duplicated one.

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
from apps.workers.extraction import (
    ASSIST_TIMEOUT_S,
    AZURE_PROVIDER,
    SARVAM_CHAT_URL,
    AssistCapability,
    TokenUsage,
    _azure_usage,
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

    The request mirrors `AzureOpenAIExtractor.run`'s wire shape — the v1 surface built by
    the ONE endpoint builder, a static bearer key, Structured Outputs with a degrade to
    `json_object` — because that is the confirmed-working request against our resource, and
    a second dialect of it is a second thing to keep in step. It differs only in the prompt
    and the schema, which is the whole of what this task changes.
    """
    credentials = azure_credentials()
    if credentials is None:
        return None
    resource, api_key, deployment = credentials
    url = f"{azure_openai_base_url(resource)}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    messages = [
        {"role": "system", "content": _SYSTEM_INSTRUCTION},
        {"role": "user", "content": description},
    ]
    body: dict[str, object] = {
        "model": deployment,
        "messages": messages,
        "temperature": 0.4,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "calevate_script_draft",
                "strict": True,
                "schema": _DRAFT_SCHEMA,
            },
        },
    }
    async with httpx.AsyncClient(timeout=ASSIST_TIMEOUT_S) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 400:
            # The resource refused Structured Outputs (documented, unobserved here — see
            # `AzureOpenAIExtractor`). Degrade ONCE to plain json_object; the belt is
            # `_first_json_object`. No body logged (hard rule 6): it quotes the request.
            log.warning("script_assist_azure_json_schema_unsupported")
            body["response_format"] = {"type": "json_object"}
            response = await client.post(url, headers=headers, json=body)
    if response.status_code >= 400:
        log.warning("script_assist_azure_failed", extra={"status": response.status_code})
        return None
    payload = response.json()
    choices = payload.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    raw = _first_json_object(str(content))
    if not raw:
        return None
    return _RawDraft(script=_script_from_model_json(raw), usage=_azure_usage(payload))


async def _draft_via_sarvam(description: str) -> _RawDraft | None:
    """The disclosed fallback: Sarvam's OpenAI-compatible chat, `json_object` + the belt.

    No `usage` is returned — D-36 prices this leg at zero, so `ScriptDraft.usage` stays
    None and `meter_assist`'s Sarvam branch records nothing, exactly as re-summarise does.
    """
    settings = get_settings()
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        return None
    async with httpx.AsyncClient(timeout=ASSIST_TIMEOUT_S) as client:
        response = await client.post(
            SARVAM_CHAT_URL,
            headers={"Authorization": f"Bearer {settings.sarvam_api_key}"},
            json={
                "model": SARVAM_DEFAULT_LLM,
                "messages": [
                    {"role": "system", "content": _SYSTEM_INSTRUCTION},
                    {"role": "user", "content": description},
                ],
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
            },
        )
    if response.status_code >= 400:
        log.warning("script_assist_sarvam_failed", extra={"status": response.status_code})
        return None
    payload = response.json()
    choices = payload.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    raw = _first_json_object(str(content))
    if not raw:
        return None
    return _RawDraft(script=_script_from_model_json(raw))


async def draft_script(description: str, *, quota_exhausted: bool = False) -> ScriptDraft:
    """Draft a `CallScript` from a business description (the AI writing assist).

    Same control flow as `run_assist`: ask the ONE selector who serves, run Azure first,
    fall to the disclosed Sarvam leg if Azure cannot or does not answer, and refuse only
    when nothing can. `quota_exhausted` is the gate's verdict passed IN (this module has no
    session), so the ceiling reaches the one function that spends a token.
    """
    capability = assist_capability(quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)

    if capability.provider == AZURE_PROVIDER:
        drafted = await _draft_via_azure(description)
        if drafted is not None:
            return ScriptDraft(script=drafted.script, capability=capability, usage=drafted.usage)
        # Azure could not answer — re-ask the selector with the fact we now have rather
        # than deciding locally what an outage means (run_assist's rule).
        capability = assist_capability(quota_exhausted=quota_exhausted, provider_unavailable=True)
        if not capability.available:
            raise assist_unavailable(capability)

    drafted = await _draft_via_sarvam(description)
    if drafted is None:
        # Both legs silent: a refusal the author can act on, not an empty editor.
        raise assist_unavailable(AssistCapability(available=False, reason="provider_unavailable"))
    return ScriptDraft(script=drafted.script, capability=capability)


__all__ = ["ScriptDraft", "draft_script"]
