"""Keep every agent's engine webhook endpoint registered and switched on (D-678).

ThinnestAI attempts each delivery ONCE and switches an endpoint off after five failures in
a row (`thinnest-findings/mirror/pages/api-reference/webhooks.md:84-88`). The calls behind
those failures are settled by `pipeline.reconcile_executions` from the call list; this
sweep is the other half — it puts the endpoint back so the NEXT call's transcript arrives
by delivery, and it alarms, because an endpoint the vendor switched off means deliveries
were already being lost. It also registers an endpoint for any agent that has none (a
publish whose registration failed after the agent was created).

One `ensure_agent_webhook` per active route, each in its OWN tenant session: one tenant's
failure is counted and the sweep carries on, as every fleet-wide walk here does.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.engine_webhooks import WEBHOOK_ENGINES, ensure_agent_webhook

log = get_logger(__name__)

WEBHOOK_SWEEP_MINUTES: Final = frozenset({1, 21, 41})
#: Vendor round trips per sweep, at most. Twenty minutes later the rest are reached.
WEBHOOK_SWEEP_BUDGET: Final = 200


async def reconcile_engine_webhooks(ctx: dict[str, Any]) -> str:
    engine = get_settings().engine
    if engine not in WEBHOOK_ENGINES:
        return "engine_without_webhooks"
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, engine_agent_ref FROM engine_agent_routes "
                    "WHERE engine = :engine AND active "
                    "ORDER BY webhook_checked_at ASC NULLS FIRST LIMIT :budget"
                ),
                {"engine": engine, "budget": WEBHOOK_SWEEP_BUDGET},
            )
        ).all()
    reenabled = registered = unreached = 0
    for tenant_id, ref in rows:
        try:
            async with tenant_session(UUID(str(tenant_id))) as session:
                outcome = (
                    await ensure_agent_webhook(session, engine=engine, engine_agent_ref=str(ref))
                ).outcome
        except Exception as exc:
            log.warning(
                "engine_webhook_check_failed",
                extra={"engine": engine, "tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            unreached += 1
            continue
        if outcome == "reenabled":
            reenabled += 1
            alert(
                "WORKER_DELIVERY",
                "engine_webhook_reenabled",
                detail=(
                    f"engine={engine}: the vendor had switched this agent's webhook endpoint "
                    "off after repeated failed deliveries, and it is back on. Calls in the gap "
                    "are settled by the reconciliation re-drive from the engine's call record; "
                    "check why the receiver was failing."
                ),
                tenant_id=str(tenant_id),
                engine_agent_ref=str(ref),
            )
        elif outcome in ("registered", "replaced"):
            registered += 1
    if unreached:
        alert(
            "WORKER_DELIVERY",
            "engine_webhook_sweep_incomplete",
            detail=(
                f"{unreached} of {len(rows)} agent webhook endpoint(s) could not be checked; "
                "a switched-off endpoint among them is still losing deliveries. See "
                "engine_webhook_check_failed in the worker log."
            ),
            engine=engine,
        )
    return (
        f"checked={len(rows)} reenabled={reenabled} registered={registered} unreached={unreached}"
    )


__all__ = ["WEBHOOK_SWEEP_BUDGET", "WEBHOOK_SWEEP_MINUTES", "reconcile_engine_webhooks"]
