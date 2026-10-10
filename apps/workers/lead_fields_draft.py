"""Draft a custom business's lead fields ONCE, from what the platform knows about it.

Founder decision 15 (10 Oct 2026): a business that fits no known type gets its business
fields drafted by AI from everything known about it at that point — its profile, services,
FAQs, booking rules, knowledge titles and what its agents do — and never again. The client
edits them freely afterwards.

Enqueued through the outbox by `agents/lead_fields.request_draft`, in the transaction that
queued the `lead_field_drafts` row. One attempt and no retry ladder: a failed draft marks
the row `failed` with a code, and the client or an operator asks again.

WHAT THE MODEL SEES. Only the business's own words about itself (the class
`workers/script_assist` serves), never a caller, a lead or a transcript. It still passes
through `redact()` first, because a business types its own phone numbers and addresses
into FAQs and booking rules and the draft needs none of them. Nothing of it is logged
(hard rule 6).

WHAT IT COSTS. One completion per business, ever. Recorded on the tenant's ledger under
`billing.models.ASSIST_FEATURE_LEAD_FIELDS` at our cost when the model's price is
billable (hard rule 7), and absorbed: it never counts against the client's AI allowance.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, cast
from uuid import UUID

import httpx
from calevate_shared.engine import SARVAM_DEFAULT_LLM, azure_openai_base_url
from calevate_shared.extraction import ExtractionField, FieldType, is_phone_field
from calevate_shared.lead_fields import CORE_KEYS, CORE_LEAD_FIELDS, OUTPUT_KEYS
from sqlalchemy import text

from apps.api.agents.extraction_routes import (
    MAX_ENUM_VALUE_LEN,
    MAX_LABEL_LEN,
    MAX_REASON_LEN,
)
from apps.api.agents.lead_fields import (
    business_type_label,
    replace_business_fields,
)
from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.billing.models import ASSIST_FEATURE_LEAD_FIELDS
from apps.api.billing.rates import llm_price_is_billable
from apps.api.core import provider_health
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.session import tenant_session
from apps.api.tenancy.business_profile import load_profile
from apps.workers import chat
from apps.workers.chat import ChatOutcome
from apps.workers.extraction import SARVAM_CHAT_URL, _first_json_object, azure_credentials
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The ARQ name; `agents/lead_fields.DRAFT_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "draft_lead_fields"

#: Nobody is waiting on this, but a hung provider must not hold a worker slot.
DRAFT_TIMEOUT_S: Final = 45.0
#: A draft is at most `MAX_DRAFTED_FIELDS` short objects; this only fires on a runaway.
DRAFT_MAX_TOKENS: Final = 1500
#: Enough to be useful, few enough that the client reads every one.
MAX_DRAFTED_FIELDS: Final = 6
#: The business description handed to the model, in characters.
MAX_CONTEXT_CHARS: Final = 6000

_CORE_LABELS = ", ".join(f.label.lower() for f in CORE_LEAD_FIELDS)

#: The instruction. Pinned by `tests/lead_fields_test.py`: no repeat of the core, no
#: invented facts, nothing sensitive, short spoken-business vocabulary.
SYSTEM_PROMPT: Final = (
    "You choose the details an AI phone receptionist should write down after each call "
    "for one small Indian business. Every call already records: "
    f"{_CORE_LABELS}. Never repeat any of those. "
    f"Propose between 3 and {MAX_DRAFTED_FIELDS} more details that THIS business needs "
    "to follow up a caller, chosen from what it sells and how it works. "
    "For each give: label (2 to 4 plain English words, as a column heading a shop owner "
    "understands), type (one of text, number, bool, enum, date), reason (one sentence "
    "telling the note-taker exactly what to listen for in the caller's own words), "
    "required (true for at most one detail, the one every caller gives), and choices "
    "(2 to 6 short values, only when type is enum; otherwise an empty list). "
    "Use bool only for a clear yes/no the caller states. Use number only for a plain "
    "count or amount, and say the unit in the label. "
    "Never ask for a phone number, email, address proof, Aadhaar, PAN, bank or card "
    "details, passwords, religion, caste, or health conditions unless the business is "
    "itself a health business. Do not invent prices, products or services the "
    "description does not mention. "
    'Return ONLY JSON: {"fields": [{"label": str, "type": str, "reason": str, '
    '"required": bool, "choices": [str]}]}.'
)

_DRAFT_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "type": {"type": "string", "enum": ["text", "number", "bool", "enum", "date"]},
                    "reason": {"type": "string"},
                    "required": {"type": "boolean"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "type", "reason", "required", "choices"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _key_for(label: str, taken: set[str]) -> str | None:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    base = re.sub(r"^[^a-z]+", "", base)[:36].rstrip("_")
    if not base:
        return None
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key if _KEY_RE.match(key) else None


def fields_from_model(raw: dict[str, Any]) -> list[ExtractionField]:
    """The model's answer as fields the editor and the extractor accept, or fewer.

    Tolerant by design: a malformed item is dropped rather than failing the draft. Dropped
    too: anything that collides with the core or a fixed Leads column, a duplicate, and
    anything the extractor would treat as a phone field (the core already has one).
    """
    items = raw.get("fields")
    if not isinstance(items, list):
        return []
    taken: set[str] = set(CORE_KEYS) | set(FIXED_KEYS) | set(OUTPUT_KEYS)
    labels_seen = {f.label.lower() for f in CORE_LEAD_FIELDS}
    out: list[ExtractionField] = []
    required_used = False
    for item in items:
        if not isinstance(item, dict) or len(out) >= MAX_DRAFTED_FIELDS:
            continue
        label = " ".join(str(item.get("label", "")).split())[:MAX_LABEL_LEN]
        kind = str(item.get("type", "text"))
        if (
            not label
            or label.lower() in labels_seen
            or kind
            not in (
                "text",
                "number",
                "bool",
                "enum",
                "date",
            )
        ):
            continue
        choices = [
            " ".join(str(c).split())[:MAX_ENUM_VALUE_LEN]
            for c in (item.get("choices") or [])
            if str(c).strip()
        ][:6]
        if kind == "enum" and len(choices) < 2:
            kind, choices = "text", []
        key = _key_for(label, taken)
        if key is None:
            continue
        required = bool(item.get("required")) and not required_used
        try:
            field = ExtractionField(
                key=key,
                label=label,
                type=cast(FieldType, kind),
                enum_values=choices if kind == "enum" else None,
                reason=" ".join(str(item.get("reason", "")).split())[:MAX_REASON_LEN],
                required=required,
            )
        except ValueError:
            continue
        if is_phone_field(field):
            continue
        taken.add(key)
        labels_seen.add(label.lower())
        required_used = required_used or required
        out.append(field)
    return out


async def _business_context(tenant_id: UUID) -> tuple[str, str | None]:
    """Everything known about the business, as one redacted description, and its type."""
    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text("SELECT name, vertical_template FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
        profile = await load_profile(session, tenant_id=tenant_id)
        titles = (
            (
                await session.execute(
                    text(
                        "SELECT name FROM kb_sources WHERE status <> 'rejected' "
                        "ORDER BY created_at DESC LIMIT 30"
                    )
                )
            )
            .scalars()
            .all()
        )
        agents = (
            await session.execute(
                text(
                    "SELECT name, direction FROM agents WHERE deleted_at IS NULL "
                    "ORDER BY created_at LIMIT 10"
                )
            )
        ).all()
    name = str(org[0]) if org else ""
    vertical = None if org is None or org[1] is None else str(org[1])
    lines = [f"Business name: {name}", f"Business type: {business_type_label(vertical)}"]
    for item in profile.services[:40]:
        note = f" ({item.notes})" if item.notes else ""
        lines.append(f"Sells or offers: {item.name}{note}")
    for faq in profile.faqs[:15]:
        lines.append(f"Callers ask: {faq.question}")
    roles = sorted({p.role for p in profile.staff if p.role})
    if roles:
        lines.append("Staff roles: " + ", ".join(roles))
    if profile.booking_rules:
        lines.append(f"How orders or bookings are taken: {profile.booking_rules}")
    for branch in profile.branches[:5]:
        lines.append(f"Branch: {branch.label}")
    for title in titles:
        lines.append(f"Knowledge on file: {title}")
    for agent_name, direction in agents:
        job = "answers calls" if direction == "inbound" else "calls leads"
        lines.append(f"Phone agent '{agent_name}' {job}")
    description = redact("\n".join(" ".join(line.split()) for line in lines)).text
    return description[:MAX_CONTEXT_CHARS], vertical


async def _ask(leg: chat.ChatLeg, description: str, *, strict: bool) -> ChatOutcome:
    response_format: dict[str, Any] = (
        {
            "type": "json_schema",
            "json_schema": {"name": "lead_fields_draft", "strict": True, "schema": _DRAFT_SCHEMA},
        }
        if strict
        else {"type": "json_object"}
    )
    return await chat.complete(
        leg,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": description}],
        timeout_s=DRAFT_TIMEOUT_S,
        temperature=0.2,
        response_format=response_format,
        max_tokens=DRAFT_MAX_TOKENS,
    )


async def _draft(description: str) -> tuple[list[ExtractionField], ChatOutcome | None, str | None]:
    """The fields, the paid turn that produced them, and the model it was priced as.

    Azure first, then the Sarvam leg, the order `workers/script_assist` keeps. A turn that
    was answered but unusable is still returned so its cost is recorded.
    """
    settings = get_settings()
    credentials = azure_credentials()
    spent: tuple[ChatOutcome, str] | None = None
    if credentials is not None:
        resource, api_key, deployment = credentials
        leg = chat.ChatLeg(
            url=f"{azure_openai_base_url(resource)}/chat/completions",
            api_key=api_key,
            wire_model=deployment,
            dialect="openai",
        )
        model = settings.azure_openai_model
        try:
            try:
                outcome = await _ask(leg, description, strict=True)
            except httpx.HTTPStatusError as refusal:
                if refusal.response.status_code != 400:
                    raise
                outcome = await _ask(leg, description, strict=False)
            await provider_health.note_success("lead_fields", "azure")
            fields = (
                fields_from_model(_first_json_object(outcome.content))
                if outcome.finish_reason != "length"
                else []
            )
            if fields:
                return fields, outcome, model
            spent = (outcome, model)
        except (httpx.HTTPError, TimeoutError) as failure:
            log.warning(
                "lead_fields_draft_azure_failed", extra=provider_health.failure_fields(failure)
            )
            await provider_health.note_failure("lead_fields", "azure", failure)
    if settings.sarvam_api_key:
        leg = chat.ChatLeg(
            url=SARVAM_CHAT_URL,
            api_key=settings.sarvam_api_key,
            wire_model=SARVAM_DEFAULT_LLM,
            dialect="sarvam",
        )
        try:
            outcome = await _ask(leg, description, strict=False)
        except (httpx.HTTPError, TimeoutError) as failure:
            log.warning(
                "lead_fields_draft_sarvam_failed", extra=provider_health.failure_fields(failure)
            )
        else:
            fields = (
                fields_from_model(_first_json_object(outcome.content))
                if outcome.finish_reason != "length"
                else []
            )
            if fields:
                return fields, outcome, SARVAM_DEFAULT_LLM
            spent = spent or (outcome, SARVAM_DEFAULT_LLM)
    if spent is not None:
        return [], spent[0], spent[1]
    return [], None, None


async def _meter(tenant_id: UUID, outcome: ChatOutcome | None, model: str | None) -> None:
    if outcome is None or model is None:
        return
    if outcome.usage is None:
        log.warning("lead_fields_draft_unmeterable", extra={"tenant_id": str(tenant_id)})
        return
    if not llm_price_is_billable(model):
        log.info("lead_fields_draft_unpriced", extra={"tenant_id": str(tenant_id), "model": model})
        return
    async with tenant_session(tenant_id) as session:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            tokens_out=outcome.usage.output_tokens,
            model=model,
            feature=ASSIST_FEATURE_LEAD_FIELDS,
        )


async def _fail(tenant_id: UUID, code: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE lead_field_drafts SET status = 'failed', error_code = :code, "
                "completed_at = now(), updated_at = now() WHERE status = 'running'"
            ),
            {"code": code},
        )


async def draft_lead_fields(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the queued draft, ask the model once, store and apply what came back."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE lead_field_drafts SET status = 'running', updated_at = now() "
                    "WHERE status = 'queued' RETURNING id"
                )
            )
        ).first()
    if claimed is None:
        # Already drafted, or claimed by an earlier delivery of this message.
        return "not_queued"

    try:
        description, _vertical = await _business_context(tenant_id)
        fields, outcome, model = await _draft(description)
        await _meter(tenant_id, outcome, model)
    except Exception:
        log.exception("lead_fields_draft_crashed", extra={"tenant_id": str(tenant_id)})
        await _fail(tenant_id, "draft_crashed")
        return "failed"

    if not fields:
        await _fail(tenant_id, "no_draft" if outcome is not None else "no_provider")
        return "failed"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE lead_field_drafts SET status = 'done', fields = CAST(:fields AS jsonb), "
                "model = :model, error_code = NULL, completed_at = now(), updated_at = now() "
                "WHERE status = 'running'"
            ),
            {"fields": json.dumps([f.model_dump() for f in fields]), "model": model},
        )
        # Onto every agent that has no business fields of its own yet; an agent whose
        # fields somebody already chose keeps them.
        written = await replace_business_fields(session, fields=fields, only_empty=True)
    log.info(
        "lead_fields_drafted",
        extra={"tenant_id": str(tenant_id), "fields": len(fields), "agents": len(written)},
    )
    return "done"


__all__ = ["JOB_NAME", "SYSTEM_PROMPT", "draft_lead_fields", "fields_from_model"]
