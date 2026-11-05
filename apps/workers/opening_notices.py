"""Writes the AI and recording notices into an agent's opening line, from the outbox (D-971).

Queued by `agents/opening_notices.queue_opening_notices` when an opening line put live, or a
notice switch moved, leaves the line not saying exactly the notices switched on. The opening
writer (`opening_line.write_opening`) is asked to repair the line with those problems named,
from the same brief every script writer reads, and the line is put live through
`script_builder.replace_opening_line`, which measures it against the engine's greeting
ceiling and refuses while other script changes wait to go live.

Every answer or refusal from a paid leg is metered under `ASSIST_FEATURE_SCRIPT_DRAFT`, as
Pip's other script writing is (hard rule 7).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from apps.api.agents import script_builder, script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.opening_notices import WEAVE_JOB, WEAVE_NOTE, OpeningToWeave, weave_state
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.opening_line import opening_problems, write_opening
from apps.workers.script_assist import JsonAnswer

log = get_logger(__name__)

JOB_NAME: Final = WEAVE_JOB


async def _meter(tenant_id: UUID, spends: list[JsonAnswer[str] | ProblemError]) -> None:
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    async with tenant_session(tenant_id) as session:
        for spent in spends:
            if isinstance(spent, ProblemError):
                await crm_assist.meter_refusal(
                    session, tenant_id=tenant_id, refusal=spent, feature=feature
                )
                continue
            await crm_assist.meter_earlier(
                session, tenant_id=tenant_id, earlier=spent.earlier, feature=feature
            )
            await crm_assist.meter_assist(
                session,
                tenant_id=tenant_id,
                ref=new_assist_ref(),
                result=spent,
                model=spent.model,
                feature=feature,
            )


async def weave_opening_notices(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    prompt_id = str(payload["prompt_id"])
    async with tenant_session(tenant_id) as session:
        state = await weave_state(session, agent_id)
        if state is None:
            return "gone"
        # A later version or a staged change: the publish of whatever is live next asks again.
        if str(state.prompt_id) != prompt_id or state.staged:
            return "stale"
        if not state.todo:
            return "already_said"
        brief = await script_proposals.brief_for(session, tenant_id, agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    names = (brief.business_name, brief.agent_name)
    spends: list[JsonAnswer[str] | ProblemError] = []
    written: list[tuple[OpeningToWeave, str]] = []
    for line in state.todo:
        problems = opening_problems(
            line.line,
            brief.language,
            names=names,
            introduced=brief.introduced,
            where=line.field,
            woven=brief.woven,
        )
        try:
            answer = await write_opening(
                brief,
                line=line.line,
                problems=problems,
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                placed=line.placed,
            )
        except ProblemError as refused:
            log.info(
                "opening_notices_unwritten", extra={"reason": refused.code, "field": line.field}
            )
            spends.append(refused)
            continue
        spends.append(answer)
        written.append((line, answer.value))
    applied = 0
    async with tenant_session(tenant_id) as session:
        for line, value in written:
            try:
                async with session.begin_nested():
                    await script_builder.replace_opening_line(
                        session,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        opening_line=value,
                        created_by=None,
                        placed=line.placed,
                        notes=WEAVE_NOTE,
                    )
                applied += 1
            except ProblemError as refused:
                # The stored sentences are still said beside the old line; the owner's next
                # change to the opening or a switch asks again.
                log.info(
                    "opening_notices_not_applied",
                    extra={"reason": refused.code, "field": line.field},
                )
    # Metered in its own transaction: a line refused at apply was still paid for.
    await _meter(tenant_id, spends)
    log.info(
        "opening_notices_woven",
        extra={"agent_id": str(agent_id), "written": len(written), "applied": applied},
    )
    return "woven" if applied else "unwritten"


__all__ = ["JOB_NAME", "weave_opening_notices"]
