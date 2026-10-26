"""Chooses the facts each agent knows by heart (`apps/api/agents/hot_facts.py`, D-896).

`recompute_hot_facts` runs from the outbox when a client's knowledge, pinned facts or profile
changes, and once a day for every client from `sweep_hot_facts`, because what callers ask
moves with the calls themselves. Each agent is chosen in its own transaction under the
tenant's knowledge lock (the order every publish path keeps), so one agent the engine
refuses does not hold back the others, and a refusal rolls its choice back to be tried again.
The job is idempotent: the same knowledge and calls choose the same set, and an unchanged set
writes and republishes nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.hot_facts import RECOMPUTE_JOB, recompute_agent, request_daily
from apps.api.billing.plans import IST
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine import get_engine
from apps.api.kb.service import lock_tenant_knowledge
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

#: The outbox job (`apps/api/agents/hot_facts.request_recompute`).
JOB_NAME: Final = RECOMPUTE_JOB

#: The daily sweep's IST firing time (`apps/workers/settings.py`).
SWEEP_HOUR: Final = 4
SWEEP_MINUTE: Final = 31

_AGENTS: Final = (
    "SELECT id FROM agents WHERE deleted_at IS NULL AND status <> 'archived' "
    "AND system_prompt_id IS NOT NULL ORDER BY created_at, id"
)

_DIRECTORY: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL "
    "AND status IN ('onboarding', 'active') ORDER BY id"
)


async def recompute_hot_facts(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    engine = get_engine()
    async with tenant_session(tenant_id) as session:
        agent_ids = [UUID(str(r[0])) for r in (await session.execute(text(_AGENTS))).all()]
    counts = {"unchanged": 0, "changed": 0, "republished": 0, "not_applicable": 0, "refused": 0}
    for agent_id in agent_ids:
        try:
            async with tenant_session(tenant_id) as session:
                await lock_tenant_knowledge(session, tenant_id=tenant_id)
                outcome = await recompute_agent(
                    session, tenant_id=tenant_id, agent_id=agent_id, engine=engine
                )
            counts[outcome] += 1
        except ProblemError as exc:
            counts["refused"] += 1
            log.warning("hot_facts_refused", extra={"agent_id": str(agent_id), "reason": exc.code})
            alert(
                "CORE_LOGIC",
                "hot_facts_not_delivered",
                detail=(
                    "An agent's facts known by heart could not be updated, so it keeps the "
                    "ones it had. The reason code says why."
                ),
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
                reason=exc.code,
            )
    log.info("hot_facts_recomputed", extra={"tenant_id": str(tenant_id), **counts})
    return json.dumps(counts)


async def _queue(tenant_id: UUID, *, day: str) -> None:
    async with tenant_session(tenant_id) as session:
        await request_daily(session, tenant_id=tenant_id, day=day)


async def sweep_hot_facts(ctx: dict[str, Any]) -> str:
    """Daily: queue every open client's choice once per IST day (`enqueue_outbox_once`), so
    a retried tick queues nothing twice."""
    del ctx
    day = datetime.now(UTC).astimezone(IST).date().isoformat()
    async with admin_session() as directory:
        tenant_ids = [UUID(str(r[0])) for r in (await directory.execute(text(_DIRECTORY))).all()]
    budget = WalkBudget()
    counts = {"queued": 0, "failed": 0}
    async for tenant_id in resumed_walk("hot_facts", tenant_ids, budget):
        try:
            await _queue(tenant_id, day=day)
            counts["queued"] += 1
        except Exception as exc:
            counts["failed"] += 1
            log.warning(
                "hot_facts_sweep_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    unreached = len(tenant_ids) - counts["queued"] - counts["failed"]
    log.info("hot_facts_sweep", extra={**counts, "unreached": unreached})
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "hot_facts_sweep_truncated",
            detail=(
                f"the daily choice of facts known by heart reached {len(tenant_ids) - unreached} "
                f"of {len(tenant_ids)} client(s) inside its time budget; the rest are chosen "
                "tomorrow or on their next knowledge change"
            ),
        )
    return json.dumps(counts)


__all__ = ["JOB_NAME", "SWEEP_HOUR", "SWEEP_MINUTE", "recompute_hot_facts", "sweep_hot_facts"]
