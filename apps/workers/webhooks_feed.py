"""The events feed's 30-day sweep (D-1049, `integrations/feed.py`).

Daily, every account, in each account's own session (the table is FORCE-RLS'd), in
bounded deletes. A feed row is a copy of a lead's or a call's data, so it is kept no longer
than the feed promises to serve it.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import admin_session, tenant_session
from apps.api.integrations import feed
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

#: 03:27 IST, at a minute no other fleet-wide walk uses (`tests/job_registration_test.py`).
FEED_SWEEP_HOUR_UTC: Final = 21
FEED_SWEEP_MINUTE: Final = 57
#: Rows one statement deletes; the loop stops at the first short batch.
SWEEP_BATCH: Final = 5000
_MAX_BATCHES: Final = 40

_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"
#: Older than the window, in bounded deletes. Runs in the account's own session (FORCE RLS).
_SWEEP_SQL: Final = (
    "DELETE FROM integration_events WHERE id IN (SELECT id FROM integration_events "
    "WHERE created_at < now() - CAST(:retention AS interval) LIMIT :batch)"
)


async def _sweep_tenant(tenant_id: UUID) -> int:
    removed = 0
    async with tenant_session(tenant_id) as session:
        for _ in range(_MAX_BATCHES):
            result = await session.execute(
                text(_SWEEP_SQL), {"retention": feed.FEED_RETENTION, "batch": SWEEP_BATCH}
            )
            batch = int(rowcount_of(result) or 0)
            removed += batch
            if batch < SWEEP_BATCH:
                break
    return removed


async def sweep_integration_events(ctx: dict[str, Any]) -> str:
    del ctx
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    removed = failed = probed = 0
    budget = WalkBudget()
    async for tenant_id in resumed_walk("integration_events_sweep", tenants, budget):
        probed += 1
        try:
            removed += await _sweep_tenant(tenant_id)
        except Exception as exc:
            failed += 1
            log.error(
                "integration_events_sweep_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    if failed or probed < len(tenants):
        alert(
            "WORKER_TERMINAL",
            "integration_events_sweep_incomplete",
            detail=(
                f"{failed} account(s) failed and {len(tenants) - probed} were not reached; "
                "their events older than 30 days are still held. Tomorrow's run tries again."
            ),
        )
    return f"removed={removed} failed={failed} probed={probed}"


__all__ = ["FEED_SWEEP_HOUR_UTC", "FEED_SWEEP_MINUTE", "sweep_integration_events"]
