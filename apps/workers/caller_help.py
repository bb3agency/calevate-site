"""Judge whether one agent's callers follow along on their own phone (founder, 5 Nov 2026).

Queued through the outbox by `agents/caller_help.queue_pass`, on the D-889 pass queue
(`agents/agent_pass`). One pass:

1. **Claim** the agent's `caller_help_state` from `queued` to `running`.
2. **Read** what the agent does: its latest saved script (with each section's small steps,
   D-908), its campaigns' names, purposes and goals, and the business's own details and
   analysis. Redacted before anything leaves (D-127 G-1/G-2); asked of our Gemini only, the
   lead-detail suggestions' rule, so an owner's script never reaches the Sarvam standby whose
   terms permit training on inputs.
3. **Nothing to judge?** An agent with no script and no campaign brief is stored as
   suggesting neither, at no cost: the founder's rule is that the judgement comes from what
   the agent does, and the business alone does not say that.
4. **Unchanged?** Inputs hashing as the last finished pass spend nothing.
5. **May it spend?** As the lead-detail suggestions: ours on a trial, the account's AI
   allowance otherwise; used up or the platform brake on, `skipped`.
6. **Ask once, clean, meter and store** in one transaction.

Nothing here is logged but ids, codes and counts (hard rule 6).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents import agent_pass
from apps.api.agents.assist_leg import google_assist_leg
from apps.api.agents.caller_help import JOB, REASON_MAX, SLOT, CallerHelp, Judgement
from apps.api.billing.ai_quota import new_assist_ref, platform_brake_tripped, require_ai_assist
from apps.api.billing.models import (
    ASSIST_FEATURE_CALLER_HELP,
    ASSIST_FEATURE_CALLER_HELP_ABSORBED,
)
from apps.api.billing.trials import trial_billing_active
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.tenancy import business_copy
from apps.workers.field_suggestions import script_text
from apps.workers.lead_fields_draft import business_context
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

JOB_NAME: Final = JOB
#: Part of the inputs hash, so a changed question re-judges every agent at its next trigger.
PROMPT_VERSION: Final = 1
TIMEOUT_S: Final = 30.0
MAX_TOKENS: Final = 400
SCRIPT_CHARS: Final = 6000
BUSINESS_CHARS: Final = 1500
CAMPAIGNS: Final = 5

SYSTEM_PROMPT: Final = (
    "You look at ONE phone agent of a small Indian business and answer two questions about "
    "the people it talks to, from what the agent's script and campaigns say it does on the "
    "call.\n"
    "screen_guide: during the call, does the agent walk the person through something on "
    "their own phone or computer, such as installing or opening an app, signing up or "
    "logging in, filling an online form, finding a page or a button, or paying online? Yes "
    "only when the script or a campaign says the agent does that ON the call. That the "
    "business has an app or website is not enough; sending a link to open later is not "
    "enough.\n"
    "give_time: during the call, does the agent ask the person to do something that keeps "
    "them quiet for a while, such as following steps on their phone, fetching a card or a "
    "document, reading a number off a bill, or checking with someone at home? A receptionist "
    "that answers questions, books, takes messages or transfers calls is no; so is an agent "
    "that only tells people about an offer.\n"
    "The business's own analysis is given as a hint about the business as a whole; this "
    "agent's script decides. When the inputs do not say, the answer is no.\n"
    "For each, reason: when yes, one plain English sentence for the owner saying what the "
    'agent does that makes it so, drawn from its script or campaign (for example: "She '
    f'walks farmers through installing the app step by step."), at most {REASON_MAX} '
    "characters, naming no technology company; when no, an empty string.\n"
    'Return ONLY JSON: {"screen_guide": {"suggested": bool, "reason": str}, '
    '"give_time": {"suggested": bool, "reason": str}}.'
)

_JUDGEMENT_SCHEMA: Final = {
    "type": "object",
    "properties": {"suggested": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["suggested", "reason"],
    "additionalProperties": False,
}
_ANSWER_SCHEMA: Final = {
    "type": "object",
    "properties": {"screen_guide": _JUDGEMENT_SCHEMA, "give_time": _JUDGEMENT_SCHEMA},
    "required": ["screen_guide", "give_time"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Inputs:
    #: The redacted text the model reads.
    description: str
    #: Whether the agent itself says anything: a script or a campaign brief.
    has_agent_words: bool

    def digest(self) -> str:
        body = json.dumps({"v": PROMPT_VERSION, "d": self.description}, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()


def _clip(value: Any, limit: int) -> str:
    words = " ".join(str(value or "").split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")


def agent_script_text(script: Any) -> str:
    """The script's words (`field_suggestions.script_text`) and each section's small steps,
    which are where an agent that guides a caller through their phone says so."""
    lines = [script_text(script)] if script_text(script) else []
    for stage in (script.get("stages") or []) if isinstance(script, dict) else []:
        if not isinstance(stage, dict):
            continue
        for step in stage.get("procedure") or []:
            if isinstance(step, dict) and step.get("action"):
                done = f" (done when: {step['wait_for']})" if step.get("wait_for") else ""
                lines.append(f"Small step in '{stage.get('name', '')}': {step['action']}{done}")
    return "\n".join(" ".join(str(line).split()) for line in lines)


async def gather(tenant_id: UUID, agent_id: UUID) -> Inputs:
    description, _vertical = await business_context(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent = (
            await session.execute(
                text(
                    # The latest saved script, staged or live: the owner's newest word on
                    # what this agent does.
                    "SELECT a.name, a.direction, pv.structured_script, pv.body FROM agents a "
                    "LEFT JOIN prompt_versions pv "
                    "ON pv.id = COALESCE(a.system_prompt_id, a.live_prompt_id) WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
        campaigns = (
            await session.execute(
                text(
                    "SELECT name, purpose, goal FROM campaigns WHERE agent_id = :aid "
                    "ORDER BY created_at DESC LIMIT :n"
                ),
                {"aid": agent_id, "n": CAMPAIGNS},
            )
        ).all()
        copy = await business_copy.read_state(session)
    name, direction, script, body = agent if agent is not None else ("", "", None, None)
    said = agent_script_text(script) or _clip(body, SCRIPT_CHARS)
    briefs = [
        f"Campaign '{c[0]}': why it calls: {c[1] or 'not given'}; a good call ends with: "
        f"{c[2] or 'not given'}"
        for c in campaigns
        if c[1] or c[2]
    ]
    job = {"inbound": "answers calls", "outbound": "places calls"}.get(
        str(direction), "answers and places calls"
    )
    parts = [f"The agent: '{name}', which {job}."]
    if said:
        parts.append("Its script:\n" + said[:SCRIPT_CHARS])
    if briefs:
        parts.append("Its campaigns:\n" + "\n".join(briefs))
    parts.append("The business:\n" + description[:BUSINESS_CHARS])
    guide = copy.copy.screen_guide if copy is not None and copy.copy is not None else None
    if guide is not None:
        verdict = "often" if guide.suggested else "not usually"
        hint = f": {guide.reason}" if guide.suggested and guide.reason else ""
        parts.append(
            f"The business's own analysis: its callers {verdict} use its app or website on a "
            f"call{hint}"
        )
    return Inputs(
        description=redact("\n\n".join(parts)).text,
        has_agent_words=bool(said or briefs),
    )


def _judgement(raw: Any) -> Judgement | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("suggested"), bool):
        return None
    if not raw["suggested"]:
        return Judgement(suggested=False)
    reason = _clip(raw.get("reason"), REASON_MAX)
    # A yes the owner cannot be told the reason for is not one to ask them about; and the
    # reason is shown to a client, who never sees a provider named (D-679).
    if not reason or business_copy.provider_problem("reason", reason):
        return None
    return Judgement(suggested=True, reason=reason)


def judgement_from_model(raw: dict[str, Any]) -> CallerHelp | None:
    """The model's answer, or None when it is unusable (the ladder's repair gets its chance).

    A caller following steps on a screen goes quiet while they do it, so a screen-guided
    agent is always suggested "Give callers time" too, with the screen reason when the model
    gave none of its own."""
    screen = _judgement(raw.get("screen_guide"))
    give_time = _judgement(raw.get("give_time"))
    if screen is None or give_time is None:
        return None
    if screen.suggested and not give_time.suggested:
        give_time = Judgement(suggested=True, reason=screen.reason)
    return CallerHelp(screen_guide=screen, give_time=give_time)


async def _blocked(tenant_id: UUID, *, absorbed: bool) -> bool:
    async with tenant_session(tenant_id) as session:
        if absorbed:
            return await platform_brake_tripped(session)
        try:
            await require_ai_assist(session, tenant_id=tenant_id)
        except ProblemError:
            return True
    return False


async def _store(
    tenant_id: UUID,
    agent_id: UUID,
    inputs: Inputs,
    judged: CallerHelp,
    answer: JsonAnswer[CallerHelp] | None,
    *,
    feature: str,
) -> None:
    """Meter the answer and store the judgement and the inputs hash in ONE transaction."""
    async with tenant_session(tenant_id) as session:
        if answer is not None:
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
        closed = (
            await session.execute(
                text(
                    "UPDATE agents SET caller_help = CAST(:j AS jsonb), caller_help_inputs = :h, "
                    "caller_help_state = CASE WHEN caller_help_state = 'running' "
                    "  THEN 'done' ELSE caller_help_state END, "
                    "caller_help_at = now(), updated_at = now() "
                    "WHERE id = :aid RETURNING caller_help_state"
                ),
                {"aid": agent_id, "h": inputs.digest(), "j": judged.model_dump_json()},
            )
        ).scalar()
        if closed == "queued":
            await agent_pass.requeue_if_asked(session, SLOT, tenant_id=tenant_id, agent_id=agent_id)


async def _finish(tenant_id: UUID, agent_id: UUID, state: str) -> None:
    async with tenant_session(tenant_id) as session:
        await agent_pass.finish(session, SLOT, tenant_id=tenant_id, agent_id=agent_id, state=state)


def _parse(raw: dict[str, Any]) -> CallerHelp | None:
    return judgement_from_model(raw)


async def _run(tenant_id: UUID, agent_id: UUID, *, previous: str | None) -> str:
    inputs = await gather(tenant_id, agent_id)
    if previous == inputs.digest():
        await _finish(tenant_id, agent_id, "done")
        return "unchanged"
    if not inputs.has_agent_words:
        neither = CallerHelp(
            screen_guide=Judgement(suggested=False), give_time=Judgement(suggested=False)
        )
        await _store(tenant_id, agent_id, inputs, neither, None, feature="")
        return "nothing_to_judge"
    async with tenant_session(tenant_id) as session:
        absorbed = await trial_billing_active(session, tenant_id=tenant_id)
    if await _blocked(tenant_id, absorbed=absorbed):
        await _finish(tenant_id, agent_id, "skipped")
        return "skipped"
    feature = ASSIST_FEATURE_CALLER_HELP_ABSORBED if absorbed else ASSIST_FEATURE_CALLER_HELP
    leg = google_assist_leg()
    if not leg.serves_dashboard:
        alert(
            "CORE_LOGIC",
            "caller_help_unavailable",
            detail="The Gemini leg the caller-help judgement uses cannot serve; none was made.",
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
        await _finish(tenant_id, agent_id, "failed")
        return "failed"
    try:
        answer: JsonAnswer[CallerHelp] = await ask_json(
            inputs.description,
            SYSTEM_PROMPT,
            parse=_parse,
            azure_format={
                "type": "json_schema",
                "json_schema": {"name": "caller_help", "strict": True, "schema": _ANSWER_SCHEMA},
            },
            tenant_leg=leg,
            max_tokens=MAX_TOKENS,
            temperature=0.1,
            timeout_s=TIMEOUT_S,
            health_leg="caller_help",
            gemini_only=True,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        await _finish(tenant_id, agent_id, "failed")
        log.warning(
            "caller_help_failed",
            extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "code": refused.code},
        )
        return "failed"
    await _store(tenant_id, agent_id, inputs, answer.value, answer, feature=feature)
    return "stored"


async def judge_caller_help(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the agent's queued pass, read, ask once, store the judgement."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    async with tenant_session(tenant_id) as session:
        claimed, previous = await agent_pass.claim(session, SLOT, agent_id=agent_id)
    if not claimed:
        outcome = "not_queued"
    else:
        try:
            outcome = await _run(tenant_id, agent_id, previous=previous)
        except Exception:
            log.exception(
                "caller_help_crashed",
                extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
            )
            await _finish(tenant_id, agent_id, "failed")
            outcome = "failed"
    log.info(
        "caller_help_run",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "outcome": outcome},
    )
    return outcome


__all__ = [
    "JOB_NAME",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "Inputs",
    "agent_script_text",
    "gather",
    "judge_caller_help",
    "judgement_from_model",
]
