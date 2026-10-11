"""Bring an account's agents to its business type, and suggest a type where none was chosen.

Queued through the outbox by `admin/business_type.queue_apply` (an operator confirmed a
type) and by migration `d7a3c91e5b20` (every account that had `clinic` by default, and
Raghava Organics). Three steps, each idempotent, so a redelivery repeats nothing harmful:

1. **Lead details.** An agent with no business fields gets the type's standard set (or a
   custom business's finished AI draft). With `replace_clinic_default`, an agent whose
   fields are a subset of the clinic set, on an account that is not a confirmed clinic, is
   treated as carrying the old default and gets the type's set instead (the neutral core
   alone for an unconfirmed account). Fields somebody chose are never touched. Each write
   is a new schema version (`agents/lead_fields.replace_business_fields`).
2. **Scripts.** An agent still carrying another business type's ready-made starter, exactly
   as written, gets the confirmed type's starter (`agents/starters.replace_unedited_starter`);
   a script anybody changed is left alone. Every agent's script is then recompiled so "what
   to collect" matches, and a live agent is republished through the one publish path
   (`script_builder.recompile_collect`). One transaction per agent, so one agent the voice
   platform refuses does not hold back the others.
3. **Suggestion.** For an account still unconfirmed with no suggestion on file, the
   dashboard AI chain (`workers/script_assist.ask_json`: Azure, then the disclosed Sarvam
   fallback) reads the business's own description of itself, redacted (D-127 G-1/G-2),
   and suggests ONE type with a short reason. It is stored for the operator's "Business
   type not confirmed" prompt and changes nothing by itself. Metered as
   `ASSIST_FEATURE_BUSINESS_TYPE`, absorbed.

`suggest_only` (the operator's "Suggest again", `admin/business_type.queue_suggestion`)
runs step 3 alone and asks even when a suggestion is on file. Every run logs
`business_type_suggestion` with whether it asked and the outcome, ids and codes only.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from scripts.seed import BUSINESS_TYPE_LABELS
from sqlalchemy import text

from apps.api.admin.business_type import CLINIC, CLINIC_DEFAULT_KEYS, record_suggestion
from apps.api.agents.lead_fields import (
    agents_with_fields,
    maybe_request_draft,
    replace_business_fields,
    starting_business_fields,
)
from apps.api.agents.script_builder import recompile_collect
from apps.api.agents.starters import replace_unedited_starter
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_BUSINESS_TYPE
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.lead_fields_draft import business_context
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: `admin/business_type.APPLY_JOB`.
JOB_NAME: Final = "apply_business_type"

#: Long enough to say why in one sentence an operator reads beside the suggestion.
MAX_REASON_CHARS: Final = 200

SUGGEST_INSTRUCTION: Final = (
    "You read what one small Indian business says about itself and choose the ONE business "
    "type that fits it best, from this list (key: meaning): "
    + "; ".join(f"{key}: {label}" for key, label in BUSINESS_TYPE_LABELS.items())
    + ". Choose from what the business sells and does, never from a guess about its name "
    "alone. If the description says too little to tell, choose custom. Give a reason of one "
    "short sentence naming what in the description decided it. "
    'Return ONLY JSON: {"business_type": str, "reason": str}.'
)

_SUGGEST_SCHEMA: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "calevate_business_type",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "business_type": {"type": "string", "enum": list(BUSINESS_TYPE_LABELS)},
                "reason": {"type": "string"},
            },
            "required": ["business_type", "reason"],
            "additionalProperties": False,
        },
    },
}


def suggestion_from_model(raw: dict[str, Any]) -> tuple[str, str] | None:
    """The model's answer as (type, reason), or None when it named no type we offer."""
    business_type = str(raw.get("business_type", "")).strip()
    if business_type not in BUSINESS_TYPE_LABELS:
        return None
    reason = " ".join(str(raw.get("reason", "")).split())[:MAX_REASON_CHARS]
    return business_type, reason


def carries_clinic_default(fields: list[ExtractionField]) -> bool:
    """Business fields that are the clinic set, whole or trimmed, and nothing else."""
    return bool(fields) and {f.key for f in fields} <= CLINIC_DEFAULT_KEYS


#: Why step 3 did not ask, or what came of asking. Logged as `outcome`.
SKIP_CONFIRMED: Final = "skipped_confirmed"
SKIP_ALREADY_SUGGESTED: Final = "skipped_already_suggested"
OUTCOME_STORED: Final = "stored"
OUTCOME_NOT_STORED: Final = "not_stored_confirmed_meanwhile"
OUTCOME_UNAVAILABLE: Final = "unavailable"


