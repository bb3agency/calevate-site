"""Re-splices the business's pinned facts into every agent (`apps/api/teach/pinned.py`).

Under the tenant's knowledge lock, the order every publish path keeps (knowledge lock, then
agent rows). One transaction per agent, so one agent the engine refuses (an instructions box
over its limit, `engine_prompt_too_long`) does not hold back the others; that agent keeps
what it had and an operator is told.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.kb.service import lock_tenant_knowledge
from apps.api.teach.pinned import RECOMPILE_JOB, recompile_agent

log = get_logger(__name__)

JOB_NAME: Final = RECOMPILE_JOB


async def recompile_pinned_facts(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
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
    changed = 0
    refused = 0
    for agent_id in agent_ids:
        try:
            async with tenant_session(tenant_id) as session:
                await lock_tenant_knowledge(session, tenant_id=tenant_id)
                if await recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id):
                    changed += 1
        except ProblemError as exc:
            refused += 1
            log.warning(
                "pinned_facts_recompile_refused",
                extra={"agent_id": str(agent_id), "reason": exc.code},
            )
            alert(
                "CORE_LOGIC",
                "pinned_facts_not_delivered",
                detail=(
                    "An agent could not take the business's pinned facts and keeps the "
                    "previous ones. The reason code says why (often the instructions are "
                    "over the engine's limit)."
                ),
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
                reason=exc.code,
            )
    log.info(
        "pinned_facts_recompile_done",
        extra={"tenant_id": str(tenant_id), "changed": changed, "refused": refused},
    )
    return "done" if not refused else "partial"


__all__ = ["JOB_NAME", "recompile_pinned_facts"]
