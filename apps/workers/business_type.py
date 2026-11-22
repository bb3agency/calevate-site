"""Bring an account's agents to its business type, and suggest a type where none was chosen.

Queued through the outbox by `admin/business_type.queue_apply` (an operator confirmed a
type) and by migration `d7a3c91e5b20` (every account that had `clinic` by default, and
Raghava Organics). Three steps, each idempotent, so a redelivery repeats nothing harmful:

1. **Lead details.** A confirmed account's one AI draft is asked for once its business says
   what it sells (`lead_fields.maybe_request_draft`). Nothing here writes a list: the type
   decides the business's starting set, which new campaigns and lines copy, and which
   existing ones take the new set is the operator's or owner's choice on Lead details
   (D-1029).
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

from calevate_shared import verticals
from calevate_shared.business_frame import BUSINESS_KIND
from sqlalchemy import text

from apps.api.admin.business_type import record_suggestion
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.lead_fields import maybe_request_draft
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
    f"You read what one {BUSINESS_KIND} says about itself and choose the ONE business "
    "type that fits it best, from this list (key: meaning): "
    + "; ".join(f"{key}: {label}" for key, label in verticals.labels().items())
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
                "business_type": {"type": "string", "enum": list(verticals.all_keys())},
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
    if not verticals.is_known(business_type):
        return None
    reason = " ".join(str(raw.get("reason", "")).split())[:MAX_REASON_CHARS]
    return business_type, reason


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


async def _ask_for_draft(tenant_id: UUID) -> bool:
    """Step 1. Queues the account's AI draft when its type is confirmed (an unconfirmed
    account stays on the neutral core until a person chooses). Returns whether one was."""
    async with tenant_session(tenant_id) as session:
        confirmed = (
            await session.execute(
                text(
                    "SELECT unconfirmed_business_type IS NULL FROM organizations "
                    "WHERE id = :tid AND deleted_at IS NULL"
                ),
                {"tid": tenant_id},
            )
        ).scalar()
        if not confirmed:
            return False
        return await maybe_request_draft(session, tenant_id=tenant_id, requested_by=None)


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
    replaced = changed = refused = crashed = 0
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
        except Exception as exc:
            crashed += 1
            log.warning(
                "business_type_recompile_crashed",
                extra={"agent_id": str(agent_id), "error": type(exc).__name__},
            )
    if crashed:
        # After every other agent had its turn; the queue retries the job, and each step
        # finds nothing left to do on the agents already brought over.
        raise RuntimeError(f"{crashed} agent(s) could not be brought to the business type")
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
    # The account's own dashboard leg, as every other dashboard assist reads it: without it
    # the ladder skipped the Gemini rung and a deployment with no Azure leg answered on the
    # standby.
    async with tenant_session(tenant_id) as session:
        tenant_leg = await account_assist_leg(session)
    try:
        answer: JsonAnswer[tuple[str, str]] = await ask_json(
            description,
            SUGGEST_INSTRUCTION,
            parse=suggestion_from_model,
            azure_format=_SUGGEST_SCHEMA,
            tenant_leg=tenant_leg,
            max_tokens=200,
            temperature=0.0,
        )
    except ProblemError as exc:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=exc, feature=ASSIST_FEATURE_BUSINESS_TYPE
            )
        return _log_suggestion(tenant_id, asked=True, outcome=OUTCOME_UNAVAILABLE, code=exc.code)
    business_type, reason = answer.value
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session,
            tenant_id=tenant_id,
            earlier=answer.earlier,
            feature=ASSIST_FEATURE_BUSINESS_TYPE,
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_BUSINESS_TYPE,
            model=answer.model,
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
    drafted = await _ask_for_draft(tenant_id)
    replaced, recompiled, refused = await _recompile_scripts(tenant_id)
    # Read again AFTER step 1, never from its own read: the suggestion step's
    # condition is the account's state when it runs, and a skip is logged with its reason.
    suggestion = await _suggest(tenant_id)
    log.info(
        "business_type_applied",
        extra={
            "tenant_id": str(tenant_id),
            "draft_queued": drafted,
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
    "suggestion_from_model",
]
