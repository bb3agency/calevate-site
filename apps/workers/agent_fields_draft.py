"""Draft what ONE agent writes down from its own script (founder, 3 Nov 2026).

A business-wide set (`lead_fields_draft`) cannot know that one agent checks whether a
farmer installed the Chrome app and another books soil tests. So once a new agent's script
is written for the business and put on it (`script_proposals.apply_untouched_starter`), its
details are drafted from that script: what the steps ask the caller for, beside the core
every lead carries. Applied at once, and only while the agent still has the set it was
made with; a set anybody changed is theirs and is never written over.

Queued by `script_proposals.apply_untouched_starter`. One request on the dashboard AI
ladder (`script_assist.ask_json`), no retry: a refusal leaves the starting set. The same
rules and parser as the business draft (`lead_fields_draft.fields_from_model`): no repeat
of the core, nothing sensitive, no phone field. What the model sees is the business's own
redacted description and the agent's script, never a caller, and nothing of it is logged.
Metered at our cost under `ASSIST_FEATURE_LEAD_FIELDS` and absorbed.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript, upgrade_to_v2
from calevate_shared.extraction import ExtractionField

from apps.api.agents import script_builder
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.extraction_routes import validate_fields, write_schema
from apps.api.agents.script_proposals import agent_own_fields
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_LEAD_FIELDS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.lead_fields_draft import (
    _DRAFT_SCHEMA,
    DRAFT_MAX_TOKENS,
    DRAFT_TIMEOUT_S,
    SYSTEM_PROMPT,
    business_context,
    fields_from_model,
)
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: The ARQ name; `script_proposals.AGENT_FIELDS_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "draft_agent_fields"

#: The business draft's instruction, pointed at one agent's own calls.
AGENT_PROMPT: Final = (
    SYSTEM_PROMPT
    + " The details are for ONE agent of this business: choose them from what its script "
    "asks the caller and what its steps find out, so the owner reads the outcome of each "
    "call at a glance."
)


def _script_brief(script: CallScript) -> str:
    lines = [f"What this agent's calls are for: {script.goal}".strip()]
    if script.outbound_purpose:
        lines.append(f"Why it calls: {script.outbound_purpose}")
    for i, stage in enumerate(script.stages, 1):
        lines.append(f"Step {i}, {stage.name}: {stage.instruction}")
    return "\n".join(lines)


def _drafted(raw: dict[str, Any]) -> list[ExtractionField] | None:
    return fields_from_model(raw) or None


async def draft_agent_fields(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Draft the agent's details from its script and apply them over its untouched set."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    started_with = payload.get("fields") or []
    try:
        description, _vertical = await business_context(tenant_id)
        async with tenant_session(tenant_id) as session:
            if await agent_own_fields(session, agent_id) != started_with:
                return "owner_changed"
            script = upgrade_to_v2(
                (await script_builder.load_agent_script(session, agent_id)).script
            )
            tenant_leg = await account_assist_leg(session)
        try:
            answer: JsonAnswer[list[ExtractionField]] = await ask_json(
                f"{description}\n\n{_script_brief(script)}",
                AGENT_PROMPT,
                parse=_drafted,
                azure_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "agent_fields",
                        "strict": True,
                        "schema": _DRAFT_SCHEMA,
                    },
                },
                tenant_leg=tenant_leg,
                max_tokens=DRAFT_MAX_TOKENS,
                temperature=0.2,
                timeout_s=DRAFT_TIMEOUT_S,
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
            log.info(
                "agent_fields_refused", extra={"agent_id": str(agent_id), "reason": refused.code}
            )
            return "refused"
        async with tenant_session(tenant_id) as session:
            # Checked again under the write: an owner who edited while the model answered
            # keeps their edit.
            applied = await agent_own_fields(session, agent_id) == started_with
            if applied:
                validate_fields(answer.value)
                await write_schema(session, agent_id=agent_id, fields=answer.value)
            await crm_assist.meter_earlier(
                session,
                tenant_id=tenant_id,
                earlier=answer.earlier,
                feature=ASSIST_FEATURE_LEAD_FIELDS,
            )
            await crm_assist.meter_assist(
                session,
                tenant_id=tenant_id,
                ref=new_assist_ref(),
                result=answer,
                feature=ASSIST_FEATURE_LEAD_FIELDS,
                model=answer.model,
            )
    except Exception:
        log.exception("agent_fields_crashed", extra={"agent_id": str(agent_id)})
        return "failed"
    log.info(
        "agent_fields_drafted",
        extra={"agent_id": str(agent_id), "count": len(answer.value), "applied": applied},
    )
    return "applied" if applied else "owner_changed"


__all__ = ["AGENT_PROMPT", "JOB_NAME", "draft_agent_fields"]
