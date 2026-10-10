"""Reads and sorts one teaching from the teach box (`apps/api/teach/teaching.py`).

1. READ, when the owner sent a photo, a file or a voice note: a photo is read by the OCR leg
   (`document_ocr`, metered as `kb_ocr`), a file by the document reader, a voice note by our
   speech-to-text sub-processor. A voice note then STOPS at `heard`: the owner checks the
   words before anything is sorted or saved.
2. SORT the words into facts and rules with the dashboard-assist ladder (Azure, then the
   disclosed Sarvam leg), metered against the client's AI allowance as `kb_teach`. When the
   allowance is used up or no model answers, the words come back unsorted, one line each,
   with a sentence saying so: teaching never stops for lack of AI.

WHAT THE MODEL SEES. The owner's own words about their business (the tenant-authored class
`workers/script_assist` serves), never a caller's. Not redacted, because a fact such as the
shop's own phone number is exactly what is being taught. Never logged (hard rule 6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import httpx
from calevate_shared.document_ingest import DocumentRefusedError, OcrUnavailableError
from calevate_shared.engine import SARVAM_DEFAULT_LLM, azure_openai_base_url
from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota, record_ai_assist_usage
from apps.api.core import provider_health
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.crm.assist import ASSIST_FEATURE_KB_OCR
from apps.api.db.session import tenant_session
from apps.api.kb.uploads import classify_upload
from apps.api.teach.models import MAX_FACT_CHARS, MAX_RULE_CHARS, MAX_TEACH_WORDS
from apps.api.teach.teaching import ASSIST_FEATURE_KB_TEACH, TEACH_JOB
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.document_ocr import OcrImage, PaidOcrUnusableError, ocr_images
from apps.workers.document_text import extract_document
from apps.workers.extraction import (
    ASSIST_TIMEOUT_S,
    AZURE_PROVIDER,
    QUOTA_EXHAUSTED_REASON,
    SARVAM_CHAT_URL,
    AssistCapability,
    _first_json_object,
    assist_capability,
    azure_credentials,
)
from apps.workers.storage import delete_objects, read_kb_object

log = get_logger(__name__)

JOB_NAME: Final = TEACH_JOB

#: Sarvam's REST speech-to-text (sarvamai 0.1.28, `speech_to_text/raw_client.py`: POST
#: `speech-to-text` on `https://api.sarvam.ai`, multipart `file`, form `model`/`mode`/
#: `language_code`/`input_audio_codec`, header `api-subscription-key`; clips under 30 s).
SARVAM_STT_URL: Final = "https://api.sarvam.ai/speech-to-text"
#: `saaras:v3` in `codemix` mode keeps English words in English and Indian-language words in
#: their own script, the way owners speak; `unknown` lets it detect the language.
STT_MODEL: Final = "saaras:v3"
STT_MODE: Final = "codemix"
STT_TIMEOUT_S: Final = 40.0

_CODECS: Final[dict[str, str]] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/aac": "aac",
}

MAX_ITEMS: Final = 30
SORT_MAX_TOKENS: Final = 2000

SYSTEM_PROMPT: Final = (
    "You sort what the owner of a small Indian business tells their AI phone agent into "
    "FACTS and RULES. A FACT is something true about the business that a caller might ask "
    "about: products, stock, prices, hours, address, delivery areas, offers, policies. A "
    "RULE tells the agent how to behave on calls: what to say or never say, when to offer "
    "something, how to treat a kind of caller. Split the owner's words into short items "
    "that each make sense alone, one fact or one rule per item. Keep the owner's language "
    "and the English words they use. Never add anything the owner did not say, never "
    "change a number, price, name or time, and drop greetings and filler. Write each fact "
    "as a plain statement and each rule as an instruction to the agent. "
    f"At most {MAX_ITEMS} items. "
    'Return ONLY JSON: {"items": [{"kind": "fact" or "rule", "text": str}]}.'
)

_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["fact", "rule"]},
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

UNSORTED_NOTE: Final = (
    "We could not sort this automatically, so each line is shown as a fact. Mark the ones "
    "that are rules."
)
QUOTA_NOTE: Final = (
    "This month's AI help is used up, so this was not sorted. Each line is shown as a fact; "
    "mark the ones that are rules."
)


@dataclass(frozen=True, slots=True)
class Sorted:
    items: list[dict[str, str]]
    #: For `crm.assist.meter_assist`; `usage` is what a paid turn cost.
    capability: AssistCapability
    usage: TokenUsage | None
    note: str | None


def items_from_model(raw: dict[str, Any]) -> list[dict[str, str]]:
    """The model's answer as review items, dropping anything malformed or empty."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw.get("items") or []:
        if not isinstance(item, dict) or item.get("kind") not in ("fact", "rule"):
            continue
        limit = MAX_FACT_CHARS if item["kind"] == "fact" else MAX_RULE_CHARS
        value = " ".join(str(item.get("text") or "").split())[:limit]
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        out.append({"kind": str(item["kind"]), "text": value})
        if len(out) >= MAX_ITEMS:
            break
    return out


