"""Draft one agent's call outcomes ONCE, from the business's details and the agent's job (D-836).

Founder, 20 Oct 2026: outcomes must follow the business and the kind of call, not a fixed list.
The system-fact outcomes (missed, hung up early, call back booked, transferred, needs you) stay
universal and are never drafted; this writes what a call can come to FOR THIS BUSINESS, each
with how far it moves the lead.

Queued through the outbox by `agents/call_outcomes.queue_draft` (at publish, or at the first
call of an agent published before D-836). One run:

1. **Claim** `business_outcomes_draft` from `queued` to `running` (compare-and-swap).
2. **Kept own**: an agent whose owner saved a list in the meantime is left alone, unspent.
3. **May it spend?** A trial account's draft is ours (`..._ABSORBED`); every other account's
   counts against its AI allowance, the D-827 rule (`require_ai_assist`). Used up, or the
   platform brake on: `skipped`, and the agent keeps reading the starting set.
4. **Ask once** on the dashboard AI ladder (`script_assist.ask_json`) over the business's own
   words, redacted (D-127 G-1/G-2). No caller, lead or transcript is read.
5. **Meter and store together**, writing only where `business_outcomes` is still NULL: a list
   the owner saved while the model was answering wins.

Nothing here is logged but ids, codes and counts (hard rule 6).
"""

from __future__ import annotations

import re
from typing import Any, Final
from uuid import UUID

