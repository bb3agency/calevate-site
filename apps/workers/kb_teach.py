"""Hears or sorts one teaching from the teach box (`apps/api/teach/teaching.py`).

1. HEAR, when the owner recorded a voice note: our speech-to-text sub-processor writes the
   words (metered at our cost as `kb_teach_voice`, absorbed), and the teaching STOPS at
   `heard`: the words go back into the teach box for the owner to check. Photos and files
   are read by Pip since D-821 and are never uploaded here.
2. SORT words Pip was asked to teach into facts and rules with the dashboard-assist ladder
   (`script_assist.ask_json`: the account's Gemini leg or Azure, then the disclosed
   standby), metered against the client's AI allowance as `kb_teach`. When the allowance
   is used up or no model answers, the words come back unsorted, one line each,
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
from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.teach.models import MAX_FACT_CHARS, MAX_RULE_CHARS, MAX_TEACH_WORDS
from apps.api.teach.teaching import ASSIST_FEATURE_KB_TEACH, TEACH_JOB
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    QUOTA_EXHAUSTED_REASON,
    AssistCapability,
    PaidTurn,
    SpentRefusalError,
    assist_capability,
)
from apps.workers.script_assist import ask_json
from apps.workers.speech_to_text import meter_clip
from apps.workers.speech_to_text import transcribe as transcribe_voice
from apps.workers.storage import delete_objects, read_kb_object

log = get_logger(__name__)

JOB_NAME: Final = TEACH_JOB

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
    #: For `crm.assist.meter_assist`: who answered and what that answer cost.
    capability: AssistCapability
    usage: TokenUsage | None
    note: str | None
    #: The answering model, for the meter (`JsonAnswer.model`).
    model: str | None = None
    #: Paid legs that answered unusably first (`crm/assist.meter_earlier`).
    earlier: tuple[PaidTurn, ...] = ()
    #: Did a model write `items`? False for the unsorted fallback.
    answered: bool = False


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


def _sorted_items(raw: dict[str, Any]) -> list[dict[str, str]] | None:
    """`items_from_model`, or None when nothing usable came back, so the ladder's next leg
    gets its chance."""
    return items_from_model(raw) or None


async def sort_words(
    words: str, *, capability: AssistCapability, tenant_leg: Any, quota_exhausted: bool
) -> Sorted:
    """Facts and rules from the owner's words, on the dashboard AI ladder every assist uses
    (`script_assist.ask_json`): the account's Gemini leg or Azure, then the disclosed standby.
    Nothing answering leaves the words unsorted, one fact per line, with a note saying so."""
    if not capability.available:
        note = QUOTA_NOTE if capability.reason == QUOTA_EXHAUSTED_REASON else UNSORTED_NOTE
        return Sorted(unsorted_items(words), capability, None, note)
    try:
        answer = await ask_json(
            words,
            SYSTEM_PROMPT,
            parse=_sorted_items,
            azure_format={
                "type": "json_schema",
                "json_schema": {"name": "teach_sort", "strict": True, "schema": _SCHEMA},
            },
            tenant_leg=tenant_leg,
            quota_exhausted=quota_exhausted,
            max_tokens=SORT_MAX_TOKENS,
            temperature=0.1,
            health_leg="teach",
        )
    except ProblemError as refused:
        log.info("kb_teach_unsorted", extra={"reason": refused.code})
        earlier = refused.earlier if isinstance(refused, SpentRefusalError) else ()
        return Sorted(unsorted_items(words), capability, None, UNSORTED_NOTE, earlier=earlier)
    return Sorted(
        answer.value,
        answer.capability,
        answer.usage,
        answer.capability.disclosure,
        model=answer.model,
        earlier=answer.earlier,
        answered=True,
    )


#: `usage_events.meta.feature` for transcribing a teach-box voice note. Absorbed (founder,
#: 11 Oct 2026): our cost, never the client's allowance or wallet.
ASSIST_FEATURE_KB_VOICE: Final = "kb_teach_voice"


async def read_upload(tenant_id: UUID, *, data: bytes, input_kind: str, content_type: str) -> str:
    """The words in a voice note. Raises `UnreadableError` with a code.

    Photos and files are read by Pip since D-821 and are never uploaded here; a row of
    either kind queued before then is reported unreadable rather than read."""
    if input_kind != "voice":
        raise UnreadableError("unreadable")
    try:
        heard = await transcribe_voice(data, content_type)
    except (httpx.HTTPError, RuntimeError, ValueError) as failure:
        log.warning("kb_teach_stt_failed", extra={"error": type(failure).__name__})
        raise UnreadableError("voice_unreadable") from failure
    await meter_clip(tenant_id, feature=ASSIST_FEATURE_KB_VOICE)
    return heard


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
    status, input_kind, words, object_key, content_type, _filename = claimed

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
                )
            except UnreadableError as unreadable:
                await _fail(tenant_id, teaching_id, unreadable.code)
                return "failed"
            # The bytes have done their job; the words are what the owner reviews.
            await delete_objects([str(object_key)])
            words = (words or "").strip()[:MAX_TEACH_WORDS]
            if not words:
                await _fail(tenant_id, teaching_id, "nothing_heard")
                return "failed"
            # A voice note STOPS here: its words go back into the teach box for the owner
            # to check, and Pip sorts what they send it (D-821).
            await _set(
                tenant_id,
                teaching_id,
                "UPDATE kb_teachings SET status = 'heard', words = :words, object_key = NULL, "
                "updated_at = now() WHERE id = :id AND status = 'reading'",
                words=words,
            )
            return "heard"

        async with tenant_session(tenant_id) as session:
            tenant_leg = await account_assist_leg(session)
            quota = await read_ai_quota(session, tenant_id=tenant_id)
        exhausted = quota.at_ceiling or quota.platform_paused
        capability = assist_capability(tenant_leg=tenant_leg, quota_exhausted=exhausted)
        result = await sort_words(
            str(words), capability=capability, tenant_leg=tenant_leg, quota_exhausted=exhausted
        )
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_earlier(
                session,
                tenant_id=tenant_id,
                earlier=result.earlier,
                feature=ASSIST_FEATURE_KB_TEACH,
            )
            if result.answered:
                await crm_assist.meter_assist(
                    session,
                    tenant_id=tenant_id,
                    ref=new_assist_ref(),
                    result=result,
                    feature=ASSIST_FEATURE_KB_TEACH,
                    model=result.model,
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