def unsorted_items(words: str) -> list[dict[str, str]]:
    """The owner's words, one line or sentence per item, each shown as a fact."""
    pieces: list[str] = []
    for line in words.splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        if len(line) <= MAX_FACT_CHARS:
            pieces.append(line)
            continue
        for sentence in re.split(r"(?<=[.!?।])\s+", line):
            while sentence:
                pieces.append(sentence[:MAX_FACT_CHARS])
                sentence = sentence[MAX_FACT_CHARS:].strip()
    return [{"kind": "fact", "text": piece} for piece in pieces[:MAX_ITEMS]]


async def _ask(leg: chat.ChatLeg, words: str, *, strict: bool) -> chat.ChatOutcome:
    response_format: dict[str, Any] = (
        {
            "type": "json_schema",
            "json_schema": {"name": "teach_sort", "strict": True, "schema": _SCHEMA},
        }
        if strict
        else {"type": "json_object"}
    )
    return await chat.complete(
        leg,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": words}],
        timeout_s=ASSIST_TIMEOUT_S,
        temperature=0.1,
        response_format=response_format,
        max_tokens=SORT_MAX_TOKENS,
    )


async def _via_azure(words: str) -> tuple[list[dict[str, str]], TokenUsage | None] | None:
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
    try:
        try:
            outcome = await _ask(leg, words, strict=True)
        except httpx.HTTPStatusError as refusal:
            if refusal.response.status_code != 400:
                raise
            outcome = await _ask(leg, words, strict=False)
    except httpx.HTTPError as failure:
        log.warning("kb_teach_azure_failed", extra=provider_health.failure_fields(failure))
        await provider_health.note_failure("teach", AZURE_PROVIDER, failure)
        return None
    await provider_health.note_success("teach", AZURE_PROVIDER)
    items = (
        items_from_model(_first_json_object(outcome.content))
        if outcome.finish_reason != "length"
        else []
    )
    return items, outcome.usage


async def _via_sarvam(words: str) -> list[dict[str, str]]:
    settings = get_settings()
    if not settings.sarvam_api_key:
        return []
    leg = chat.ChatLeg(
        url=SARVAM_CHAT_URL,
        api_key=settings.sarvam_api_key,
        wire_model=SARVAM_DEFAULT_LLM,
        dialect="sarvam",
    )
    try:
        outcome = await _ask(leg, words, strict=False)
    except httpx.HTTPError as failure:
        log.warning("kb_teach_sarvam_failed", extra=provider_health.failure_fields(failure))
        return []
    if outcome.finish_reason == "length":
        return []
    return items_from_model(_first_json_object(outcome.content))