from calevate_shared.business_outcomes import (
    LABEL_MAX,
    LEAD_MOVES,
    MAX_BUSINESS_OUTCOMES,
    MEANING_MAX,
    RESERVED_KEYS,
    BusinessOutcome,
    outcome_key,
)
from pydantic import ValidationError
from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.call_outcomes import dump_outcomes
from apps.api.billing.ai_quota import new_assist_ref, platform_brake_tripped, require_ai_assist
from apps.api.billing.models import (
    ASSIST_FEATURE_BUSINESS_OUTCOMES,
    ASSIST_FEATURE_BUSINESS_OUTCOMES_ABSORBED,
)
from apps.api.billing.trials import trial_billing_active
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.lead_fields_draft import business_context
from apps.workers.pipeline import load_moments_brief
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: The ARQ name; `agents/call_outcomes.DRAFT_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "draft_business_outcomes"

DRAFT_TIMEOUT_S: Final = 45.0
DRAFT_MAX_TOKENS: Final = 1200
#: The description handed to the model, in characters.
MAX_CONTEXT_CHARS: Final = 7000

#: The instruction. English: the labels are what the owner reads on English screens.
SYSTEM_PROMPT: Final = (
    "You name the ways a phone call can end for one small Indian business, as its owner "
    "would want calls sorted. Another system already records these on its own, so never "
    "propose them: the call was missed, the caller hung up early, a call back was booked, "
    "the call was handed to a person, the caller needs a person from the business. "
    f"Propose between 3 and {MAX_BUSINESS_OUTCOMES} outcomes for the calls THIS agent "
    "handles, chosen from what the business sells and what the agent is for. Include one "
    "for a caller who wants to buy, order or book what this business offers, one for a "
    "caller who is interested but did not decide, and one for a caller who is not "
    "interested. For each give: label (2 to 4 plain English words an owner understands, "
    f"at most {LABEL_MAX} characters), meaning (one sentence, at most {MEANING_MAX} "
    "characters, saying what the caller said or did), and lead_status: hot only for a "
    "caller ready to buy now, interested for a caller who wants or is considering what the "
    "business offers, contacted for everything else. Do not invent products or services "
    "the description does not mention. Name no company, brand or technology. "
    'Return ONLY JSON: {"outcomes": [{"label": str, "meaning": str, "lead_status": str}]}.'
)

_DRAFT_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "meaning": {"type": "string"},
                    "lead_status": {"type": "string", "enum": list(LEAD_MOVES)},
                },
                "required": ["label", "meaning", "lead_status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["outcomes"],
    "additionalProperties": False,
}


def outcomes_from_model(raw: dict[str, Any]) -> list[BusinessOutcome]:
    """The model's answer as outcomes the extractor accepts, or fewer.

    Tolerant by design, as `lead_fields_draft.fields_from_model` is: a malformed item, a
    repeated name, an unknown lead move or a name that spells a system outcome is dropped
    rather than failing the draft. Text over its limit is cut at a word.
    """
    items = raw.get("outcomes")
    if not isinstance(items, list):
        return []
    taken: set[str] = set()
    labels: set[str] = set()
    out: list[BusinessOutcome] = []
    for item in items:
        if not isinstance(item, dict) or len(out) >= MAX_BUSINESS_OUTCOMES:
            continue
        label = _clip(str(item.get("label", "")), LABEL_MAX)
        meaning = _clip(str(item.get("meaning", "")), MEANING_MAX)
        move = str(item.get("lead_status", ""))
        if not label or label.casefold() in labels or move not in LEAD_MOVES:
            continue
        if re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") in RESERVED_KEYS:
            continue
        key = outcome_key(label, taken)
        if key is None:
            continue
        try:
            outcome = BusinessOutcome.model_validate(
                {"key": key, "label": label, "meaning": meaning, "lead_status": move}
            )
        except ValidationError:
            continue
        taken.add(key)
        labels.add(label.casefold())
        out.append(outcome)
    return out


def _clip(value: str, limit: int) -> str:
    words = " ".join(value.split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")


def _drafted(raw: dict[str, Any]) -> list[BusinessOutcome] | None:
    """`outcomes_from_model`, or None so the ladder's next leg gets its chance."""
    return outcomes_from_model(raw) or None


async def agent_context(tenant_id: UUID, agent_id: UUID, *, name: str, direction: str) -> str:
    """The business's own description plus what this agent is for, redacted."""
    description, _vertical = await business_context(tenant_id)
    brief = await load_moments_brief(tenant_id, agent_id)
    job = "answers the business's calls" if direction == "inbound" else "calls leads"
    lines = [f"This agent: '{name}', which {job}."]
    if brief.business_line:
        lines.append(f"What the business is, in its script: {brief.business_line}")
    if brief.agent_goal:
        lines.append(f"What the agent is for: {brief.agent_goal}")
    if brief.script_steps:
        lines.append("The agent's steps: " + "; ".join(brief.script_steps))
    agent_part = redact("\n".join(" ".join(line.split()) for line in lines)).text
    return f"{description}\n{agent_part}"[:MAX_CONTEXT_CHARS]


async def _set_state(tenant_id: UUID, agent_id: UUID, state: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET business_outcomes_draft = :state, updated_at = now() "
                "WHERE id = :aid AND business_outcomes_draft = 'running'"
            ),
            {"state": state, "aid": agent_id},
        )


async def _blocked(tenant_id: UUID, *, absorbed: bool) -> bool:
    """True when this run may not spend: the allowance decides a client's run, and only the
    platform AI brake stops one that is ours (`business_copy._may_spend`'s rule)."""
    async with tenant_session(tenant_id) as session:
        if absorbed:
            return await platform_brake_tripped(session)
        try:
            await require_ai_assist(session, tenant_id=tenant_id)
        except ProblemError:
            return True
    return False


async def _store(
    tenant_id: UUID, agent_id: UUID, answer: JsonAnswer[list[BusinessOutcome]], *, feature: str
) -> bool:
    """Meter the answer and store the outcomes in ONE transaction. False when the owner's own
    list got there first; the spend is on the ledger either way."""
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=feature,
            model=answer.model,
        )
        stored = (
            await session.execute(
                text(
                    "UPDATE agents SET business_outcomes = CAST(:outcomes AS jsonb), "
                    "business_outcomes_draft = 'done', updated_at = now() "
                    "WHERE id = :aid AND business_outcomes IS NULL RETURNING id"
                ),
                {"aid": agent_id, "outcomes": dump_outcomes(answer.value)},
            )
        ).first()
        if stored is None:
            await session.execute(
                text(
                    "UPDATE agents SET business_outcomes_draft = 'done', updated_at = now() "
                    "WHERE id = :aid"
                ),
                {"aid": agent_id},
            )
    return stored is not None


async def _run(tenant_id: UUID, agent_id: UUID, *, name: str, direction: str) -> str:
    async with tenant_session(tenant_id) as session:
        absorbed = await trial_billing_active(session, tenant_id=tenant_id)
    if await _blocked(tenant_id, absorbed=absorbed):
        await _set_state(tenant_id, agent_id, "skipped")
        return "skipped"
    feature = (
        ASSIST_FEATURE_BUSINESS_OUTCOMES_ABSORBED if absorbed else ASSIST_FEATURE_BUSINESS_OUTCOMES
    )
    description = await agent_context(tenant_id, agent_id, name=name, direction=direction)
    async with tenant_session(tenant_id) as session:
        tenant_leg = await account_assist_leg(session)
    try:
        answer: JsonAnswer[list[BusinessOutcome]] = await ask_json(
            description,
            SYSTEM_PROMPT,
            parse=_drafted,
            azure_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "business_outcomes_draft",
                    "strict": True,
                    "schema": _DRAFT_SCHEMA,
                },
            },
            tenant_leg=tenant_leg,
            max_tokens=DRAFT_MAX_TOKENS,
            temperature=0.2,
            timeout_s=DRAFT_TIMEOUT_S,
            health_leg="business_outcomes",
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        await _set_state(tenant_id, agent_id, "failed")
        log.warning(
            "business_outcomes_draft_failed",
            extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "code": refused.code},
        )
        return "failed"
    stored = await _store(tenant_id, agent_id, answer, feature=feature)
    return "stored" if stored else "kept_own"


async def draft_business_outcomes(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the agent's queued draft, ask the model once, store what came back."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE agents SET business_outcomes_draft = 'running', updated_at = now() "
                    "WHERE id = :aid AND business_outcomes_draft = 'queued' "
                    "AND deleted_at IS NULL RETURNING name, direction, business_outcomes"
                ),
                {"aid": agent_id},
            )
        ).first()
    if claimed is None:
        outcome = "not_queued"
    elif claimed[2] is not None:
        await _set_state(tenant_id, agent_id, "done")
        outcome = "kept_own"
    else:
        try:
            outcome = await _run(
                tenant_id, agent_id, name=str(claimed[0]), direction=str(claimed[1])
            )
        except Exception:
            log.exception(
                "business_outcomes_draft_crashed",
                extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
            )
            await _set_state(tenant_id, agent_id, "failed")
            outcome = "failed"
    log.info(
        "business_outcomes_draft_run",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "outcome": outcome},
    )
    return outcome


__all__ = [
    "JOB_NAME",
    "SYSTEM_PROMPT",
    "agent_context",
    "draft_business_outcomes",
    "outcomes_from_model",
]
