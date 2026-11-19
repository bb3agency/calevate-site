"""The hourly sweep that gives agents' own engine agents to their lines and campaigns (D-1019).

`agents/engine_retirement.retire_for_tenant` for every account with an engine agent routed,
under one `WalkBudget` that resumes where the last tick stopped. It does nothing unless the
console's `agent_engine_retirement_sweep` is on (off by default: release R2 is run one client
at a time from the admin console first), and nothing while a publish still makes each agent
an engine agent of its own (`agents_still_get_their_own`). A held agent alarms once per
cause from the job itself; one account's failure is logged and walked again next hour.

Ids and counts in every log line (hard rule 6).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.engine_retirement import agents_still_get_their_own, retire_for_tenant
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

#: Accounts that ever had an engine agent routed, read untenanted (`agents` is invisible
#: here). Not only active routes: an account's erasure deactivates its routes while its agent
#: can still hold a ref, and a walk of active routes alone never reaches it.
_TENANTS_SQL: Final = (
    "SELECT DISTINCT tenant_id FROM engine_agent_routes "
    "WHERE tenant_id IS NOT NULL ORDER BY tenant_id"
)


async def sweep_agent_engine_retirement(ctx: dict[str, Any]) -> str:
    """Hourly. See the module docstring."""
    del ctx
    if not get_settings().agent_engine_retirement_sweep:
        return "off"
    if agents_still_get_their_own():
        log.info("agent_engine_retirement_sweep_skipped", extra={"reason": "agents_hold"})
        return "agents_still_hold_engine_agents"
    async with untenanted_session() as directory:
        tenants = [
            UUID(str(row)) for row in (await directory.execute(text(_TENANTS_SQL))).scalars()
        ]
    tally: dict[str, int] = {}
    failed = 0
    async for tenant_id in resumed_walk("agent_engine_retirement", tenants, WalkBudget()):
        try:
            run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)
        except Exception as exc:
            failed += 1
            log.warning(
                "agent_engine_retirement_sweep_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
            continue
        for agent in run.agents:
            tally[agent.outcome] = tally.get(agent.outcome, 0) + 1
    log.info(
        "agent_engine_retirement_sweep",
        extra={"tenants": len(tenants), "failed": failed, **tally},
    )
    counts = " ".join(f"{key}={value}" for key, value in sorted(tally.items()))
    return f"tenants={len(tenants)} failed={failed} {counts}".strip()


__all__ = ["sweep_agent_engine_retirement"]