async def sort_words(
    words: str, *, capability: AssistCapability, tenant_leg: Any, quota_exhausted: bool
) -> Sorted:
    """Facts and rules from the owner's words; the ladder `workers/script_assist` follows."""
    if not capability.available:
        note = QUOTA_NOTE if capability.reason == QUOTA_EXHAUSTED_REASON else UNSORTED_NOTE
        return Sorted(unsorted_items(words), capability, None, note)
    spent: TokenUsage | None = None
    if capability.provider == AZURE_PROVIDER:
        azure = await _via_azure(words)
        if azure is not None and azure[0]:
            return Sorted(azure[0], capability, azure[1], capability.disclosure)
        spent = azure[1] if azure is not None else None
        capability = assist_capability(
            tenant_leg=tenant_leg, quota_exhausted=quota_exhausted, provider_unavailable=True
        )
        if not capability.available:
            return Sorted(unsorted_items(words), capability, spent, UNSORTED_NOTE)
    items = await _via_sarvam(words)
    if not items:
        return Sorted(unsorted_items(words), capability, spent, UNSORTED_NOTE)
    return Sorted(items, capability, spent, capability.disclosure)


async def transcribe_voice(data: bytes, content_type: str) -> str:
    """The words in a voice note. Raises `httpx.HTTPError` when the provider fails."""
    settings = get_settings()
    if not settings.sarvam_api_key:
        raise RuntimeError("no speech-to-text credential")
    form = {"model": STT_MODEL, "mode": STT_MODE, "language_code": "unknown"}
    codec = _CODECS.get(content_type.split(";")[0].strip().lower())
    if codec:
        form["input_audio_codec"] = codec
    async with httpx.AsyncClient(timeout=STT_TIMEOUT_S, follow_redirects=False) as client:
        response = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": settings.sarvam_api_key},
            data=form,
            files={"file": ("voice-note", data, content_type)},
        )
        response.raise_for_status()
        body = response.json()
    transcript = body.get("transcript") if isinstance(body, dict) else None
    return str(transcript or "").strip()


async def _meter_ocr(tenant_id: UUID, model: str, prompt: int | None, output: int | None) -> None:
    if prompt is None or output is None:
        log.warning("kb_teach_ocr_unmeterable", extra={"tenant_id": str(tenant_id)})
        return
    async with tenant_session(tenant_id) as session:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=prompt,
            tokens_out=output,
            model=model,
            feature=ASSIST_FEATURE_KB_OCR,
        )


async def read_upload(
    tenant_id: UUID, *, data: bytes, input_kind: str, content_type: str, filename: str
) -> str:
    """The text of a photo, a file or a voice note. Raises `UnreadableError` with a code."""
    if input_kind == "voice":
        try:
            return await transcribe_voice(data, content_type)
        except (httpx.HTTPError, RuntimeError, ValueError) as failure:
            log.warning("kb_teach_stt_failed", extra={"error": type(failure).__name__})
            raise UnreadableError("voice_unreadable") from failure
    kind = (
        "image"
        if input_kind == "photo"
        else classify_upload(filename=filename, content_type=content_type)
    )
    try:
        if kind == "image":
            extracted = await ocr_images(
                [OcrImage(data=data, mime_type=content_type or "image/jpeg", position=1)]
            )
        else:
            extracted = extract_document(data, kind)  # type: ignore[arg-type]
    except OcrUnavailableError as unavailable:
        log.error("kb_teach_ocr_unavailable", extra={"reason": unavailable.reason})
        raise UnreadableError("photo_reading_unavailable") from unavailable
    except DocumentRefusedError as refused:
        if isinstance(refused, PaidOcrUnusableError):
            await _meter_ocr(tenant_id, refused.model, refused.prompt_tokens, refused.output_tokens)
        raise UnreadableError("unreadable") from refused
    if extracted.model is not None:
        await _meter_ocr(
            tenant_id, extracted.model, extracted.prompt_tokens, extracted.output_tokens
        )
    return extracted.text


class UnreadableError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _set(tenant_id: UUID, teaching_id: UUID, sql: str, **params: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), {"id": teaching_id, **params})