async def _suggestion_state(tenant_id: UUID) -> tuple[bool, bool]:
    """(still unconfirmed, a suggestion is on file). A missing account reads as confirmed."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT unconfirmed_business_type IS NOT NULL, "
                    "suggested_business_type IS NOT NULL FROM organizations "
                    "WHERE id = :tid AND deleted_at IS NULL"
                ),
                {"tid": tenant_id},
            )
        ).first()
    return (False, False) if row is None else (bool(row[0]), bool(row[1]))


async def _refit_fields(tenant_id: UUID, *, replace_clinic_default: bool) -> int:
    """Step 1. Returns the number of agents whose fields were written."""
    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text(
                    "SELECT vertical_template, unconfirmed_business_type "
                    "FROM organizations WHERE id = :tid AND deleted_at IS NULL"
                ),
                {"tid": tenant_id},
            )
        ).first()
        if org is None:
            return 0
        vertical = None if org[0] is None else str(org[0])
        unconfirmed = org[1] is not None
        if unconfirmed:
            # Neutral until a person chooses: the core alone, never the clinic's set.
            target: list[ExtractionField] = []
        else:
            target = await starting_business_fields(session, tenant_id=tenant_id, vertical=vertical)
            await maybe_request_draft(session, tenant_id=tenant_id, requested_by=None)
        fill: list[UUID] = []
        replace: list[UUID] = []
        for agent in await agents_with_fields(session):
            fields = agent["fields"]
            if not fields and target:
                fill.append(agent["id"])
            elif replace_clinic_default and vertical != CLINIC and carries_clinic_default(fields):
                replace.append(agent["id"])
        written = 0
        if fill or replace:
            writes = await replace_business_fields(
                session, fields=target, agent_ids=[*fill, *replace]
            )
            written = sum(1 for w in writes if w.changed)
        return written


async def _recompile_scripts(tenant_id: UUID) -> tuple[int, int, int]:
    """Step 2. Returns (starters replaced, agents recompiled, agents the platform refused)."""
    async with tenant_session(tenant_id) as session:
        agent_ids = [
            UUID(str(r[0]))
            for r in (
                await session.execute(
                    text(
                        "SELECT id FROM agents WHERE deleted_at IS NULL "
                        "AND system_prompt_id IS NOT NULL ORDER BY created_at"
                    )
                )
            ).all()
        ]
    replaced = changed = refused = 0
    for agent_id in agent_ids:
        try:
            async with tenant_session(tenant_id) as session:
                if await replace_unedited_starter(session, tenant_id=tenant_id, agent_id=agent_id):
                    replaced += 1
                elif await recompile_collect(session, tenant_id=tenant_id, agent_id=agent_id):
                    changed += 1
        except ProblemError as exc:
            refused += 1
            log.warning(
                "business_type_recompile_refused",
                extra={"agent_id": str(agent_id), "reason": exc.code},
            )
    return replaced, changed, refused


async def _suggest(tenant_id: UUID, *, again: bool = False) -> str:
    """Step 3. Asks for a suggestion when the account is unconfirmed and has none on file
    (or `again`), and returns the outcome it logged."""
    unconfirmed, on_file = await _suggestion_state(tenant_id)
    if not unconfirmed:
        return _log_suggestion(tenant_id, asked=False, outcome=SKIP_CONFIRMED)
    if on_file and not again:
        return _log_suggestion(tenant_id, asked=False, outcome=SKIP_ALREADY_SUGGESTED)
    description, _ = await business_context(tenant_id, include_type=False)
    try:
        answer: JsonAnswer[tuple[str, str]] = await ask_json(
            description,
            SUGGEST_INSTRUCTION,
            parse=suggestion_from_model,
            azure_format=_SUGGEST_SCHEMA,
            max_tokens=200,
            temperature=0.0,
        )
    except ProblemError as exc:
        return _log_suggestion(tenant_id, asked=True, outcome=OUTCOME_UNAVAILABLE, code=exc.code)
    business_type, reason = answer.value
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_BUSINESS_TYPE,
        )
        stored = await record_suggestion(
            session, tenant_id=tenant_id, business_type=business_type, reason=reason
        )
    return _log_suggestion(
        tenant_id,
        asked=True,
        outcome=OUTCOME_STORED if stored else OUTCOME_NOT_STORED,
        code=business_type if stored else None,
    )


def _log_suggestion(tenant_id: UUID, *, asked: bool, outcome: str, code: str | None = None) -> str:
    """One line per run of step 3, so "No suggestion yet" can always be explained."""
    log.info(
        "business_type_suggestion",
        extra={"tenant_id": str(tenant_id), "asked": asked, "outcome": outcome, "code": code},
    )
    return outcome


async def apply_business_type(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    if payload.get("suggest_only"):
        await _suggest(tenant_id, again=True)
        return "done"
    written = await _refit_fields(
        tenant_id, replace_clinic_default=bool(payload.get("replace_clinic_default"))
    )
    replaced, recompiled, refused = await _recompile_scripts(tenant_id)
    # Read again AFTER the refit, never from the refit's own read: the suggestion step's
    # condition is the account's state when it runs, and a skip is logged with its reason.
    suggestion = await _suggest(tenant_id)
    log.info(
        "business_type_applied",
        extra={
            "tenant_id": str(tenant_id),
            "fields_written": written,
            "starters_replaced": replaced,
            "scripts_recompiled": recompiled,
            "scripts_refused": refused,
            "suggestion": suggestion,
        },
    )
    return "done" if not refused else "partial"


__all__ = [
    "JOB_NAME",
    "SUGGEST_INSTRUCTION",
    "apply_business_type",
    "carries_clinic_default",
    "suggestion_from_model",
]
