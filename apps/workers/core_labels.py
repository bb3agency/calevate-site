"""Name the six core lead details for ONE business, once, from what it says about itself.

Every lead carries the same core (`calevate_shared.lead_fields.CORE_LEAD_FIELDS`), so the
caller notice, the one phone-holding field and every reader share one meaning. What the
client reads them as should be theirs: a crop-records business reads "What they want" as
"Crop issue". This asks the model for those names; the keys and the instruction the
extraction model reads never change, and the owner may rename any of them afterwards
(`agents/lead_fields.save_core_labels`).

Queued by `agents/lead_fields.maybe_name_core_details` (and, for accounts that existed
before, by migration f7d2b9c4e1a8). One request on the dashboard AI ladder
(`script_assist.ask_json`), no retry: a refusal frees the claim so the next profile save
asks again. What the model sees is the business's own redacted words about itself
(`lead_fields_draft.business_context`), never a caller, and nothing of it is logged.
Metered at our cost under `ASSIST_FEATURE_LEAD_FIELDS` and absorbed, like the lead-details
draft it sits beside.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from calevate_shared.lead_fields import CORE_LABEL_MAX_CHARS, CORE_LEAD_FIELDS, clean_core_labels
from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_LEAD_FIELDS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.lead_fields_draft import business_context
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: The ARQ name; `agents/lead_fields.NAME_CORE_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "name_core_details"

NAME_TIMEOUT_S: Final = 30.0
NAME_MAX_TOKENS: Final = 400

_KEYS: Final = tuple(f.key for f in CORE_LEAD_FIELDS)
_MEANINGS: Final = "; ".join(f"{f.key}: {f.label} ({f.reason})" for f in CORE_LEAD_FIELDS)

#: Pinned by `tests/core_labels_test.py`: same meaning, the business's words, a column header.
SYSTEM_PROMPT: Final = (
    "An AI phone agent writes down the same six details after every call for a small "
    "Indian business. Rename each detail so THIS business's owner recognises it at a glance "
    "on their leads list, in their trade's plain English words, while it still means exactly "
    "the same thing. The six, with what each holds: "
    f"{_MEANINGS}. "
    f"Each name: 1 to 3 words, at most {CORE_LABEL_MAX_CHARS} characters, a column heading, "
    "no two the same. Keep a detail's own name when nothing fits better (a name and a "
    "language rarely need another word). Never change what a detail holds, never name a "
    "product, price or person, and never add a detail. "
    'Return ONLY JSON: {"labels": {' + ", ".join(f'"{k}": str' for k in _KEYS) + "}}."
)

_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "object",
            "properties": {key: {"type": "string"} for key in _KEYS},
            "required": list(_KEYS),
            "additionalProperties": False,
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def labels_from_model(raw: dict[str, Any]) -> dict[str, str] | None:
    """The model's names, cleaned as an owner's would be; None when none differs from the
    platform's, so the ladder's next leg gets its chance."""
    labels = raw.get("labels")
    named = clean_core_labels(labels if isinstance(labels, dict) else None)
    return named or None


async def _claim(tenant_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE organizations SET core_labels_drafted_at = now() WHERE id = :tid "
                    "AND core_labels_drafted_at IS NULL AND core_field_labels = '{}'::jsonb "
                    "RETURNING id"
                ),
                {"tid": tenant_id},
            )
        ).first()
    return claimed is not None


async def _release(tenant_id: UUID) -> None:
    """Nothing usable came back: free the claim so the next profile save asks again."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET core_labels_drafted_at = NULL WHERE id = :tid "
                "AND core_field_labels = '{}'::jsonb"
            ),
            {"tid": tenant_id},
        )


async def _store(tenant_id: UUID, answer: JsonAnswer[dict[str, str]]) -> bool:
    """Store the names and meter the answer in ONE transaction. Never over names the owner
    set while the model was answering."""
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "UPDATE organizations SET core_field_labels = CAST(:labels AS jsonb) "
                    "WHERE id = :tid AND core_field_labels = '{}'::jsonb RETURNING id"
                ),
                {"tid": tenant_id, "labels": json.dumps(answer.value)},
            )
        ).first()
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=ASSIST_FEATURE_LEAD_FIELDS
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_LEAD_FIELDS,
            model=answer.model,
        )
    return stored is not None


async def name_core_details(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the one naming, ask the model once, store what came back."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    if not await _claim(tenant_id):
        # Named already, by the model or the owner.
        return "not_needed"
    try:
        description, _vertical = await business_context(tenant_id)
        async with tenant_session(tenant_id) as session:
            tenant_leg = await account_assist_leg(session)
        try:
            answer = await ask_json(
                description,
                SYSTEM_PROMPT,
                parse=labels_from_model,
                azure_format={
                    "type": "json_schema",
                    "json_schema": {"name": "core_labels", "strict": True, "schema": _SCHEMA},
                },
                tenant_leg=tenant_leg,
                max_tokens=NAME_MAX_TOKENS,
                temperature=0.2,
                timeout_s=NAME_TIMEOUT_S,
                health_leg="lead_fields",
            )
        except ProblemError as refused:
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session,
                    tenant_id=tenant_id,
                    refusal=refused,
                    feature=ASSIST_FEATURE_LEAD_FIELDS,
                )
            await _release(tenant_id)
            log.info(
                "core_labels_refused", extra={"tenant_id": str(tenant_id), "reason": refused.code}
            )
            return "refused"
        stored = await _store(tenant_id, answer)
    except Exception:
        log.exception("core_labels_crashed", extra={"tenant_id": str(tenant_id)})
        await _release(tenant_id)
        return "failed"
    log.info(
        "core_labels_named",
        extra={"tenant_id": str(tenant_id), "named": len(answer.value), "stored": stored},
    )
    return "named" if stored else "owner_named"


__all__ = ["JOB_NAME", "SYSTEM_PROMPT", "labels_from_model", "name_core_details"]