async def _fail(tenant_id: UUID, teaching_id: UUID, code: str) -> None:
    await _set(
        tenant_id,
        teaching_id,
        "UPDATE kb_teachings SET status = 'failed', error_code = :code, completed_at = now(), "
        "updated_at = now() WHERE id = :id AND status IN ('reading', 'sorting')",
        code=code,
    )


async def run_kb_teaching(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim a queued teaching, read it if needed, and sort it for review."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    teaching_id = UUID(str(payload["teaching_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE kb_teachings SET status = CASE WHEN words IS NULL THEN 'reading' "
                    "ELSE 'sorting' END, updated_at = now() "
                    "WHERE id = :id AND status = 'queued' "
                    "RETURNING status, input_kind, words, object_key, content_type, filename"
                ),
                {"id": teaching_id},
            )
        ).first()
    if claimed is None:
        return "not_queued"
    status, input_kind, words, object_key, content_type, filename = claimed

    try:
        if status == "reading":
            data = await read_kb_object(str(object_key)) if object_key else None
            if data is None:
                await _fail(tenant_id, teaching_id, "upload_missing")
                return "failed"
            try:
                words = await read_upload(
                    tenant_id,
                    data=data,
                    input_kind=str(input_kind),
                    content_type=str(content_type or ""),
                    filename=str(filename or "upload"),
                )
            except UnreadableError as unreadable:
                await _fail(tenant_id, teaching_id, unreadable.code)
                return "failed"
            # The bytes have done their job; the words are what the owner reviews.
            await delete_objects([str(object_key)])
            words = (words or "").strip()[:MAX_TEACH_WORDS]
            if not words:
                await _fail(
                    tenant_id,
                    teaching_id,
                    "nothing_heard" if input_kind == "voice" else "nothing_read",
                )
                return "failed"
            if input_kind == "voice":
                await _set(
                    tenant_id,
                    teaching_id,
                    "UPDATE kb_teachings SET status = 'heard', words = :words, object_key = NULL, "
                    "updated_at = now() WHERE id = :id AND status = 'reading'",
                    words=words,
                )
                return "heard"
            await _set(
                tenant_id,
                teaching_id,
                "UPDATE kb_teachings SET status = 'sorting', words = :words, object_key = NULL, "
                "updated_at = now() WHERE id = :id AND status = 'reading'",
                words=words,
            )

        async with tenant_session(tenant_id) as session:
            tenant_leg = await account_assist_leg(session)
            quota = await read_ai_quota(session, tenant_id=tenant_id)
        exhausted = quota.at_ceiling or quota.platform_paused
        capability = assist_capability(tenant_leg=tenant_leg, quota_exhausted=exhausted)
        result = await sort_words(
            str(words), capability=capability, tenant_leg=tenant_leg, quota_exhausted=exhausted
        )
        async with tenant_session(tenant_id) as session:
            if result.capability.available or result.usage is not None:
                await crm_assist.meter_assist(
                    session,
                    tenant_id=tenant_id,
                    ref=new_assist_ref(),
                    result=result,
                    feature=ASSIST_FEATURE_KB_TEACH,
                )
            await session.execute(
                text(
                    "UPDATE kb_teachings SET status = 'ready', items = CAST(:items AS jsonb), "
                    "disclosure = :note, completed_at = now(), updated_at = now() "
                    "WHERE id = :id AND status = 'sorting'"
                ),
                {"id": teaching_id, "items": json.dumps(result.items), "note": result.note},
            )
    except Exception:
        log.exception("kb_teach_crashed", extra={"teaching_id": str(teaching_id)})
        await _fail(tenant_id, teaching_id, "crashed")
        return "failed"
    log.info(
        "kb_teach_sorted",
        extra={"teaching_id": str(teaching_id), "items": len(result.items)},
    )
    return "ready"


__all__ = [
    "JOB_NAME",
    "SYSTEM_PROMPT",
    "items_from_model",
    "run_kb_teaching",
    "sort_words",
    "transcribe_voice",
    "unsorted_items",
]
